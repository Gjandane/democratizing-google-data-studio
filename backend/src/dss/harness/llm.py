"""Model availability and planner/worker routing without logging credentials."""
import asyncio
import logging

from google import genai
from google.adk.models.google_llm import Gemini
from google.genai import types

logger = logging.getLogger(__name__)


async def list_models(key):
    def fetch():
        with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=10000)) as client:
            return [model.name.removeprefix("models/") for model in client.models.list()]
    return await asyncio.to_thread(fetch)


class ModelRouter:
    def __init__(self, settings, model_lister=None):
        self.settings = settings
        self.model_lister = model_lister or list_models
        self.planner_model = settings.get().planner_model
        self.worker_model = settings.get().worker_model

    async def refresh(self):
        config = self.settings.get()
        self.planner_model, self.worker_model = config.planner_model, config.worker_model
        key = config.google_api_key.get_secret_value()
        if not key:
            return
        try:
            available = {name.removeprefix("models/") for name in await self.model_lister(key)}
        except Exception:
            logger.warning("Could not list models; check API credentials and connectivity")
            return
        if self.planner_model not in available:
            logger.warning("Planner model unavailable; using worker model for plan and spec")
            self.planner_model = self.worker_model

    def model_for(self, node):
        return self.planner_model if node in {"plan", "spec"} else self.worker_model

    def llm_for(self, node):
        key = self.settings.get().google_api_key.get_secret_value()
        if not key:
            from dss.harness.guardrails import RunError
            raise RunError("llm_unavailable", "Set the Google API key in Settings", 503)
        return Gemini(model=self.model_for(node), client=genai.Client(
            api_key=key, http_options=types.HttpOptions(timeout=30000)))
