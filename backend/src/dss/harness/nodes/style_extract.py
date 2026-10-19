"""Style profile: the validated visual treatment a reference extraction returns, written by code
as style.md for the existing style consumers (spec context). The vision call is reference_extract."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
