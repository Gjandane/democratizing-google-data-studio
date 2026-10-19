"""A validation function node with a bounded repair routing decision."""
import json
from google.adk import Event
from google.adk.events.event_actions import EventActions
from dss.harness.guardrails import RunError
from dss.spec.validate import validate_spec


def make_validator(state, *, allowed, high_priority, expected, trace, save, verify=None):
    async def validate(node_input):
        trace.span('validate')
        raw = state['raw']
        try:
            value = json.loads(raw)
            errors = validate_spec(value, allowed=allowed, high_priority=high_priority)
            if isinstance(value, dict):
                for key, required in expected.items():
                    if value.get(key) != required:
                        errors.append({'path': key, 'message': 'Must match the supplied build identity and datasource'})
            if not errors and verify:
                errors.extend(verify(value))
        except (ValueError, TypeError):
            value = None
            errors = [{'path': '', 'message': 'Expected a JSON DashboardSpec object'}]
        state['errors'] = errors
        if errors:
            if state['repairs'] < 2:
                state['repairs'] += 1
                return Event(actions=EventActions(route='repair'))
            state['failure'] = RunError('invalid_request', 'Dashboard Spec validation failed: ' + json.dumps(errors), 422, {'errors': errors})
        else:
            await save(value)
        return Event(actions=EventActions(route='success'))
    return validate
