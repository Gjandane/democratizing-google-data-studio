"""One persisted trace, including failed runs, without prompts or secret values."""
import json
import asyncio
from contextlib import contextmanager
from time import perf_counter

from dss.db import now


def response_diagnostic(category):
    """Code-owned categories only; never accept a provider code or exception message."""
    boundary = {'provider_response_error': 'provider_response', 'no_final_text': 'final_text',
                'unsafe_reply': 'reply_guard', 'malformed_json': 'json_decode',
                'too_many_elements': 'element_count', 'accepted': 'local_validation'}.get(category)
    return {'boundary': boundary or 'provider_response', 'category': category if boundary else 'unclassified'}


def schema_path(path, schema):
    """Walk the code's schema, replacing arbitrary keys/union labels and bounding indices/depth."""
    def branches(part, depth=0):
        if not isinstance(part, dict) or depth > 8:
            return []
        ref = part.get('$ref', '')
        if ref.startswith('#/$defs/'):
            return branches(schema.get('$defs', {}).get(ref[8:], {}), depth + 1)
        return [part, *(child for key in ('anyOf', 'oneOf', 'allOf') for option in part.get(key, [])
                        for child in branches(option, depth + 1))]
    candidates, result = branches(schema), []
    for component in path:
        if len(result) == 12:
            result.append('?')
            break
        if type(component) is int:
            children = [part['items'] for part in candidates if isinstance(part.get('items'), dict)]
            result.append(component if children and 0 <= component <= 1000 else '?')
        else:
            children = [part['properties'][component] for part in candidates
                        if isinstance(component, str) and component in part.get('properties', {})]
            result.append(component if children else '?')
        candidates = [branch for child in children for branch in branches(child)]
    return result


def validation_diagnostic(errors, schema, *, local=False):
    """Project validator errors before they can reach a trace, assertion or console.

    No messages, values, context, schema values, union labels or URLs survive. The schema
    is the code-owned response schema, never the model's response. Projection is best effort
    and cannot replace an extraction failure.
    """
    result = {'boundary': 'local_validation' if local else 'provider_schema',
              'category': 'local_pydantic_rejection' if local else 'provider_schema_rejection',
              'issues': [], 'issue_count': 0, 'issues_truncated': False}
    categories = ({'extra_forbidden': 'extra', 'missing': 'missing', 'literal_error': 'enum',
                   'int_type': 'type', 'int_parsing': 'type', 'int_from_float': 'type',
                   'string_type': 'type', 'list_type': 'type', 'dict_type': 'type', 'model_type': 'type',
                   'greater_than': 'range', 'greater_than_equal': 'range',
                   'less_than': 'range', 'less_than_equal': 'range',
                   'too_long': 'length', 'too_short': 'length', 'string_too_long': 'length',
                   'string_too_short': 'length', 'string_pattern_mismatch': 'pattern', 'value_error': 'invariant'}
                  if local else {'additionalProperties': 'extra', 'required': 'missing', 'type': 'type',
                                 'enum': 'enum', 'const': 'enum', 'minimum': 'range', 'maximum': 'range',
                                 'exclusiveMinimum': 'range', 'exclusiveMaximum': 'range',
                                 'minLength': 'length', 'maxLength': 'length', 'minItems': 'length',
                                 'maxItems': 'length', 'pattern': 'pattern', 'anyOf': 'union', 'oneOf': 'union'})
    try:
        for error in errors:
            result['issue_count'] += 1
            if len(result['issues']) < 10:
                code, path = (error.get('type'), error.get('loc', ())) if local else (error.validator, error.absolute_path)
                result['issues'].append({'category': categories.get(code, 'other'), 'path': schema_path(path, schema)})
        result['issues_truncated'] = result['issue_count'] > len(result['issues'])
    except Exception:
        # A broken diagnostic must neither expose the exception nor mask the original error.
        return {'boundary': result['boundary'], 'category': 'unclassified'}
    return result


def record_reference_diagnostic(trace, diagnostic):
    """Attach only an already projected diagnostic to the existing extraction span."""
    for span in reversed(trace.spans):
        if span['node'] == 'reference_extract':
            span['diagnostic'] = diagnostic
            break


def cost(model, input_tokens, output_tokens, thinking_tokens):
    from dss.harness.stages import MODELS
    price = MODELS.get(model, {}).get('price')
    if price is None or any(v is None for v in (input_tokens, output_tokens, thinking_tokens)):
        return None
    long = price['long_context_over'] is not None and input_tokens > price['long_context_over']
    input_rate = price['long_input_usd_per_mtok'] if long else price['input_usd_per_mtok']
    output_rate = price['long_output_usd_per_mtok'] if long else price['output_usd_per_mtok']
    if input_rate is None or output_rate is None:
        return None
    return (input_tokens * input_rate + (output_tokens + thinking_tokens) * output_rate) / 1_000_000


def cost_total(values):
    values = list(values)
    known = [v for v in values if v is not None]
    return (sum(known) if known or not values else None), len(known) == len(values)


