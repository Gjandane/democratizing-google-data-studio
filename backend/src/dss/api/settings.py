from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

router = APIRouter(prefix="/api/settings")


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planner_model: str = Field(default="gemini-4-argon", min_length=1, max_length=200)
    worker_model: str = Field(default="gemini-3.8-flash", min_length=1, max_length=200)
    gcp_project_id: str = ""
    bq_dataset: str = "dss_demo"
    bq_location: str = "US"
    gcs_bucket: str = ""
    google_api_key: SecretStr = SecretStr("")


@router.get("")
def get_settings(request: Request):
    return request.app.state.settings.get().public()


@router.put("")
async def put_settings(body: SettingsUpdate, request: Request):
    values = body.model_dump(exclude_unset=True)
    if "google_api_key" in values:
        values["google_api_key"] = body.google_api_key.get_secret_value()
    request.app.state.settings.update(values)
    await request.app.state.models.refresh()
    return request.app.state.settings.get().public()
