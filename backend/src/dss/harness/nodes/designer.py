"""Designer node: the planner designs each page as HTML/CSS around its component slots.

architecture.md#Designed pages. Page 1 goes first and sets the canvas width and the shared
stylesheet; pages 2-n then run in parallel with both as input. Each page gets one repair turn with
the sanitizer and measure errors, then falls back to the code layout and kit. If page 1 falls back,
the build keeps the code path at width 1200 and no other page is designed. Raw model output is
guarded and never logged or traced; spans carry counts only.
"""
import asyncio
from contextlib import aclosing
import re
from typing import NamedTuple

from google.adk.models.llm_request import LlmRequest
from google.genai import types
from pydantic import Field, ValidationError

from dss.harness.context import designer_context, fit_request, tokens
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.style_extract import provider_schema
from dss.render import design_page
from dss.spec.layout import design_decoration, synthetic_decoration
from dss.spec.models import Box, Design, Model
from dss.spec.validate import validate_spec

MAX_OUTPUT_TOKENS = 16000  # thinking included (low thinking level)
FOOTER = 64  # px under page 1 of a synthetic build; code draws the sample-data label there
MAX_ERRORS = 20  # errors sent back on the repair turn
WIDTHS = (1200, 1440, 1920)  # page 1's minimum slot widths are listed at these canvas widths
PAGE_ROOT = re.compile(r'\.dss-design-p[1-9][0-9]*(?![\w-])')
STYLE = re.compile(r'<style>(.*?)</style>', re.S)
ALL_FALLBACK = 'The page design did not pass its checks, so every page uses the standard layout.'


class FirstPage(Model):
    canvas_width: int = Field(ge=design_page.MIN_WIDTH, le=design_page.MAX_WIDTH, strict=True)
    html: str = Field(min_length=1)


class LaterPage(Model):
    html: str = Field(min_length=1)


class Designed(NamedTuple):
    html: str  # sanitized for its page
    boxes: dict
    height: int
    width: int
    css: str  # this page's stylesheet as the model reads it (page root written `body`)


class Fallback(NamedTuple):
    reason: str


def readable(clean):
    """Sanitized HTML as the model wrote it: the code-owned page root class reads `body` again
    (the sanitizer scopes `body` back to the root)."""
    return PAGE_ROOT.sub('body', clean)


