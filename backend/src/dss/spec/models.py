"""Typed Dashboard Spec; semantic constraints are checked against the catalog."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_serializer

CHART_TYPES = ("scorecard", "time_series", "area", "bar", "pie", "table", "pivot_table", "geo_map", "scatter")
CONTROL_TYPES = ("date_range", "dropdown", "fixed_size_list")
TYPES = (*CHART_TYPES, "text", "image", *CONTROL_TYPES)
# Controls bound through `field` (a Blueprint row's single dimension), not `dimensions`.
FIELD_CONTROLS = ("dropdown", "fixed_size_list")
# Charts drawn over `date_dimension`: one date-grain rule (options.date_granularity) for both.
DATE_AXIS_TYPES = ("time_series", "area")
SYNTHETIC_LABEL_ID = 'p1_synthetic_sample_data'
SYNTHETIC_LABEL = 'Synthetic sample data'


def reference_image(path):
    """True for a stored reference screenshot (code names them reference_*), whatever the folder,
    case or separator: a screenshot is evidence, never a recipe image, logo or background."""
    return str(path).replace('\\', '/').rsplit('/', 1)[-1].casefold().startswith('reference_')


def image_paths(spec):
    """(path, image path) for every spec image asset: image components and logo decorations."""
    for p, page in enumerate(spec.pages):
        for i, c in enumerate(page.components):
            if c.image_path:
                yield f"pages.{p}.components.{i}.image_path", c.image_path
        for i, d in enumerate(page.decorations):
            if d.style.get('image_path'):
                yield f"pages.{p}.decorations.{i}.style.image_path", d.style['image_path']

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Canvas(Model):
    # Code-laid builds keep 1200; a designed page 1 sets 1200-1920 (#Designed pages).
    width: int = Field(default=1200, ge=1200, le=1920, strict=True)
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

class Box(Model):
    """Measured pixel box of a component on a designed page; Layout returns it unchanged."""
    x: int = Field(ge=0, strict=True)
    y: int = Field(ge=0, strict=True)
    w: int = Field(ge=1, strict=True)
    h: int = Field(ge=1, strict=True)


class Design(Model):
    """A designed page: the sanitized page HTML, stored so versions and reloads need no model."""
    html: str = Field(min_length=1)
    source: str = Field(min_length=1)  # provenance, e.g. "designer" or "revise"
    model: str = Field(min_length=1)


def _without_none(handler, value, keys):
    # Code-laid specs serialize byte for byte as before the optional designed-page keys.
    data = handler(value)
    for key in keys:
        if getattr(value, key) is None:
            data.pop(key, None)
    return data


Color = Annotated[str, Field(strict=True, pattern=r"^#[0-9A-Fa-f]{6}$", min_length=7, max_length=7)]


class Theme(Model):
    background: Color = "#F1F5F9"
    surface: Color = "#FFFFFF"
    text: Color = "#0F172A"
    muted: Color = "#64748B"
    accent: Color = "#1E40AF"
    palette: list[Color] = Field(default_factory=lambda: ["#1E40AF", "#0D9488"])
    font_family: str = "Arial"
    radius: int = Field(default=8, ge=0)

class Metric(Model):
    field: str = Field(min_length=1)
    agg: Literal["sum", "avg", "count", "count_distinct", "min", "max", "none"]

class Sort(Model):
    """The recipe contract's add_chart.sort shape; renderer and compiler read it as is."""
    field: str = Field(min_length=1)
    order: Literal["asc", "desc"]

class Component(Model):
    id: str = Field(pattern=r"^p[1-9][0-9]*_[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    type: Literal[TYPES]
    label: str
    grid: Cell  # the code layout's cell; on a designed page the fallback if the design is dropped
    box: Box | None = None
    dimensions: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    date_dimension: str | None = None
    breakdown: str | None = None
    sort: Sort | None = None
    options: dict = Field(default_factory=dict)
    colors: list[Color] | None = Field(default=None, min_length=1, max_length=20)
    text: str | None = None
    image_path: str | None = None
    field: str | None = None
    question_ref: str | None = None
    # The approved native reference item this component fulfils (Blueprint row reference_item); omitted when None.
    reference_item: str | None = None

    @model_serializer(mode='wrap')
    def _serialize(self, handler):
        return _without_none(handler, self, ('box', 'reference_item'))

class Decoration(Model):
    id: str = Field(pattern=r"^p[1-9][0-9]*_[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    kind: Literal["band", "panel", "title", "subtitle", "text", "logo", "divider", "design"]
    grid: Cell
    text: str | None = None
    style: dict = Field(default_factory=dict)

class Page(Model):
    index: int = Field(ge=1)
    name: str
    height: int = Field(gt=0)
    decorations: list[Decoration] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    design: Design | None = None

    @model_serializer(mode='wrap')
    def _serialize(self, handler):
        return _without_none(handler, self, ('design',))

class DataField(Model):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    label: str
    role: Literal["dimension", "metric"]
    default_agg: Literal["sum", "avg", "count", "count_distinct", "min", "max", "none"] = "none"
    # A *_TRUNC derived field's bucket grain, or a base DATE column's profiled bucket start
    # (month, quarter, year), set by code layout from the view's derivation or the intake profile;
    # the compiler emits it as a time series' or area's options.date_granularity (recipe 1.2/1.3).
    date_granularity: Literal["day", "week", "month", "quarter", "year"] | None = None

    def __getitem__(self, key):
        return getattr(self, key)

    @model_serializer(mode='wrap')
    def _serialize(self, handler):
        return _without_none(handler, self, ('date_granularity',))

class Datasource(Model):
    table: str = Field(pattern=r"^[^.\s]+\.[^.\s]+\.[^.\s]+$")
    fields: list[DataField] = Field(default_factory=list)
    synthetic: bool = False

class DashboardSpec(Model):
    spec_version: int = Field(ge=1)
    build_id: str = Field(pattern=r"^b_[0-9a-f]{12}$")
    title: str = Field(min_length=1)
    archetype: str
    canvas: Canvas = Field(default_factory=Canvas)
    grid: Grid = Field(default_factory=Grid)
    theme: Theme = Field(default_factory=Theme)
    datasource: Datasource
    pages: list[Page] = Field(min_length=1, max_length=5)
