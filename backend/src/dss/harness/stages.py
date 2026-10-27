"""Code-owned Settings 3.0 profiles and action/page execution boundaries.

Verified 2026-10-26 against ai.google.dev/gemini-api/docs/models/{model id}
and /pricing. Argon documents a unified 1,048,576-token context window.
Prices are Standard paid-tier rates on the check date (thinking is output).
"""
from copy import deepcopy
import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import time

from dss.harness.guardrails import RunError

FLASH, ARGON = 'gemini-3.8-flash', 'gemini-4-argon'
GENERATIONS = ('reference_interpretation', 'native_planning', 'html_brief',
               'reference_html', 'html_no_reference')
IMAGE_STAGES = frozenset({'reference_interpretation', 'html_brief', 'reference_html'})
LEGACY_ROLES = {'planner_model': ('native_planning', 'html_brief', 'html_no_reference'),
                'worker_model': ('interview', 'routine', 'reference_interpretation', 'reference_html')}
LEGACY_DEFAULTS = {'planner_model': ARGON, 'worker_model': FLASH}
LIMITS = {
    'model_timeout_s': [10, 600], 'generation_timeout_s': [30, 3600],
    'transport_retries': [0, 5],
    'validation_repairs': {stage: [0, 0 if stage == 'reference_interpretation' else
                                    1 if stage == 'native_planning' else 5] for stage in GENERATIONS},
    'input_margin_pct': [0, 100], 'min_input_tokens': 1024, 'min_output_tokens': 256,
}
MODELS = {
    model: {'id': model, 'thinking_levels': ['low', 'medium', 'high'],
            'max_input_tokens': 1048576, 'max_output_tokens': 65536, 'images': True,
            'price': {'input_usd_per_mtok': rates[0], 'output_usd_per_mtok': rates[1],
                      'long_context_over': None, 'long_input_usd_per_mtok': None,
                      'long_output_usd_per_mtok': None, 'checked_on': '2026-10-26'}}
    for model, rates in ((FLASH, (0.75, 3.75)), (ARGON, (2.0, 10.0)))
}


def defaults():
    stages = {name: {'model': FLASH, 'thinking': 'low', 'timeout_s': 30}
              for name in ('interview', 'routine')}
    for stage in GENERATIONS:
        html = stage in ('reference_html', 'html_no_reference')
        stages[stage] = {'model': FLASH if html else ARGON, 'thinking': 'high',
                         'input_tokens': 131072, 'output_tokens': 65536 if html else 32768,
                         'timeout_s': 1200 if html else 600,
                         'transport_retries': 1 if stage in GENERATIONS[:2] else 2,
                         'validation_repairs': 0 if stage == 'reference_interpretation' else 2 if html else 1,
                         'input_margin_pct': 20}
    stages['html_no_reference']['layout_fallback'] = True
    return {'stages': stages, 'fallback_model': FLASH, 'review_briefs': False}


def capabilities(available=None):
    return {'models': [{**deepcopy(value), 'available': None if available is None else model in available}
                       for model, value in MODELS.items()], 'defaults': defaults(), 'limits': deepcopy(LIMITS)}


def pointer(key):
    return str(key).replace('~', '~0').replace('/', '~1')


def issues(value):
    """Return stable, value-free messages, also for malformed stored profiles."""
    result = []
    def add(path, message):
        result.append({'path': path, 'message': message})
    fallback = value.get('fallback_model')
    fallback_cap = MODELS.get(fallback) if isinstance(fallback, str) else None
    if fallback_cap is None:
        add('/fallback_model', 'Choose a known fallback model.')
    if type(value.get('review_briefs')) is not bool:
        add('/review_briefs', 'Use a boolean.')
    profiles = value.get('stages')
    if not isinstance(profiles, dict):
        add('/stages', 'Use a stage profile object.')
        return result
    expected = defaults()['stages']
    for stage in profiles.keys() - expected.keys():
        add('/stages/' + pointer(stage), 'Unknown stage.')
    for stage, fields in expected.items():
        path = '/stages/' + stage
        profile = profiles.get(stage)
        if not isinstance(profile, dict):
            add(path, 'Supply a stage profile object.')
            continue
        for field in profile.keys() - fields.keys():
            add(path + '/' + pointer(field), 'Unknown profile field.')
        for field in fields.keys() - profile.keys():
            add(path + '/' + field, 'Required profile field.')
        model = profile.get('model')
        cap = MODELS.get(model) if isinstance(model, str) else None
        if cap is None:
            add(path + '/model', 'Choose a known model.')
        elif stage in IMAGE_STAGES and not cap['images']:
            add(path + '/model', 'This stage requires image support.')
        if cap and profile.get('thinking') not in cap['thinking_levels']:
            add(path + '/thinking', 'Choose a thinking level supported by the model.')
        elif not cap and profile.get('thinking') not in ('low', 'medium', 'high'):
            add(path + '/thinking', 'Choose low, medium or high.')
        bounds = {'timeout_s': LIMITS['generation_timeout_s' if stage in GENERATIONS else 'model_timeout_s']}
        if stage in GENERATIONS:
            bounds.update(transport_retries=LIMITS['transport_retries'],
                          validation_repairs=LIMITS['validation_repairs'][stage],
                          input_margin_pct=LIMITS['input_margin_pct'])
            for field, minimum, maximum in (('input_tokens', 1024, 'max_input_tokens'),
                                             ('output_tokens', 256, 'max_output_tokens')):
                bounds[field] = [minimum, cap[maximum] if cap else None]
        for field, (lo, hi) in bounds.items():
            number = profile.get(field)
            if type(number) is not int or number < lo or (hi is not None and number > hi):
                add(path + '/' + field, f'Use an integer from {lo} to {hi}.' if hi is not None else f'Use an integer at least {lo}.')
        if stage == 'html_no_reference' and type(profile.get('layout_fallback')) is not bool:
            add(path + '/layout_fallback', 'Use a boolean.')
        if stage in GENERATIONS and fallback_cap and model != fallback:
            if stage in IMAGE_STAGES and not fallback_cap['images']:
                add('/fallback_model', f'Fallback needs image support for {stage}.')
            if profile.get('thinking') not in fallback_cap['thinking_levels']:
                add(path + '/thinking', 'Fallback does not support this thinking level.')
            for field in ('input_tokens', 'output_tokens'):
                number = profile.get(field)
                if type(number) is int and number > fallback_cap['max_' + field]:
                    add(path + '/' + field, 'Fallback does not support this token limit.')
    return result


