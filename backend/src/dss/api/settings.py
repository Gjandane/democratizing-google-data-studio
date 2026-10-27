from fastapi import APIRouter, Request
from dss.harness.guardrails import RunError
from dss.harness.stages import capabilities

router = APIRouter(prefix="/api/settings")


@router.get("")
def get_settings(request: Request):
    return request.app.state.settings.get().public()


@router.get('/capabilities')
def get_capabilities(request: Request):
    return capabilities(request.app.state.models.available)


@router.put("")
async def put_settings(request: Request):
    try:
        values = await request.json()
    except ValueError:
        values = None
    if not isinstance(values, dict):
        raise RunError('invalid_settings', 'Fix the highlighted settings and save again.', 422,
                       {'issues': [{'path': '', 'message': 'Use a settings object.'}]})
    if request.app.state.config.engine_mode == "agent" and values.keys() & {
            'google_api_key', 'gcp_project_id', 'bq_dataset', 'bq_location', 'gcs_bucket'}:
        raise RunError("settings_locked", "Only models can be changed in agent mode", 403)
    request.app.state.settings.update(values)
    await request.app.state.models.refresh()
    return request.app.state.settings.get().public()
