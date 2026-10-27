"""Style profile: the validated visual treatment a reference extraction returns, written by code
as style.md for the existing style consumers (spec context). The vision call is reference_extract."""
import json
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Hex = Annotated[str, Field(pattern=r'^#[0-9A-Fa-f]{6}$')]


class StyleProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    palette: list[Hex] = Field(min_length=2, max_length=8)
    background: Hex
    surface: Hex
    text: Hex
    accent: Hex
    font_family: str = Field(min_length=1, max_length=60, pattern=r'^[A-Za-z0-9 -]+$')
    radius: int = Field(ge=0, le=32)
    notes: str = Field(default='', max_length=1000)

    @field_validator('palette', mode='after')
    @classmethod
    def upper_palette(cls, value):
        return [v.upper() for v in value]

    @field_validator('background', 'surface', 'text', 'accent', mode='after')
    @classmethod
    def upper(cls, value):
        return value.upper()


COLORS = ('background', 'surface', 'text', 'accent')
PRESET_FIELDS = ('palette', *COLORS, 'font_family', 'radius')
MAX_REPAIRS = 10
# A known-valid profile: one field at a time is checked against the unchanged StyleProfile rules.
_BASE = {'palette': ['#000000', '#FFFFFF'], 'background': '#FFFFFF', 'surface': '#FFFFFF', 'text': '#000000',
         'accent': '#000000', 'font_family': 'Arial', 'radius': 0, 'notes': ''}
_CHANNEL = r'\s*([0-9]{1,3})\s*'
_RGB = re.compile(rf'rgb\({_CHANNEL},{_CHANNEL},{_CHANNEL}\)|rgba\({_CHANNEL},{_CHANNEL},{_CHANNEL},\s*(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)%?\s*\)',
                  re.IGNORECASE)


def _valid(name, value, entry=False):
    """True when `value` passes StyleProfile's own rules for `name` (or one palette entry), as JSON."""
    candidate = {**_BASE, name: [value, '#000000'] if entry else value}
    try:
        StyleProfile.model_validate_json(json.dumps(candidate))
    except (ValidationError, TypeError, ValueError):
        return False
    return True


def _color(value):
    """The common color forms the Spec names; anything else stays as it is."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if re.fullmatch(r'#[0-9A-Fa-f]{3}', text):
        return '#' + ''.join(c * 2 for c in text[1:])
    if re.fullmatch(r'[0-9A-Fa-f]{6}', text):
        return '#' + text
    if re.fullmatch(r'#[0-9A-Fa-f]{8}', text):
        return text[:7]
    if match := _RGB.fullmatch(text):
        channels = [int(c) for c in match.groups() if c is not None]
        if all(c <= 255 for c in channels):
            return '#' + ''.join(f'{c:02X}' for c in channels)
    return text


def _font(value):
    """A CSS family list keeps its first family, without surrounding quotes."""
    if not isinstance(value, str):
        return value
    first = value.split(',', 1)[0].strip()
    if len(first) >= 2 and first[0] == first[-1] and first[0] in '"\'':
        first = first[1:-1].strip()
    return first


def preset_profile(archetype):
    """The StyleProfile values of the theme preset design prefill uses for this archetype."""
    from dss.artifacts.design import DEFAULTS, presets
    preset = next(p for p in presets() if p.id == DEFAULTS[archetype])
    return {**{k: getattr(preset, k) for k in PRESET_FIELDS}, 'palette': list(preset.palette), 'notes': ''}


def repair_style(reply, preset=None):
    """Code-owned style repair before local validation (#Recreate extraction style repair).

    Both modes normalize the color/font values that fail the rules as returned; with `preset`
    (recreate only) each style field still invalid, missing or mistyped falls back to the preset.
    Returns the repaired reply and its ordered (path, action) repairs; no value enters a repair.
    """
    if not isinstance(reply, dict):
        return reply, []
    style = reply.get('style')
    if not isinstance(style, dict):
        if preset is None:
            return reply, []
        return {**reply, 'style': dict(preset)}, [(['style'], 'preset')]
    style, repairs = dict(style), {}
    for name in COLORS + ('font_family',):
        if name in style and not _valid(name, style[name]):
            fixed = (_font if name == 'font_family' else _color)(style[name])
            if fixed != style[name]:
                style[name], repairs[('style', name)] = fixed, 'normalized'
    if isinstance(style.get('palette'), list):
        style['palette'] = list(style['palette'])
        for i, value in enumerate(style['palette']):
            if not _valid('palette', value, entry=True) and (fixed := _color(value)) != value:
                style['palette'][i], repairs[('style', 'palette', i)] = fixed, 'normalized'
    unknown = []
    if preset is not None:
        unknown = [(['style', '?'], 'preset') for key in style if key not in StyleProfile.model_fields]
        style = _fallback(style, preset, repairs)
    return {**reply, 'style': style}, unknown + [
        ([part if type(part) is not int or part <= 1000 else '?' for part in path], action)
        for path, action in repairs.items()]


def _fallback(style, preset, repairs):
    """Recreate: known fields only, each valid or the preset's; a palette keeps 2-8 valid entries."""
    result = {}
    for name in COLORS + ('font_family', 'radius'):
        if name in style and _valid(name, style[name]):
            result[name] = style[name]
        else:
            result[name], repairs[('style', name)] = preset[name], 'preset'
    palette = style.get('palette')
    kept = [i for i, v in enumerate(palette) if _valid('palette', v, entry=True)] if isinstance(palette, list) else []
    if len(kept) >= 2:
        result['palette'] = [palette[i] for i in kept[:8]]
        for i in sorted(set(range(len(palette))) - set(kept[:8])):
            repairs[('style', 'palette', i)] = 'preset'
    else:
        for path in [p for p in repairs if p[:2] == ('style', 'palette')]:
            del repairs[path]
        result['palette'], repairs[('style', 'palette')] = list(preset['palette']), 'preset'
    if 'notes' in style:
        if _valid('notes', style['notes']):
            result['notes'] = style['notes']
        else:
            result['notes'], repairs[('style', 'notes')] = '', 'preset'
    return result


def repair_projection(repairs):
    """Bounded, value-free span projection of the style repairs."""
    return {'repairs': [{'path': path, 'action': action} for path, action in repairs[:MAX_REPAIRS]],
            'count': len(repairs), 'truncated': len(repairs) > MAX_REPAIRS}


def provider_schema(model):
    """The model's JSON schema for response_json_schema, without nested array maxima.

    The worker rejects nested `maxItems`; Pydantic keeps every limit locally.
    """
    schema = model.model_json_schema()

    def provider_limits(value):
        if isinstance(value, dict):
            value.pop('maxItems', None)
            for child in value.values():
                provider_limits(child)
        elif isinstance(value, list):
            for child in value:
                provider_limits(child)
    provider_limits(schema)
    return schema


def style_doc(profile, sources, reference_set):
    """style.md frontmatter and body; `reference_set` marks it reference-owned (removed with the set)."""
    body = '# Style profile\n\nPalette: ' + ', '.join(profile.palette) + '\n\n' + '\n'.join(
        f'- {k}: {getattr(profile, k)}' for k in ('background', 'surface', 'text', 'accent', 'font_family', 'radius'))
    if profile.notes:
        body += '\n\nNotes (model text, untrusted):\n\n' + ' '.join(profile.notes.split())
    return ({'type': 'Style Profile', 'title': 'Style profile', **profile.model_dump(exclude={'notes'}),
             'sources': sources, 'reference_set': reference_set}, body + '\n')
