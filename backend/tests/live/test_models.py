import pytest

from dss.config import Config
from dss.harness.llm import list_models


@pytest.mark.live
async def test_models(capsys):
    config = Config.from_env()
    key = config.google_api_key.get_secret_value()
    assert key, "GOOGLE_API_KEY must be configured for this live check"
    available = set(await list_models(key))
    # Make availability visible even under pytest's default output capture.
    with capsys.disabled():
        for name in ("gemini-4-argon", "gemini-3.8-flash"):
            print(f"{name}: {'available' if name in available else 'unavailable'}")
