"""HTML/CSS around code-owned native slots: planner for builds without a reference; a counted
planner brief then worker HTML for reference builds, each with a separate cancellable deadline.

architecture.md#Designed pages. Page 1 goes first and sets the canvas width and the shared
stylesheet; pages 2-n then run in parallel with both as input. Each page gets one repair turn with
the sanitizer and measure errors. Reference failures stop the candidate publication; builds without
references retain the code layout and kit fallback. Raw model output is
guarded and never logged or traced; spans carry counts only.
"""
import asyncio
from contextlib import aclosing
import re
import time
from typing import NamedTuple

from google.adk.models.llm_request import LlmRequest
from google.genai import types
from pydantic import Field, ValidationError

from dss.harness.context import designer_context, reference_html_context, fit_request, tokens
from dss.harness.guardrails import RunError, check_reply
from dss.harness.nodes.style_extract import provider_schema
from dss.render import design_page
from dss.spec.layout import design_decoration, synthetic_decoration
from dss.spec.models import Box, Design, Model
from dss.spec.validate import validate_spec

MAX_OUTPUT_TOKENS = 16000  # thinking included (low thinking level)
HTML_STAGE_SECONDS = 600  # one deadline for counting, transport retry, measurement and one repair
FOOTER = 64  # px under page 1 of a synthetic build; code draws the sample-data label there
MAX_ERRORS = 20  # errors sent back on the repair turn
WIDTHS = (1200, 1440, 1920)  # page 1's minimum slot widths are listed at these canvas widths
PAGE_ROOT = re.compile(r'\.dss-design-p[1-9][0-9]*(?![\w-])')
STYLE = re.compile(r'<style>(.*?)</style>', re.S)
ALL_FALLBACK = 'The page design did not pass its checks, so every page uses the standard layout.'


def reference_failed(page, failure, trace=None):
    """Code-owned failure details only; never echo validation/provider text into a run error."""
    stages = [s['node'] for s in trace.spans if s.get('page') == page
              and s['node'] in ('reference_brief', 'reference_html')] if trace is not None else []
    raise RunError('invalid_request',
                   f'Reference design failed on page {page} ({failure.reason}); previous prototype retained',
                   422, {'stage': stages[-1] if stages else 'reference_html', 'page': page, 'reason': failure.reason})


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
    errors: tuple = ()  # the last attempt's ({path, message}, ...), at most MAX_ERRORS


class ReferenceDesign(NamedTuple):
    reference: object
    approved: dict
    get_brief: object
    get_html: object
    failure: Fallback | None = None


def reference_design(folder, snapshot, ledger, checker, models):
    """Prepare ephemeral reference-stage inputs from the current candidate, after feasibility.
    A broken reference refuses publication; absence keeps the old designer.
    This function does not call a model or persist anything."""
    from dss.harness.nodes import reference_brief as rb
    from dss.spec import requirements as req
    try:
        reference = rb.reference(folder)
    except RunError:
        return ReferenceDesign(None, {}, None, None, Fallback('reference'))
    if reference is None:
        return None
    if (ledger.assessment is None or ledger.assessment.state != 'ready'
            or req.new_sources(snapshot, ledger) or req.evaluate(snapshot, ledger, checker).state != 'ready'):
        return ReferenceDesign(reference, {}, None, None, Fallback('feasibility'))
    return ReferenceDesign(reference, rb.report(snapshot, ledger, checker),
                           lambda: models.llm_for('reference_brief'), lambda: models.llm_for('reference_html'))


ICON = re.compile(r'(<i\b[^>]*\bdata-icon="([^"]*)"[^>]*>)<svg\b.*?</svg>(</i>)', re.S)


def readable(clean):
    """Sanitized HTML as the model wrote it: the code-owned page root class reads `body` again
    (the sanitizer scopes `body` back to the root) and a vendored icon is its name again."""
    clean = ICON.sub(lambda m: m[1] + m[3] if m[2] in design_page.icons() else m[0], clean)
    return PAGE_ROOT.sub('body', clean)


