"""Environment defaults resolved from the package, with a SQLite settings overlay."""
import os
import json
import logging
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from dss.harness import stages as stage_settings
from dss.harness.guardrails import RunError

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    google_api_key: SecretStr = SecretStr("")
    planner_model: str = "gemini-4-argon"
    worker_model: str = "gemini-3.8-flash"
    stages: Any = Field(default_factory=lambda: stage_settings.defaults()['stages'])
    fallback_model: Any = stage_settings.FLASH
    review_briefs: Any = False
    notices: list[str] = Field(default_factory=list)
    gcp_project_id: str = ""
    bq_dataset: str = "dss_demo"
    bq_location: str = "US"
    gcs_bucket: str = ""
    data_dir: Path = BACKEND_DIR / "../data"
    db_path: Path | None = None
    static_dir: Path | None = None
    access_code: SecretStr = SecretStr("")
    agent_token: SecretStr = SecretStr("")
    # Google sign-in at the gate (api.md 3.3): the OAuth web client id (public) and who may enter.
    google_client_id: str = ""
    signin_allow: tuple[str, ...] = ()
    engine_mode: Literal["local", "agent"] = "local"
    cloud_service: str = ""
    # DSS_PUBLIC (conventions.md 1.6): "1" on Cloud Run opens the hosted link; ignored off Cloud Run.
    public_link: str = ""
    consolidate_every: int = Field(default=5, ge=1)
    # The planner designs each page around its components (architecture.md#Designed pages).
    # A Config attribute only: no env name, no API setting. Off: today's code layout and kits.
    designed_pages: bool = True

    @field_validator("google_client_id", mode="before")
    @classmethod
    def _strip_client_id(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("signin_allow", mode="before")
    @classmethod
    def _parse_signin_allow(cls, value):
        # Parsed once: trimmed, lower-cased, empty entries dropped; () or "*" admits any account.
        entries = value.split(",") if isinstance(value, str) else value
        return tuple(entry.strip().lower() for entry in entries if entry.strip())

    @classmethod
    def from_env(cls):
        env = {**dotenv_values(BACKEND_DIR.parent / ".env"), **os.environ}
        names = {"google_api_key": "GOOGLE_API_KEY", "planner_model": "DSS_PLANNER_MODEL",
                 "worker_model": "DSS_WORKER_MODEL", "gcp_project_id": "GCP_PROJECT_ID",
                 "bq_dataset": "BQ_DATASET", "bq_location": "BQ_LOCATION",
                 "gcs_bucket": "GCS_BUCKET", "data_dir": "DSS_DATA_DIR", "db_path": "DSS_DB_PATH",
                 "static_dir": "DSS_STATIC_DIR", "access_code": "DSS_ACCESS_CODE",
                 "agent_token": "DSS_AGENT_TOKEN", "engine_mode": "DSS_ENGINE_MODE",
                 "cloud_service": "K_SERVICE", "consolidate_every": "DSS_CONSOLIDATE_EVERY",
                 "google_client_id": "GOOGLE_OAUTH_CLIENT_ID", "signin_allow": "DSS_SIGNIN_ALLOW",
                 "public_link": "DSS_PUBLIC"}
        values = {field: env[name] for field, name in names.items() if env.get(name) is not None}
        for field in ("data_dir", "db_path", "static_dir"):
            if values.get(field):
                values[field] = (BACKEND_DIR / values[field]).resolve()
            elif field in values:
                del values[field]
        return cls(**values)

    def public(self):
        return {**self.model_dump(include={"stages", "fallback_model", "review_briefs", "notices", "gcp_project_id",
                                          "bq_dataset", "bq_location", "gcs_bucket"}),
                "google_api_key_set": bool(self.google_api_key.get_secret_value()),
                "issues": stage_settings.issues(self.model_dump(include={'stages', 'fallback_model', 'review_briefs'}))}

    @property
    def open_link(self):
        return bool(self.cloud_service) and self.public_link == "1"

    def validate_start(self):
        code = self.access_code.get_secret_value()
        if self.cloud_service and self.public_link:
            if self.public_link != "1":
                raise RuntimeError("DSS_PUBLIC must be 1 (open link) or empty (gated)")
            if code or self.google_client_id:
                raise RuntimeError("DSS_PUBLIC=1 requires DSS_ACCESS_CODE and GOOGLE_OAUTH_CLIENT_ID to be empty")
        if self.google_client_id and not code:
            raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID requires DSS_ACCESS_CODE (it keys the session cookie)")
        if self.cloud_service:
            if not self.open_link and len(code) < 12:
                raise RuntimeError("Cloud Run requires DSS_ACCESS_CODE of at least 12 characters")
            if self.engine_mode == "agent" and len(self.agent_token.get_secret_value()) < 24:
                raise RuntimeError("Cloud Run agent mode requires DSS_AGENT_TOKEN of at least 24 characters")


class SettingsStore:
    def __init__(self, defaults, db):
        self.defaults, self.db = defaults, db

    def get(self):
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            values = self._read(connection)
        return self._config(values)

    def _read(self, connection):
        values = dict(connection.execute('SELECT key,value FROM settings').fetchall())
        if 'stages' not in values:
            seed = stage_settings.defaults()
            notices = []
            for role, names in stage_settings.LEGACY_ROLES.items():
                explicit = values.get(role)
                if explicit is None and getattr(self.defaults, role) != stage_settings.LEGACY_DEFAULTS[role]:
                    explicit = getattr(self.defaults, role)
                if explicit is not None:
                    for name in names:
                        seed['stages'][name]['model'] = explicit
                        notices.append(f'Migrated {role} to stages.{name}.')
                        logging.getLogger(__name__).info('Seeded stage %s from legacy settings', name)
            seed['stage_migration_notices'] = notices
            encoded = {key: json.dumps(value) for key, value in seed.items()}
            connection.executemany('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', encoded.items())
            values = dict(connection.execute('SELECT key,value FROM settings').fetchall())
        return values

    def _config(self, values):
        values = {key: value for key, value in values.items() if key not in stage_settings.LEGACY_ROLES}
        if self.defaults.engine_mode == "agent":
            values = {key: value for key, value in values.items()
                      if key in ('stages', 'fallback_model', 'review_briefs', 'stage_migration_notices')}
        values = dict(values)
        for key in ('stages', 'fallback_model', 'review_briefs', 'stage_migration_notices'):
            if key in values:
                values[key] = json.loads(values[key])
        values['notices'] = values.pop('stage_migration_notices', [])
        return Config.model_validate({**self.defaults.model_dump(), **values})

    def update(self, values):
        with self.db.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            current = self._config(self._read(connection)).model_dump()
            merged = stage_settings.merge(current, values)
            problems = stage_settings.update_issues(current, merged, values)
            allowed = {'stages', 'fallback_model', 'review_briefs', 'google_api_key', 'gcp_project_id',
                       'bq_dataset', 'bq_location', 'gcs_bucket'}
            for key, value in values.items():
                if key not in allowed:
                    problems.append({'path': '/' + stage_settings.pointer(key), 'message': 'Unknown setting.'})
                elif key in allowed - {'stages', 'fallback_model', 'review_briefs'} and not isinstance(value, str):
                    problems.append({'path': '/' + key, 'message': 'Use a string.'})
            if problems:
                raise RunError('invalid_settings', 'Fix the highlighted settings and save again.', 422,
                               {'issues': problems})
            encoded = {key: json.dumps(merged[key]) if key in ('stages', 'fallback_model', 'review_briefs')
                       else merged[key] for key in values}
            connection.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                   encoded.items())
        return self.get()