class StageCall:
    """Only code-owned fields and numeric usage survive this request boundary."""
    def __init__(self, session, request, model, transport_attempt):
        from dss.harness import stages
        from dss.harness.context import request_estimate
        run = stages.execution.get()
        self.session, self.start, self.responded = session, session.clock.now(), False
        self.value = dict(run_id=getattr(run.trace, 'run_id', '') if run else '', stage=session.stage,
            node=session.node, page=session.page, attempt=session.attempt, transport_attempt=transport_attempt,
            requested_model=session.profile['model'], model=model, fallback=model != session.profile['model'],
            thinking=session.profile['thinking'], input_measured=None, input_billed=None,
            input_enforced=request_estimate(request), input_limit=session.profile.get('input_tokens'),
            output_limit=request.config.max_output_tokens, output_tokens=None, thinking_tokens=None,
            outcome='ok', duration_ms=0, started_at=now(), cost_usd_estimate=None)
        self.value.update(session.request_counts)
        session.last_call = self
        if run:
            run.calls.append(self.value)

    def observe(self, response, request):
        self.responded = True
        reference = self.session.node == 'reference_extract'
        diagnostic = response_diagnostic('unclassified')
        if usage := response.usage_metadata:
            self.value.update(input_billed=usage.prompt_token_count, output_tokens=usage.candidates_token_count,
                              thinking_tokens=usage.thoughts_token_count)
        if response.finish_reason == 'MAX_TOKENS' or response.error_code == 'MAX_TOKENS':
            self.value['outcome'] = 'output_cutoff'
        elif response.error_code:
            self.value['outcome'] = 'invalid'
            diagnostic = response_diagnostic('provider_response_error')
        elif not response.partial:
            text = ''.join(p.text for p in (response.content.parts or []) if p.text and not p.thought) if response.content else ''
            tool_call = response.content and any(p.function_call for p in response.content.parts or [])
            if not text.strip() and not tool_call:
                self.value['outcome'] = 'invalid'
                diagnostic = response_diagnostic('no_final_text')
            elif text.strip() and request.config.response_json_schema:
                from jsonschema import Draft202012Validator
                try:
                    parsed = json.loads(text)
                    validator = Draft202012Validator(request.config.response_json_schema)
                    if reference:
                        # Reuse the existing provider-schema validation, retaining only its projection.
                        diagnostic = validation_diagnostic(validator.iter_errors(parsed), request.config.response_json_schema)
                        valid = diagnostic.get('issue_count') == 0 if diagnostic['category'] != 'unclassified' else validator.is_valid(parsed)
                        if valid:
                            diagnostic = {'boundary': 'provider_schema', 'category': 'unclassified'}
                    else:
                        valid = validator.is_valid(parsed)
                except (ValueError, TypeError):
                    valid = False
                    diagnostic = response_diagnostic('malformed_json')
                if not valid:
                    self.value['outcome'] = 'invalid'
        if reference:
            from dss.harness import stages
            if (run := stages.execution.get()) is not None:
                record_reference_diagnostic(run.trace, diagnostic)

    def finish(self, error=None):
        from dss.harness.guardrails import RunError
        from dss.harness.stages import GENERATIONS
        expired = self.session.stage in GENERATIONS and self.session.clock.now() >= self.session.clock.end
        if error is not None and expired:
            self.value['outcome'] = 'timeout'
        elif isinstance(error, RunError):
            self.value['outcome'] = {'stage_output_cutoff': 'output_cutoff', 'stage_timeout': 'timeout',
                                     'stage_input_over_limit': 'input_over_limit'}.get(error.code, 'invalid')
        elif isinstance(error, (asyncio.CancelledError, GeneratorExit)):
            self.value['outcome'] = 'cancelled'
        elif isinstance(error, TimeoutError):
            self.value['outcome'] = 'timeout'
        elif error is not None:
            self.value['outcome'] = 'provider_error'
        elif not self.responded:
            self.value['outcome'] = 'invalid'
        self.value['duration_ms'] = max(0, round((self.session.clock.now() - self.start) * 1000))
        inputs = next((self.value[k] for k in ('input_billed', 'input_measured', 'input_enforced')
                       if self.value[k] is not None), None)
        self.value['cost_usd_estimate'] = (0 if self.value['outcome'] == 'provider_error' and not self.responded
            else cost(self.value['model'], inputs, self.value['output_tokens'], self.value['thinking_tokens']))


@contextmanager
def provider_call(session, request, model, transport_attempt=1):
    call = StageCall(session, request, model, transport_attempt)
    try:
        yield call
    except BaseException as exc:
        call.finish(exc)
        raise
    else:
        call.finish()


class Trace:
    def __init__(self, db, run_id, build_id, action):
        self.db, self.run_id, self.build_id, self.action = db, run_id, build_id, action
        self.started_at, self.start = now(), perf_counter()
        self.spans = []
        self.model = None
        self.input_tokens = self.output_tokens = 0

    def span(self, node):
        self.spans.append({"node": node})

    def save(self, status, error):
        with self.db.connect() as connection:
            connection.execute("INSERT INTO traces VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                self.run_id, self.build_id, self.action, self.model, self.input_tokens,
                self.output_tokens, int((perf_counter()-self.start)*1000), getattr(self, "tool_calls", 0), status,
                error, json.dumps(self.spans), self.started_at))