async def design(spec, get_model, trace, *, secrets=(), report=None, keep=frozenset(), reference=None):
    """(spec, notes): `spec` with every page that passed designed, or `spec` itself when page 1
    falls back. `notes` are assistant-message sentences for each fallback. `get_model()` gives the
    planner model for a build without references; `reference` supplies the two stage getters and
    current approved-component reports otherwise. `report(totals)` emits the run's token usage. Pages in
    `keep` (indexes whose decorations a requirement names) stay code-laid with no model call."""
    if 1 in keep:
        trace.spans.append({'node': 'designer_fallback', 'page': 1, 'reason': 'requirements', 'errors': 0})
        if reference is not None:
            reference_failed(1, Fallback('requirements'))
        return spec, [ALL_FALLBACK]
    if reference is not None and reference.failure:
        trace.spans.append({'node': 'designer_fallback', 'page': 1, 'reason': reference.failure.reason, 'errors': 0})
        reference_failed(1, reference.failure)
        return spec, [ALL_FALLBACK]
    try:
        model = reference.get_html() if reference is not None else get_model()
    except RunError:
        trace.spans.append({'node': 'designer_fallback', 'page': 1, 'reason': 'model', 'errors': 0})
        if reference is not None:
            reference_failed(1, Fallback('model'))
        return spec, [ALL_FALLBACK]
    trace.model = model.model

    async def page_design(page, first):
        if page.index in keep:
            trace.spans.append({'node': 'designer_fallback', 'page': page.index, 'reason': 'requirements', 'errors': 0})
            return Fallback('requirements')
        run_page = _reference_page if reference is not None else _page
        kwargs = {'reference': reference} if reference is not None else {}
        result = await run_page(model, spec, page, trace, first=first, secrets=secrets, report=report, **kwargs)
        if isinstance(result, Fallback):
            trace.spans.append({'node': 'designer_fallback', 'page': page.index, 'reason': result.reason,
                                'errors': len(result.errors)})
        return result

    first = await page_design(spec.pages[0], None)
    if isinstance(first, Fallback):
        if reference is not None:
            reference_failed(1, first, trace)
        return spec, [ALL_FALLBACK]
    # Settle siblings before candidate cleanup, including unexpected exceptions.
    later = await asyncio.gather(*(page_design(page, first) for page in spec.pages[1:]),
                                 return_exceptions=reference is not None)
    if reference is not None:
        for page, result in zip(spec.pages[1:], later):
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                reference_failed(page.index, Fallback('error'), trace)
            if isinstance(result, Fallback):
                reference_failed(page.index, result, trace)
    results = [first, *later]
    designed = assemble(spec, results, model.model)
    # The assembled spec must validate; a page it rejects is a fallback page (page 1: all pages).
    errors = validate_spec(designed)
    if errors and reference is not None:
        trace.spans.append({'node': 'designer_fallback', 'page': 1, 'reason': 'spec', 'errors': len(errors)})
        reference_failed(1, Fallback('spec'))
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


async def regenerate(spec, comments, get_model, trace, *, secrets=(), report=None, reference=None):
    """Revise on designed pages (architecture.md#Designed pages): each page in `comments`
    ({page index: [comment, ...]}) is designed again from its previous HTML and its comments at
    the spec's canvas width (sanitize, measure, one repair), all pages in parallel. (spec, {})
    with those pages replaced (source "revise"), or (None, {page index: Fallback}) for the pages
    that failed, in which case nothing is replaced. The reviser's trace keeps its model name."""
    if reference is not None and reference.failure:
        return None, {index: reference.failure for index in comments}
    try:
        model = reference.get_html() if reference is not None else get_model()
    except RunError:
        return None, {index: Fallback('model') for index in comments}
    pages = [spec.pages[index - 1] for index in sorted(comments)]
    run_page = _reference_page if reference is not None else _page
    kwargs = {'reference': reference} if reference is not None else {}
    results = await asyncio.gather(*(run_page(model, spec, page, trace, secrets=secrets, report=report, revision={
        'html': readable(page.design.html), 'comments': comments[page.index]}, **kwargs) for page in pages),
        return_exceptions=reference is not None)
    if reference is not None:
        for n, result in enumerate(results):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                results[n] = Fallback('error')
    failed = {page.index: result for page, result in zip(pages, results) if isinstance(result, Fallback)}
    for index, result in failed.items():
        trace.spans.append({'node': 'redesign_failed', 'page': index, 'reason': result.reason, 'errors': len(result.errors)})
    if failed:
        return None, failed
    revised = spec.model_copy(deep=True)
    for page, result in zip(pages, results):
        _place(revised, revised.pages[page.index - 1], result, Design(html=result.html, source='revise', model=model.model))
    revised.canvas.height = revised.pages[0].height
    if reference is not None and validate_spec(revised):
        return None, {page.index: Fallback('spec') for page in pages}
    return revised, {}


