"""One persisted trace, including failed runs, without prompts or secret values."""
import json
import asyncio
from contextlib import contextmanager
from time import perf_counter

from dss.db import now


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
        if usage := response.usage_metadata:
            self.value.update(input_billed=usage.prompt_token_count, output_tokens=usage.candidates_token_count,
                              thinking_tokens=usage.thoughts_token_count)
        if response.finish_reason == 'MAX_TOKENS' or response.error_code == 'MAX_TOKENS':
            self.value['outcome'] = 'output_cutoff'
        elif response.error_code:
            self.value['outcome'] = 'invalid'
        elif not response.partial:
            text = ''.join(p.text for p in (response.content.parts or []) if p.text and not p.thought) if response.content else ''
            tool_call = response.content and any(p.function_call for p in response.content.parts or [])
            if not text.strip() and not tool_call:
                self.value['outcome'] = 'invalid'
            elif text.strip() and request.config.response_json_schema:
                from jsonschema import Draft202012Validator
                try:
                    valid = Draft202012Validator(request.config.response_json_schema).is_valid(json.loads(text))
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    self.value['outcome'] = 'invalid'

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
