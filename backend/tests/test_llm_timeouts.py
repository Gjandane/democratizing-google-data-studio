"""Each node's Gemini client carries its own timeout: google-genai sends the client timeout to
Google as the server deadline, so a planner call must not inherit the worker's 30 s."""
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from dss.harness.llm import ModelRouter


class Settings:
    def get(self):
        return SimpleNamespace(planner_model='planner-model', worker_model='worker-model',
                               google_api_key=SecretStr('test-key'))


@pytest.mark.parametrize('node,model,timeout', [
    ('plan', 'planner-model', 120_000), ('spec', 'planner-model', 120_000),
    *[(node, 'worker-model', 30_000) for node in (
        'hello', 'interview', 'revise', 'capability_check', 'reference_extract', 'ux_audit',
        'research', 'consolidate', 'judge')]])
def test_client_timeout_per_node(node, model, timeout):
    llm = ModelRouter(Settings()).llm_for(node)
    assert llm.model == model
    assert llm.api_client._api_client._http_options.timeout == timeout


def test_planner_fallback_keeps_planner_deadline():
    router = ModelRouter(Settings())
    router.planner_model = router.worker_model
    llm = router.llm_for('spec')
    assert llm.model == 'worker-model'
    assert llm.api_client._api_client._http_options.timeout == 120_000