def merge(current, update):
    """Merge profiles per field, keeping malformed updates for path validation."""
    merged = deepcopy(current)
    for key, value in update.items():
        if key == 'stages' and isinstance(value, dict) and isinstance(merged.get(key), dict):
            for stage, profile in value.items():
                previous = merged[key].get(stage)
                merged[key][stage] = {**previous, **profile} if isinstance(previous, dict) and isinstance(profile, dict) else deepcopy(profile)
        else:
            merged[key] = deepcopy(value)
    return merged


def update_issues(current, merged, update):
    """Grandfather only unchanged invalid fields, including their dependencies."""
    before = issues(current)
    touched = set()
    for key, value in update.items():
        if key == 'stages' and isinstance(value, dict):
            for stage, profile in value.items():
                base = '/stages/' + pointer(stage)
                if stage not in defaults()['stages']:
                    touched.add(base)
                if isinstance(profile, dict):
                    touched.update(base + '/' + pointer(field) for field in profile)
                else:
                    touched.add(base)
        else:
            touched.add('/' + pointer(key))
    def affected(issue):
        path = issue['path']
        if any(path == p or path.startswith(p + '/') or p.startswith(path + '/') for p in touched):
            return True
        stage_model = path.rsplit('/', 1)[0] + '/model'
        model_dependent = path.rsplit('/', 1)[-1] in ('model', 'thinking', 'input_tokens', 'output_tokens')
        return (model_dependent and stage_model in touched) or (
            '/fallback_model' in touched and issue['message'].startswith('Fallback'))
    return [issue for issue in issues(merged) if issue not in before or affected(issue)]


# The default is deliberate: every other model node is routine, including internal/legacy nodes.
NODE_STAGES = {**dict.fromkeys(('context', 'outline_propose', 'outline_suggest', 'outline_other'), 'interview'),
               'reference_extract': 'reference_interpretation', 'blueprint': 'native_planning',
               'reference_brief': 'html_brief', 'reference_html': 'reference_html',
               'designer': 'html_no_reference'}
execution = ContextVar('dss_stage_execution', default=None)
active_session = ContextVar('dss_stage_session', default=None)


def stage_for(node):
    return NODE_STAGES.get(node, 'routine')


def snapshot(config):
    return merge(defaults(), {k: deepcopy(getattr(config, k)) for k in
                             ('stages', 'fallback_model', 'review_briefs') if hasattr(config, k)})


def profile(node):
    current = execution.get()
    return deepcopy((current.settings if current else defaults())['stages'][stage_for(node)])


def stop(node, code, message, **detail):
    stage = stage_for(node)
    error = RunError(code, f'{stage}: {message}', 503, {'stage': stage, **detail})
    remember_failure(error)  # ADK can wrap errors from before_model callbacks in a workflow error.
    return error


class StageClock:
    """One absolute deadline. Injectable time/sleep make clock tests deterministic."""
    def __init__(self, node, seconds, *, now=None, sleep=None):
        self.node, self.now, self.sleep = node, now or time.monotonic, sleep or asyncio.sleep
        self.end = self.now() + seconds

    def remaining(self, *, attempt=False):
        left = self.end - self.now()
        if left <= 0 or (attempt and left < 1):
            raise stop(self.node, 'stage_timeout', 'The stage deadline expired', reason='timeout')
        return left

    @asynccontextmanager
    async def scope(self):
        try:
            async with asyncio.timeout(self.remaining()) as deadline:
                yield self
                self.remaining()
        except TimeoutError:
            if not deadline.expired() and self.now() < self.end:
                raise  # a provider/measurement timeout is not the stage deadline
            raise stop(self.node, 'stage_timeout', 'The stage deadline expired', reason='timeout') from None
        except Exception:
            self.remaining()  # expiry also wins when the operation failed at the deadline
            raise

    async def wait(self, seconds):
        async with self.scope():
            await self.sleep(seconds)
        self.remaining(attempt=True)


