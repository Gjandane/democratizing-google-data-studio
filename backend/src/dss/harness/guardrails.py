"""Agent-run failures and final output guardrails."""


class RunError(Exception):
    def __init__(self, code, message, status_code=400, detail=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.status_code, self.detail = status_code, detail or {}


def check_reply(reply, secrets=()):
    if not isinstance(reply, str) or not reply.strip():
        raise RunError("llm_unavailable", "The model returned no reply", 503)
    if any(secret and secret in reply for secret in secrets):
        raise RunError("llm_unavailable", "The model returned an unsafe reply", 503)
    return reply
