"""Each node's Gemini client carries its stage profile's request deadline."""
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from dss.harness.llm import ModelRouter
from dss.harness.stages import defaults


class Settings:
    def __init__(self):
        config = defaults()
        for stage, profile in config['stages'].items():
            profile['model'] = ('planner-model' if stage in
                ('native_planning', 'reference_interpretation', 'html_brief') else 'worker-model')
        config['fallback_model'] = 'worker-model'
        self.value = SimpleNamespace(**config, google_api_key=SecretStr('test-key'))

    def get(self):
        return self.value


@pytest.mark.parametrize('node,model,timeout', [
    # Change 2026-10-26: generation deadlines and models come from their stage profiles.
    *[(node, 'planner-model', 1_200_000 if node == 'blueprint' else 600_000)
       for node in ('blueprint', 'reference_extract', 'reference_brief')],
    *[(node, 'worker-model', 1_200_000) for node in ('designer', 'reference_html')],
    *[(node, 'worker-model', 30_000) for node in (
        'hello', 'context', 'outline_propose', 'outline_other', 'outline_suggest', 'revise', 'capability_check', 'ux_audit',
        'synthetic_schema', 'style_extract', 'research', 'consolidate', 'judge')]])
def test_client_timeout_per_node(node, model, timeout):
    llm = ModelRouter(Settings()).llm_for(node)
    assert llm.model == model
    assert llm.api_client._api_client._http_options.timeout == timeout


@pytest.mark.parametrize('node,stage', [('hello', 'routine'), ('context', 'interview')])
async def test_listed_absent_model_uses_fallback_with_its_stage_deadline(node, stage):
    # Change 2026-10-26: listing fallback generalizes the old planner/worker swap.
    settings = Settings()
    settings.value.stages[stage]['model'] = 'missing-model'

    async def listed_models(key):
        return ['models/worker-model']

    router = ModelRouter(settings, model_lister=listed_models)
    await router.refresh()
    llm = router.llm_for(node)
    assert llm.model == 'worker-model'
    assert llm.api_client._api_client._http_options.timeout == 30_000