class StageSession:
    def __init__(self, node, *, page=None, timeout=None):
        self.node, self.stage, self.page = node, stage_for(node), page
        self.profile = profile(node)
        self.clock = StageClock(node, self.profile['timeout_s'] if timeout is None else timeout)
        self.actual_model = None
        self.attempt = 0
        self.request_counts = {}
        self.last_call = None

    def fitted(self, measured, enforced, limit):
        self.request_counts = {'input_measured': measured, 'input_enforced': enforced, 'input_limit': limit}

    def select(self, selected):
        """Sticky per action/page: a repair cannot swap back after model fallback."""
        run = execution.get()
        settings = run.settings if run else defaults()
        requested, fallback = self.profile['model'], settings['fallback_model']
        available = run.available if run else None
        if self.actual_model is None:
            self.actual_model = selected
        if available is not None and self.actual_model not in available:
            if requested in MODELS and fallback in available and self.actual_model != fallback:
                self.actual_model = fallback
            else:
                raise self.unavailable()
        return self.actual_model

    def fallback(self):
        run = execution.get()
        fallback = (run.settings if run else defaults())['fallback_model']
        available = run.available if run else None
        if self.actual_model != fallback and (available is None or fallback in available):
            self.actual_model = fallback
            return True
        return False

    def unavailable(self):
        run = execution.get()
        fallback = (run.settings if run else defaults())['fallback_model']
        return stop(self.node, 'stage_model_unavailable',
                    f"Requested model {self.profile['model']} and fallback {fallback} are unavailable")

    def configure(self, request):
        from google.genai import types
        request.config.thinking_config = types.ThinkingConfig(thinking_level=self.profile['thinking'].upper())
        if self.stage in GENERATIONS:
            request.config.max_output_tokens = self.profile['output_tokens']

    @asynccontextmanager
    async def scope(self):
        with self.activate():
            async with self.clock.scope():
                yield self

    @contextmanager
    def activate(self):
        token = active_session.set(self)
        try:
            yield self
        finally:
            active_session.reset(token)


class Execution:
    """Private full config in memory; only the public effective stage settings enter the trace."""
    def __init__(self, config, trace, *, available=None):
        self.config = config.model_copy(deep=True) if hasattr(config, 'model_copy') else deepcopy(config)
        self.settings, self.sessions, self.failure = snapshot(self.config), {}, None
        self.available = None if available is None else frozenset(available)
        self.trace = trace
        self.calls = []

    def record(self):
        # Keep the graph's node order intact; attach public metadata to its first span.
        # A failure before any node still gets a snapshot-only trace.
        if not self.trace.spans:
            self.trace.spans.append({'node': 'stage_settings'})
        self.trace.spans[0]['settings'] = deepcopy(self.settings)
        if self.calls:
            self.trace.spans[0]['calls'] = self.calls

    @contextmanager
    def activate(self):
        token = execution.set(self)
        try:
            yield self
        finally:
            self.record()
            execution.reset(token)

    def session(self, node):
        stage = stage_for(node)
        key = stage if stage in GENERATIONS else node
        if key not in self.sessions:
            self.sessions[key] = StageSession(node)
        return self.sessions[key]


def session_for(node):
    current = active_session.get()
    if current is not None and current.stage == stage_for(node) and (
            current.node == node or current.stage in GENERATIONS):
        return current
    run = execution.get()
    return run.session(node) if run else StageSession(node)


def configure(node, request):
    session = session_for(node)
    session.configure(request)
    return session


def invalid_output(node):
    """Code validation can reject structurally valid JSON after the provider returns."""
    call = session_for(node).last_call
    if call is not None and call.value['outcome'] == 'ok':
        call.value['outcome'] = 'invalid'


def remember_failure(error):
    if isinstance(error, RunError) and error.code.startswith('stage_'):
        if (run := execution.get()) is not None:
            run.failure = error if error.code == 'stage_timeout' else run.failure or error
        return error


def check_output(node, response, request):
    if stage_for(node) not in GENERATIONS:
        return
    from google.genai import types
    from dss.harness.context import tokens
    truncated = response.finish_reason == types.FinishReason.MAX_TOKENS or response.error_code == 'MAX_TOKENS'
    if response.partial and not truncated:
        return
    raw = ''.join(p.text for p in (response.content.parts or []) if p.text and not p.thought) if response.content else ''
    usage = response.usage_metadata
    limit = request.config.max_output_tokens
    if truncated or tokens(raw) > limit or (usage and (usage.candidates_token_count or 0) > limit):
        error = stop(node, 'stage_output_cutoff', 'The answer reached the output limit', reason='output_cutoff')
        error.usage = usage  # private provider usage; preserve totals even when no response is yielded
        raise error
