"""The staged artifacts, field for field with contracts/api.md 2.0.

These validate structure. Checks against connected data, the catalog, presets and
other artifacts belong to the stage nodes and produce ValidationIssues.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Agg = Literal['sum', 'avg', 'count', 'count_distinct', 'min', 'max']
DataType = Literal['string', 'number', 'date', 'datetime', 'boolean', 'geo']
Color = Annotated[str, Field(pattern=r'^#[0-9a-fA-F]{6}$')]
SnakeName = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]*$')]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ValidationIssue(Model):
    path: str
    message: str


class DerivedField(Model):
    name: SnakeName
    expression: str
    type: DataType
    description: str


class Measure(Model):
    field: str
    agg: Agg


class Ratio(Model):
    numerator: str
    denominator: str


class Kpi(Model):
    id: SnakeName
    name: str
    description: str
    unit: str | None
    measure: Measure | None
    ratio: Ratio | None

    @model_validator(mode='after')
    def one_definition(self):
        if (self.measure is None) == (self.ratio is None):
            raise ValueError('Exactly one of measure and ratio must be non-null')
        return self


class Threshold(Model):
    id: str
    name: str
    field: str
    operator: Literal['>', '>=', '<', '<=', '=']
    value: float
    unit: str | None
    description: str


class Term(Model):
    term: str
    definition: str


class Dataset(Model):
    source_id: str
    summary: str


class Context(Model):
    revision: int = Field(ge=1)
    title: str
    goal: str
    audience: str | None
    datasets: list[Dataset]
    derived_fields: list[DerivedField]
    kpis: list[Kpi]
    thresholds: list[Threshold]
    glossary: list[Term]
    issues: list[ValidationIssue]


class OutlineQuestion(Model):
    id: str
    text: str
    rationale: str
    recommended: bool
    selected: bool
    kpi_refs: list[str]
    origin: Literal['proposed', 'suggested', 'other']


class OutlineSection(Model):
    id: str
    title: str
    purpose: str
    questions: list[OutlineQuestion]


class Outline(Model):
    revision: int = Field(ge=1)
    sections: list[OutlineSection]


class ThemePreset(Model):
    id: str
    name: str
    description: str
    archetypes: list[Literal['executive', 'storytelling', 'operational', 'analytical']]
    background: Color
    surface: Color
    text: Color
    muted: Color
    accent: Color
    palette: list[Color]
    font_family: str
    radius: int
    decoration_kit: str


class Design(Model):
    revision: int = Field(ge=1)
    preset_id: str
    background: Color
    surface: Color
    text: Color
    accent: Color
    palette: list[Color] = Field(min_length=3, max_length=8)
    font_family: str
    page_structure: Literal['single', 'per_section']
    density: Literal['comfortable', 'compact']
    title: str
    subtitle: str | None
    source: Literal['preset', 'user', 'reference']
    issues: list[ValidationIssue]


class BlueprintMetric(Model):
    field: str
    agg: Literal['sum', 'avg', 'count', 'count_distinct', 'min', 'max', 'none']


class Sort(Model):
    field: str
    order: Literal['asc', 'desc']


class BlueprintComponent(Model):
    type: str
    label: str
    dimensions: list[str]
    metrics: list[BlueprintMetric]
    date_dimension: str | None
    breakdown: str | None
    sort: Sort | None
    options: dict[str, JsonValue]


class BlueprintRow(Model):
    question_id: str | None
    section_id: str
    page: int = Field(ge=1)
    component: BlueprintComponent
    note: str
    status: Literal['ok', 'blocked']
    issue_ids: list[str]


class JoinKey(Model):
    left: str
    right: str


class Join(Model):
    source_id: str
    on: list[JoinKey]


class ViewSources(Model):
    base: str
    joins: list[Join]
    union: list[str]

    @model_validator(mode='after')
    def one_combination(self):
        if self.joins and self.union:
            raise ValueError('Joins and union cannot both be non-empty')
        return self


class Blueprint(Model):
    revision: int = Field(ge=1)
    view_sources: ViewSources
    derived_fields: list[DerivedField]
    rows: list[BlueprintRow]
    view_table: str | None
    assessment_id: str | None


Artifact = Context | Outline | Design | Blueprint