async def _reference_page(model, spec, page, trace, *, reference, first=None, revision=None, secrets=(), report=None):
    """Brief then HTML, in the same run. The outer HTML deadline includes both attempts and
    all counting/transport retries. CancelledError propagates through both model streams."""
    from dss.harness.nodes import reference_brief as rb
    try:
        brief_model = reference.get_brief()
    except RunError:
        return Fallback('model')
    shared = None if first is None else {'canvas_width': first.width, 'css': first.css}
    approved = reference.approved[page.index]
    brief = await rb.brief(brief_model, reference.reference, approved, spec, page, trace,
                           shared=shared, revision=revision, secrets=secrets, report=report)
    if isinstance(brief, Fallback):
        return brief
    started = time.monotonic()
    try:
        async with asyncio.timeout(HTML_STAGE_SECONDS) as deadline:
            return await _page(model, spec, page, trace, first=first, revision=revision, secrets=secrets,
                               report=report, reference=(reference.reference, approved, brief, deadline))
    except TimeoutError:
        # Count-only metadata; never retain provider content or HTML in a trace.
        trace.spans.append({'node': 'reference_html_timeout', 'page': page.index, 'model': model.model,
                            'reason': 'timeout', 'duration_ms': round((time.monotonic() - started) * 1000)})
        return Fallback('timeout')
    finally:
        duration = round((time.monotonic() - started) * 1000)
        for span in trace.spans:
            if span.get('node') == 'reference_html' and span.get('page') == page.index:
                span['stage_duration_ms'] = duration
                span.setdefault('duration_ms', duration)  # includes refusals before counting


async def _page(model, spec, page, trace, *, first=None, revision=None, secrets=(), report=None, reference=None):
    """One page: an answer, then at most one repair; Designed or Fallback(reason, errors). Page 1
    of a new design (`first` None, no `revision`) chooses the width; a later page gets page 1's
    width and stylesheet (`first`); a revision keeps the spec's width and returns its whole page.
    Shares nothing mutable with the other pages but the append-only trace."""
    fonts = (spec.theme.font_family,)
    theme = {'title': spec.title, 'theme': spec.theme.model_dump()}
    slots = {c.id: c.type for c in page.components}
    footer = FOOTER if page.index == 1 and spec.datasource.synthetic else None
    opening = first is None and revision is None
    schema = FirstPage if opening else LaterPage
    shared = None if first is None else {'canvas_width': first.width, 'css': first.css}
    fixed = first.width if first is not None else spec.canvas.width if revision is not None else None
    info = {'index': page.index, 'name': page.name, 'pages': len(spec.pages)}
    if opening:
        info['synthetic_footer'] = footer is not None
        info['components'] = [{'id': c.id, 'type': c.type, 'label': c.label,
                               'min_w': {str(w): design_page.minimum(c.type, w)[0] for w in WIDTHS},
                               'min_h': design_page.minimum(c.type, WIDTHS[0])[1]} for c in page.components]
    else:
        info['canvas_width'] = fixed
        if revision is not None:
            info['synthetic_footer'] = footer is not None
        info['components'] = [{'id': c.id, 'type': c.type, 'label': c.label,
                               'min_w': design_page.minimum(c.type, fixed)[0],
                               'min_h': design_page.minimum(c.type, fixed)[1]} for c in page.components]

    async def usage(metadata, span):
        span.update(input_tokens=metadata.prompt_token_count or 0, output_tokens=metadata.candidates_token_count or 0)
        trace.input_tokens += metadata.prompt_token_count or 0
        trace.output_tokens += metadata.candidates_token_count or 0
        if report is not None:
            await report({'input_tokens': trace.input_tokens, 'output_tokens': trace.output_tokens})

    repair, errors = None, []
    try:
        for attempt in (1, 2):
            if reference is not None:
                if asyncio.get_running_loop().time() >= reference[3].when():
                    raise TimeoutError
            trace.span('reference_html' if reference is not None else 'designer')
            span = trace.spans[-1]
            span.update(page=page.index, attempt=attempt)
            if reference is None:
                memory = designer_context(theme, info, shared=shared, repair=repair, revision=revision)
            else:
                ref, approved, brief, _ = reference
                span.update(model=model.model, images=len(ref.images), output_budget=MAX_OUTPUT_TOKENS,
                            input_budget=12000 if attempt == 1 else 24000)
                memory = reference_html_context(
                    {'mode': ref.mode, 'images': list(ref.described), 'instructions': ref.instructions, **ref.notes},
                    brief.model_dump(mode='json'), theme, info, approved,
                    shared=shared, repair=repair, revision=revision, attempt=attempt)
            check_reply(memory, secrets)
            request = LlmRequest(model=model.model, config=types.GenerateContentConfig(
                system_instruction=str(memory), response_mime_type='application/json',
                response_json_schema=provider_schema(schema), max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_level='LOW')),
                contents=[types.Content(role='user', parts=[types.Part(text='Return the page design JSON only.'),
                    *(types.Part.from_bytes(data=data, mime_type=mime)
                      for mime, data in (ref.images if reference is not None else ()))])])
            started = time.monotonic()
            try:
                await fit_request(memory, request, model, span)
                raw, cut = await _generate(model, request, lambda metadata: usage(metadata, span))
            finally:
                if reference is not None:
                    span['duration_ms'] = round((time.monotonic() - started) * 1000)
            if reference is not None:
                span['truncated'] = cut
            if raw.strip():
                check_reply(raw, secrets)
            trace.span('validate')
            check = trace.spans[-1]
            check.update(page=page.index, attempt=attempt)
            own = None
            category = 'schema'
            if cut:
                category = 'truncated'
                errors = [{'path': 'answer', 'message': 'The answer reached the output limit and was cut off: '
                                                        'write shorter HTML and CSS'}]
            elif not raw.strip():
                category = 'empty'
                errors = [{'path': 'answer', 'message': 'The answer was empty: return the JSON object'}]
            else:
                try:
                    answer = schema.model_validate_json(raw)
                except ValidationError as exc:
                    if reference is not None:
                        # Unknown JSON keys are provider text too: never feed an arbitrarily
                        # long key (or a parser diagnostic containing it) into the repair.
                        errors = [{'path': 'answer.' + e['loc'][0] if len(e['loc']) == 1
                                   and e['loc'][0] in ('html', 'canvas_width') else 'answer',
                                   'message': f"Invalid page JSON ({e['type']}); match the response schema"}
                                  for e in exc.errors(include_input=False)[:MAX_ERRORS]]
                    else:
                        errors = [{'path': 'answer.' + '.'.join(map(str, e['loc'])), 'message': e['msg']}
                                  for e in exc.errors(include_input=False)]
                else:
                    own = answer.html
                    category = 'measurement'
                    width = fixed or answer.canvas_width
                    html = own if first is None else f'<style>{first.css}</style>' + own
                    measured = await asyncio.to_thread(design_page.measure, html, slots, width,
                                                       footer=footer, fonts=fonts)
                    errors = measured.errors
            check.update(errors=len(errors))
            if reference is not None:
                span.update(duration_ms=round((time.monotonic() - started) * 1000), errors=len(errors),
                            validation_categories={category: len(errors)} if errors else {})
            if not errors:
                clean = design_page.sanitize(html, page=page.index, fonts=fonts)
                css = STYLE.match(clean)
                return Designed(clean, measured.boxes, measured.height, width,
                                readable(css.group(1)) if css else '')
            repair = {'errors': errors[:MAX_ERRORS]}
            if own is not None:
                # The model's own markup, with icon names rather than the inlined SVGs.
                repair['html'] = own
                if opening and reference is not None:
                    repair['canvas_width'] = width
        reason = 'invalid'
    except RunError as exc:
        reason = 'over_budget' if exc.detail.get('reason') == 'over_budget' else 'model'
        if reference is not None:
            span.update(reason=reason, **{k: v for k, v in exc.detail.items() if k in ('tokens', 'budget')})
    except TimeoutError:
        if reference is not None:
            raise
        reason = 'error'  # preserve the ordinary designer's fallback classification
    except Exception:
        # Provider and Chromium errors may echo request text: keep only the fact.
        reason = 'error'
    if reference is not None:
        span.update(reason=reason, errors=len(errors))
    return Fallback(reason, tuple(errors[:MAX_ERRORS]))


