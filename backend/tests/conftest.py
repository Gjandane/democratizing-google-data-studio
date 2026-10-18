import pytest
from fastapi.testclient import TestClient

from dss.config import Config
from dss.db import now
from dss.main import create_app
from fakes import fake_models


@pytest.fixture
def app(tmp_path):
    return create_app(Config(data_dir=tmp_path, google_api_key="test-key"), model_lister=fake_models)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def build_id(client, app):
    build_id = "b_123456789abc"
    with app.state.db.connect() as connection:
        connection.execute("INSERT INTO builds(id,title,archetype,mode,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                           (build_id, "Example", "executive", "data", "connect", now(), now()))
    return build_id
