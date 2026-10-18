"""Environment defaults resolved from the package, with a SQLite settings overlay."""
import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, SecretStr

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    google_api_key: SecretStr = SecretStr("")
    planner_model: str = "gemini-4-argon"
    worker_model: str = "gemini-3.8-flash"
    gcp_project_id: str = ""
    bq_dataset: str = "dss_demo"
    bq_location: str = "US"
    gcs_bucket: str = ""
    data_dir: Path = BACKEND_DIR / "../data"
    db_path: Path | None = None

    @classmethod
    def from_env(cls):
        env = {**dotenv_values(BACKEND_DIR.parent / ".env"), **os.environ}
        names = {"google_api_key": "GOOGLE_API_KEY", "planner_model": "DSS_PLANNER_MODEL",
                 "worker_model": "DSS_WORKER_MODEL", "gcp_project_id": "GCP_PROJECT_ID",
                 "bq_dataset": "BQ_DATASET", "bq_location": "BQ_LOCATION",
                 "gcs_bucket": "GCS_BUCKET", "data_dir": "DSS_DATA_DIR", "db_path": "DSS_DB_PATH"}
        values = {field: env[name] for field, name in names.items() if env.get(name) is not None}
        for field in ("data_dir", "db_path"):
            if values.get(field):
                values[field] = (BACKEND_DIR / values[field]).resolve()
            elif field in values:
                del values[field]
        return cls(**values)

    def public(self):
        return {**self.model_dump(exclude={"google_api_key", "data_dir", "db_path"}),
                "google_api_key_set": bool(self.google_api_key.get_secret_value())}


class SettingsStore:
    def __init__(self, defaults, db):
        self.defaults, self.db = defaults, db

    def get(self):
        with self.db.connect() as connection:
            values = dict(connection.execute("SELECT key,value FROM settings").fetchall())
        return Config.model_validate({**self.defaults.model_dump(), **values})

    def update(self, values):
        with self.db.connect() as connection:
            connection.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                   values.items())
        return self.get()
