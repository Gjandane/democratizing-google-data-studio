"""Typed Dashboard Spec; semantic constraints are checked against the catalog."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

TYPES = ("scorecard", "time_series", "bar", "pie", "table", "pivot_table", "geo_map", "scatter", "text", "image", "date_range", "dropdown")

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Canvas(Model):
    width: Literal[1200] = 1200
    height: int = Field(default=900, gt=0)

class Grid(Model):
    columns: Literal[12] = 12
    row_height: Literal[20] = 20
    gutter: Literal[16] = 16
    margin: Literal[24] = 24

class Cell(Model):
    col: int = Field(ge=1)
    row: int = Field(ge=1)
    w: int = Field(ge=1)
    h: int = Field(ge=1)

class Theme(Model):
    background: str = "#F1F5F9"
    surface: str = "#FFFFFF"
    text: str = "#0F172A"
    muted: str = "#64748B"
    accent: str = "#1E40AF"
    palette: list[str] = Field(default_factory=lambda: ["#1E40AF", "#0D9488"])
    font_family: str = "Arial"
    radius: int = Field(default=8, ge=0)

class Metric(Model):
    field: str = Field(min_length=1)
    agg: Literal["sum", "avg", "count", "count_distinct", "min", "max", "none"]

class Component(Model):
    id: str = Field(pattern=r"^p[1-9][0-9]*_[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    type: Literal["scorecard", "time_series", "bar", "pie", "table", "pivot_table", "geo_map", "scatter", "text", "image", "date_range", "dropdown"]
    label: str
    grid: Cell
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    date_dimension: str | None = None
    breakdown: str | None = None
    sort: dict | None = None
    options: dict = Field(default_factory=dict)
    text: str | None = None
    image_path: str | None = None
    field: str | None = None
    question_ref: str | None = None

class Decoration(Model):
    id: str = Field(pattern=r"^p[1-9][0-9]*_[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    kind: Literal["band", "panel", "title", "subtitle", "text", "logo", "divider"]
    grid: Cell
    text: str | None = None
    style: dict = Field(default_factory=dict)

class Page(Model):
    index: int = Field(ge=1)
    name: str
    height: int = Field(gt=0)
    decorations: list[Decoration] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)

class DataField(Model):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    label: str
    role: Literal["dimension", "metric"]
    default_agg: Literal["sum", "avg", "count", "count_distinct", "min", "max", "none"] = "none"

    def __getitem__(self, key):
        return getattr(self, key)

class Datasource(Model):
    table: str = Field(pattern=r"^[^.\s]+\.[^.\s]+\.[^.\s]+$")
    fields: list[DataField] = Field(default_factory=list)

class DashboardSpec(Model):
    spec_version: int = Field(ge=1)
    build_id: str = Field(pattern=r"^b_[0-9a-f]{12}$")
    title: str = Field(min_length=1)
    archetype: str
    canvas: Canvas = Field(default_factory=Canvas)
    grid: Grid = Field(default_factory=Grid)
    theme: Theme = Field(default_factory=Theme)
    datasource: Datasource
    pages: list[Page] = Field(min_length=1, max_length=1)