async def design(spec, get_model, trace, *, secrets=(), report=None, keep=frozenset()):
    """(spec, notes): `spec` with every page that passed designed, or `spec` itself when page 1
    falls back. `notes` are assistant-message sentences for each fallback. `get_model()` gives the
    planner model (called once, only here); `report(totals)` emits the run's token usage. Pages in
    `keep` (indexes whose decorations a requirement names) stay code-laid with no model call."""
    if 1 in keep:
        trace.spans.append({'node': 'designer_fallback', 'page': 1, 'reason': 'requirements', 'errors': 0})
        return spec, [ALL_FALLBACK]
    try:
        model = get_model()
    except RunError:
        trace.spans.append({'node': 'designer_fallback', 'page': 1, 'reason': 'model', 'errors': 0})
        return spec, [ALL_FALLBACK]
    trace.model = model.model
    fonts = (spec.theme.font_family,)
    theme = {'title': spec.title, 'theme': spec.theme.model_dump()}

    async def usage(metadata, span):
        span.update(input_tokens=metadata.prompt_token_count or 0, output_tokens=metadata.candidates_token_count or 0)
        trace.input_tokens += metadata.prompt_token_count or 0
        trace.output_tokens += metadata.candidates_token_count or 0
        if report is not None:
            await report({'input_tokens': trace.input_tokens, 'output_tokens': trace.output_tokens})

    async def page_design(page, first):
        """One page: an answer, then at most one repair; Designed or Fallback. Shares nothing
        mutable with the other pages but the append-only trace."""
        if page.index in keep:
            trace.spans.append({'node': 'designer_fallback', 'page': page.index, 'reason': 'requirements', 'errors': 0})
            return Fallback('requirements')
        slots = {c.id: c.type for c in page.components}
        footer = FOOTER if page.index == 1 and spec.datasource.synthetic else None
        schema = FirstPage if first is None else LaterPage
        shared = None if first is None else {'canvas_width': first.width, 'css': first.css}
        info = {'index': page.index, 'name': page.name, 'pages': len(spec.pages)}
        if first is None:
            info['synthetic_footer'] = footer is not None
            info['components'] = [{'id': c.id, 'type': c.type, 'label': c.label,
                                   'min_w': {str(w): design_page.minimum(c.type, w)[0] for w in WIDTHS},
                                   'min_h': design_page.minimum(c.type, WIDTHS[0])[1]} for c in page.components]
        else:
            info['canvas_width'] = first.width
            info['components'] = [{'id': c.id, 'type': c.type, 'label': c.label,
                                   'min_w': design_page.minimum(c.type, first.width)[0],
                                   'min_h': design_page.minimum(c.type, first.width)[1]} for c in page.components]
        repair, errors = None, []
        try:
            for attempt in (1, 2):
                trace.span('designer')
                span = trace.spans[-1]
                span.update(page=page.index, attempt=attempt)
                memory = designer_context(theme, info, shared=shared, repair=repair)
                check_reply(memory, secrets)
                request = LlmRequest(model=model.model, config=types.GenerateContentConfig(
                    system_instruction=str(memory), response_mime_type='application/json',
                    response_json_schema=provider_schema(schema), max_output_tokens=MAX_OUTPUT_TOKENS,
                    thinking_config=types.ThinkingConfig(thinking_level='LOW')),
                    contents=[types.Content(role='user', parts=[types.Part(text='Return the page design JSON only.')])])
                await fit_request(memory, request, model, span)
                raw, cut = await _generate(model, request, lambda metadata: usage(metadata, span))
                if raw.strip():
                    check_reply(raw, secrets)
                trace.span('validate')
                check = trace.spans[-1]
                check.update(page=page.index, attempt=attempt)
                own = None
                if cut:
                    errors = [{'path': 'answer', 'message': 'The answer reached the output limit and was cut off: '
                                                            'write shorter HTML and CSS'}]
                elif not raw.strip():
                    errors = [{'path': 'answer', 'message': 'The answer was empty: return the JSON object'}]
                else:
                    try:
                        answer = schema.model_validate_json(raw)
                    except ValidationError as exc:
                        errors = [{'path': 'answer.' + '.'.join(map(str, e['loc'])), 'message': e['msg']}
                                  for e in exc.errors(include_input=False)]
                    else:
                        own = answer.html
                        width = first.width if first is not None else answer.canvas_width
                        html = own if first is None else f'<style>{first.css}</style>' + own
                        measured = await asyncio.to_thread(design_page.measure, html, slots, width,
                                                           footer=footer, fonts=fonts)
                        errors = measured.errors
                check.update(errors=len(errors))
                if not errors:
                    clean = design_page.sanitize(html, page=page.index, fonts=fonts)
                    css = STYLE.match(clean)
                    return Designed(clean, measured.boxes, measured.height, width,
                                    readable(css.group(1)) if css else '')
                repair = {'errors': errors[:MAX_ERRORS]}
                if own is not None:
                    # The model's own markup, with icon names rather than the inlined SVGs.
                    repair['html'] = own
            reason = 'invalid'
        except RunError as exc:
            reason = 'over_budget' if exc.detail.get('reason') == 'over_budget' else 'model'
        except Exception:
            # Provider and Chromium errors may echo request text: keep only the fact.
            reason = 'error'
        trace.spans.append({'node': 'designer_fallback', 'page': page.index, 'reason': reason, 'errors': len(errors)})
        return Fallback(reason)

    first = await page_design(spec.pages[0], None)
    if isinstance(first, Fallback):
        return spec, [ALL_FALLBACK]
    results = [first, *await asyncio.gather(*(page_design(page, first) for page in spec.pages[1:]))]
    designed = assemble(spec, results, model.model)
    # The assembled spec must validate; a page it rejects is a fallback page (page 1: all pages).
    errors = validate_spec(designed)
    bad = {int(e['path'].split('.')[1]) if re.match(r'pages\.\d+\.', e['path']) else 0 for e in errors}
    if bad and 0 not in bad:
        for p in bad:
            if isinstance(results[p], Designed):
                trace.spans.append({'node': 'designer_fallback', 'page': p + 1, 'reason': 'spec', 'errors': len(errors)})
                results[p] = Fallback('spec')
        designed = assemble(spec, results, model.model)
        bad = {0} if validate_spec(designed) else set()
    if bad:
        trace.spans.append({'node': 'designer_fallback', 'page': 1, 'reason': 'spec', 'errors': len(errors)})
        return spec, [ALL_FALLBACK]
    notes = [f'Page {page.index} uses the standard layout: its design did not pass its checks.'
             for page, result in zip(spec.pages, results) if isinstance(result, Fallback)]
    return designed, notes


def assemble(spec, results, model_name):
    """A copy of the code-laid spec at page 1's width: each designed page gets its design, the
    `p<n>_design` decoration (plus the synthetic footer on page 1), measured boxes and height;
    a fallback page keeps its code layout and kit."""
    designed = spec.model_copy(deep=True)
    designed.canvas.width = results[0].width
    for page, result in zip(designed.pages, results):
        if isinstance(result, Fallback):
            continue
        page.design = Design(html=result.html, source='designer', model=model_name)
        page.height = result.height
        for component in page.components:
            component.box = Box(**result.boxes[component.id])
        page.decorations = [design_decoration(page.index, result.height, designed.grid)]
        if page.index == 1 and designed.datasource.synthetic:
            grid = designed.grid
            top = result.height - FOOTER - grid.margin  # design_page.footer_top of the natural height
            page.decorations.append(synthetic_decoration((top - grid.margin) // grid.row_height + 1))
    designed.canvas.height = designed.pages[0].height
    return designed


async def _generate(model, request, usage):
    """(raw text, cut off) from one non-streamed call; thought parts are never part of the answer."""
    final = None
    async with aclosing(model.generate_content_async(request, stream=False)) as responses:
        async for response in responses:
            if not response.partial:
                final = response
    if final is None:
        raise RunError('llm_unavailable', 'The designer call failed', 503)
    metadata = final.usage_metadata
    if metadata is not None:
        await usage(metadata)
    # Truncation first: ADK reports thinking that used the whole budget as error_code MAX_TOKENS.
    truncated = final.finish_reason == types.FinishReason.MAX_TOKENS or final.error_code == 'MAX_TOKENS'
    if final.error_code and not truncated:
        raise RunError('llm_unavailable', 'The designer call failed', 503)
    raw = ''.join(p.text for p in (final.content.parts or []) if p.text and not p.thought) if final.content else ''
    cut = (truncated or tokens(raw) > MAX_OUTPUT_TOKENS
           or bool(metadata and (metadata.candidates_token_count or 0) > MAX_OUTPUT_TOKENS))
    return raw, cut