def assemble(spec, results, model_name):
    """A copy of the code-laid spec at page 1's width: each designed page gets its design, the
    `p<n>_design` decoration (plus the synthetic footer on page 1), measured boxes and height;
    a fallback page keeps its code layout and kit."""
    designed = spec.model_copy(deep=True)
    designed.canvas.width = results[0].width
    for page, result in zip(designed.pages, results):
        if not isinstance(result, Fallback):
            _place(designed, page, result, Design(html=result.html, source='designer', model=model_name))
    designed.canvas.height = designed.pages[0].height
    return designed


def _place(spec, page, result, design):
    """`page` of `spec` (in place) as the Designed `result`: design, height, boxes and the
    `p<n>_design` decoration, plus the synthetic footer on page 1."""
    page.design = design
    page.height = result.height
    for component in page.components:
        component.box = Box(**result.boxes[component.id])
    page.decorations = [design_decoration(page.index, result.height, spec.grid)]
    if page.index == 1 and spec.datasource.synthetic:
        grid = spec.grid
        top = result.height - FOOTER - grid.margin  # design_page.footer_top of the natural height
        page.decorations.append(synthetic_decoration((top - grid.margin) // grid.row_height + 1))


async def _generate(model, request, usage, limit=MAX_OUTPUT_TOKENS):
    """(raw text, cut off at `limit` output tokens) from one non-streamed call; thought parts are
    never part of the answer."""
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
    cut = (truncated or tokens(raw) > limit
           or bool(metadata and (metadata.candidates_token_count or 0) > limit))
    return raw, cut
