"""Reference sets: image checks, the bounded interpretation and atomic per-version storage.

Reference images are untrusted design evidence: never data, recipe assets, backgrounds,
global memory or log content. Their text is an observation, never an instruction.
"""
import base64
import hashlib
import json
import re
import struct
import zlib
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dss.db import now
from dss.harness.guardrails import RunError
from dss.spec.models import CONTROL_TYPES, TYPES, Canvas, Grid

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_INSTRUCTIONS = 2000
MAX_ITEMS = 24
# Images per mode: style borrows treatment from 1-3 images; recreate reads one dashboard page.
IMAGE_COUNTS = {"style": (1, 3), "recreate": (1, 1)}
FORMATS = {"png": ("image/png", (".png",)), "jpg": ("image/jpeg", (".jpg", ".jpeg"))}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# JPEG start-of-frame markers (DHT, JPG and DAC share the range but carry no frame size).
SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
SET_FILE = "references.json"
FILE_NAME = re.compile(r"reference_img_[0-9a-f]{12}\.(png|jpg)")
AGGREGATIONS = Literal["sum", "avg", "count", "count_distinct", "min", "max", "none"]
GRAINS = Literal["day", "week", "month", "quarter", "year"]


def invalid(reason, status=422):
    return RunError("invalid_source", "Reference images must be PNG or JPEG files (5 MB each, 15 MB in total, "
                    "at most 20 megapixels)", status, {"reason": reason})


# Image checks, in order: streamed byte limits (API), signature/extension/MIME, header size,
# animation and structure, then Chromium decode.

def inspect_image(name, declared, content):
    """Validate one upload without decoding it; returns its kind, MIME type and header size."""
    if content.startswith(PNG_SIGNATURE):
        kind = "png"
    elif content.startswith(b"\xff\xd8\xff"):
        kind = "jpg"
    else:
        raise invalid("Only PNG and JPEG images are supported")
    mime, suffixes = FORMATS[kind]
    if not name.lower().endswith(suffixes) or (declared or "").split(";")[0].strip().lower() != mime:
        raise invalid("File extension, content type and image signature must agree")
    width, height = png_size(content) if kind == "png" else jpeg_size(content)
    # Header size first: an oversized image never reaches the decoder.
    if width * height > MAX_PIXELS:
        raise invalid("Image exceeds 20 megapixels")
    png_scan(content) if kind == "png" else jpeg_scan(content)
    return {"ext": kind, "mime_type": mime, "width": width, "height": height}


def png_size(content):
    if len(content) < 33 or struct.unpack(">I4s", content[8:16]) != (13, b"IHDR"):
        raise invalid("PNG header is missing or corrupt")
    width, height = struct.unpack(">II", content[16:24])
    if not width or not height:
        raise invalid("PNG header is missing or corrupt")
    return width, height


def png_scan(content):
    """Walk every chunk to IEND with CRC checks; an acTL chunk means an animated PNG."""
    position = 8
    while position + 12 <= len(content):
        length, kind = struct.unpack(">I4s", content[position:position + 8])
        end = position + 12 + length
        if end > len(content) or zlib.crc32(content[position + 4:end - 4]) != struct.unpack(">I", content[end - 4:end])[0]:
            raise invalid("PNG data is truncated or corrupt")
        if kind == b"acTL":
            raise invalid("Animated PNG images are not supported")
        if kind == b"IEND":
            return
        position = end
    raise invalid("PNG data is truncated or corrupt")


def _jpeg_markers(content):
    """Yield (marker, segment start, segment length) from SOI up to and including SOS."""
    position = 2
    while True:
        while content[position:position + 2] == b"\xff\xff":
            position += 1  # fill bytes
        if position + 4 > len(content) or content[position] != 0xFF:
            raise invalid("JPEG data is truncated or corrupt")
        marker = content[position + 1]
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            position += 2
            continue
        if marker == 0xD9:
            raise invalid("JPEG data is truncated or corrupt")
        length = struct.unpack(">H", content[position + 2:position + 4])[0]
        if length < 2 or position + 2 + length > len(content):
            raise invalid("JPEG data is truncated or corrupt")
        yield marker, position, length
        if marker == 0xDA:
            return
        position += 2 + length


def jpeg_size(content):
    for marker, position, length in _jpeg_markers(content):
        if marker in SOF:
            height, width = struct.unpack(">HH", content[position + 5:position + 9]) if length >= 7 else (0, 0)
            if not width or not height:
                raise invalid("JPEG frame header is corrupt")
            return width, height
    raise invalid("JPEG has no frame header")


def jpeg_scan(content):
    """The scan must end with EOI; a truncated JPEG would otherwise decode as a partial image."""
    for marker, position, length in _jpeg_markers(content):
        if marker == 0xDA and content.rfind(b"\xff\xd9") > position + 2 + length:
            return
    raise invalid("JPEG data is truncated or corrupt")


DECODE = """async ({data, type}) => {
  try {
    const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
    // Bounded: a decode that never settles counts as a failure.
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 10000));
    const bitmap = await Promise.race([createImageBitmap(new Blob([bytes], {type})), timeout]);
    const size = [bitmap.width, bitmap.height];
    bitmap.close();
    return size;
  } catch (error) {
    return null;
  }
}"""


def decode(images):
    """Decode every image in the existing Playwright Chromium (no image library is approved).

    Run from a worker thread (sync Playwright, Windows). The decoded size must equal the header,
    in either order: Chromium applies EXIF orientation, which swaps a rotated photo's sides.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            for image in images:
                size = page.evaluate(DECODE, {"data": base64.b64encode(image["content"]).decode("ascii"),
                                              "type": image["mime_type"]})
                if size is None or sorted(size) != sorted([image["width"], image["height"]]):
                    raise invalid("Image could not be decoded")
        finally:
            browser.close()


# Bounded interpretation. The model reports boxes in thousandths (Gemini's native box scale);
# code normalizes them to 0..1. Null always means unknown, never a guess.

def _text(value):
    if isinstance(value, str):
        value = " ".join(value.split())
        return value or None
    return value


class ModelBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=1000)
    w: int = Field(ge=1, le=1000)
    h: int = Field(ge=1, le=1000)

    @model_validator(mode="after")
    def inside(self):
        if self.x + self.w > 1000 or self.y + self.h > 1000:
            raise ValueError("box must lie inside the image")
        return self


class Box(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside(self):
        if self.x + self.w > 1 + 1e-9 or self.y + self.h > 1 + 1e-9:
            raise ValueError("box must lie inside the image")
        return self


class ObservedItem(BaseModel):
    """One visible element as the model reports it; every nullable field is required."""
    model_config = ConfigDict(extra="forbid")
    kind: Literal["chart", "control", "decoration", "unknown"]
    label: str | None = Field(max_length=120)
    box: ModelBox
    chart_candidate: str | None = Field(max_length=40)
    metric_label: str | None = Field(max_length=120)
    unit: str | None = Field(max_length=40)
    aggregation: AGGREGATIONS | None
    date_grain: GRAINS | None
    confidence: Literal["high", "medium", "low"]

    @field_validator("label", "metric_label", "unit", mode="before")
    @classmethod
    def plain(cls, value):
        return _text(value)

    @field_validator("chart_candidate", mode="before")
    @classmethod
    def candidate(cls, value):
        # A component-type-like token: "Time series" -> time_series; unknown names stay for feasibility.
        if isinstance(value, str):
            value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
            return value or None
        return value


class Item(ObservedItem):
    id: str
    box: Box


class Interpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["style", "recreate"]
    aspect_ratio: float = Field(gt=0)
    palette_notes: str = Field(max_length=1000)
    type_notes: str = Field(max_length=1000)
    spacing_notes: str = Field(max_length=1000)
    items: list[Item] = Field(max_length=MAX_ITEMS)


def interpret(mode, width, height, notes, observed):
    """Code-owned interpretation: ids, normalized boxes, aspect ratio from the image header.

    Style mode keeps geometry and treatment only; chart and data fields are cleared, so a style
    reference never imports chart or data requirements.
    """
    items = []
    for number, item in enumerate(observed, 1):
        values = item.model_dump()
        values["box"] = {key: value / 1000 for key, value in values["box"].items()}
        if mode == "style":
            values.update(chart_candidate=None, metric_label=None, unit=None, aggregation=None, date_grain=None)
        items.append(Item(id=f"o{number}", **values))
    return Interpretation(mode=mode, aspect_ratio=round(width / height, 4), items=items, **notes)


# Reference analysis (dashboard-intent.md 1.3): the model proposes one disposition per visible
# item; code validates it, orders the items, assigns ids and writes the summary.

KINDS = Literal["chart", "control", "kpi", "text", "image", "legend", "other"]
DISPOSITIONS = Literal["native", "static"]
CONTROL_KINDS = ("control",)
MAX_NOTE = 1000


def _plain(value):
    return " ".join(value.split()) if isinstance(value, str) else value


def type_token(value):
    """'Time series' -> time_series; membership in allowed_types is checked by code."""
    if isinstance(value, str):
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or None
    return value


class AnalysisAnswer(BaseModel):
    """One visible item as the model proposes it; boxes in thousandths, like ObservedItem."""
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=120)
    kind: KINDS
    box: ModelBox
    disposition: DISPOSITIONS
    type: str | None = Field(max_length=40)
    shows: str = Field(max_length=300)
    reason: str = Field(max_length=300)

    @field_validator("label", "shows", "reason", mode="before")
    @classmethod
    def plain(cls, value):
        return _plain(value)

    @field_validator("type", mode="before")
    @classmethod
    def token(cls, value):
        return type_token(value)


class Proposed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disposition: DISPOSITIONS
    type: str | None


class AnalysisItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^r[1-9][0-9]*$")
    label: str = Field(min_length=1, max_length=120)
    kind: KINDS
    box: Box
    disposition: DISPOSITIONS
    type: str | None
    shows: str = Field(max_length=300)
    reason: str = Field(max_length=300)
    proposed: Proposed


class AnalysisIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    message: str


class ReferenceAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    state: Literal["pending", "approved"]
    summary: str
    items: list[AnalysisItem] = Field(min_length=1, max_length=MAX_ITEMS)
    note: str = Field(max_length=MAX_NOTE)
    allowed_types: list[str]
    issues: list[AnalysisIssue]


def item_issues(index, kind, disposition, kind_type, allowed):
    """Code rules for one item's split (analysis and later edits): [(path, message)].

    A native item needs a type from `allowed`; control types only on kind control, and a native
    control only with a control type; a static item has no type.
    """
    path = f"/items/{index}/type"
    if disposition == "static":
        return [(path, "A static item has no type")] if kind_type is not None else []
    if kind_type is None:
        return [(path, "A native item needs a type")]
    issues = []
    if kind_type not in allowed:
        issues.append((path, "Type is not one of the allowed types"))
    elif (kind_type in CONTROL_TYPES) != (kind in CONTROL_KINDS):
        issues.append((path, "Control types are only for controls, and a native control needs a control type"))
    return issues


def answer_errors(answers, allowed):
    """Code checks on a validated model answer, with paths into that answer for its one repair."""
    return [{"path": "items" + path.removeprefix("/items").replace("/", "."), "message": message}
            for n, a in enumerate(answers) for path, message in item_issues(n, a.kind, a.disposition, a.type, allowed)]


def raw_answer_errors(reply, allowed):
    """The same code checks on a schema-rejected reply's items whose kind, disposition and type parse,
    so the one repair lists every error at once."""
    items = reply.get("items") if isinstance(reply, dict) else None
    errors = []
    for n, raw in enumerate(items if isinstance(items, list) else []):
        if (isinstance(raw, dict) and isinstance(raw.get("kind"), str) and raw.get("disposition") in ("native", "static")
                and (raw.get("type") is None or isinstance(raw.get("type"), str))):
            errors += [{"path": f"items.{n}.type", "message": message}
                       for _, message in item_issues(n, raw["kind"], raw["disposition"], type_token(raw.get("type")), allowed)]
    return errors


def _count(number, noun):
    return f"{number} {noun}{'s' * (number != 1)}"


def analysis_summary(items):
    """'N charts and M controls can be native Data Studio components; K items stay static art.'

    Charts count every native item that is not a control (kind chart, kpi or other kinds the user
    made native), controls the native kind-control items, and the rest stays static.
    """
    native = [i for i in items if i.disposition == "native"]
    controls = sum(i.kind in CONTROL_KINDS for i in native)
    static = len(items) - len(native)
    component = "a native Data Studio component" if len(native) == 1 else "native Data Studio components"
    return (f"{_count(len(native) - controls, 'chart')} and {_count(controls, 'control')} can be {component}; "
            f"{_count(static, 'item')} {'stays' if static == 1 else 'stay'} static art.")


def analyze(answers, allowed):
    """A pending revision-1 analysis from a validated answer without code errors: ids r1.. in
    reading order (top-to-bottom, then left-to-right by box centre), `proposed` = the answer."""
    ordered = sorted(answers, key=lambda a: (a.box.y + a.box.h / 2, a.box.x + a.box.w / 2))
    items = [AnalysisItem(id=f"r{n}", label=a.label, kind=a.kind,
                          box={key: value / 1000 for key, value in a.box.model_dump().items()},
                          disposition=a.disposition, type=a.type, shows=a.shows, reason=a.reason,
                          proposed=Proposed(disposition=a.disposition, type=a.type))
             for n, a in enumerate(ordered, 1)]
    return ReferenceAnalysis(revision=1, state="pending", summary=analysis_summary(items), items=items, note="",
                             allowed_types=list(allowed), issues=[])


def canvas_height(aspect_ratio):
    return max(1, round(Canvas().width / aspect_ratio))


def grid_cell(box, aspect_ratio):
    """Map a normalized box into the renderer's 1200px, 12-column, 20px-row grid.

    Both edges snap independently (layout.py's cell geometry), so adjacent boxes stay adjacent.
    """
    canvas, grid = Canvas(), Grid()
    step = (canvas.width - 2 * grid.margin + grid.gutter) / grid.columns  # column width + gutter
    height = canvas_height(aspect_ratio)
    col = min(grid.columns, max(1, 1 + round((box.x * canvas.width - grid.margin) / step)))
    end = round(((box.x + box.w) * canvas.width - grid.margin + grid.gutter) / step)
    row = max(1, 1 + round((box.y * height - grid.margin) / grid.row_height))
    bottom = 1 + round(((box.y + box.h) * height - grid.margin + grid.gutter) / grid.row_height)
    return {"col": col, "row": row, "w": max(1, min(grid.columns, end) - col + 1), "h": max(1, bottom - row)}


def structural_changes(interpretation):
    """Code-made explanations of what the 12-column target or the app cannot keep as observed."""
    canvas, grid = Canvas(), Grid()
    step = (canvas.width - 2 * grid.margin + grid.gutter) / grid.columns
    changes = []
    if interpretation.mode == "recreate":
        unsupported = [i.id for i in interpretation.items
                       if i.kind in ("chart", "control") and i.chart_candidate and i.chart_candidate not in TYPES]
        if unsupported:
            changes.append("No matching component type for " + ", ".join(unsupported)
                           + "; the feasibility check offers a supported alternative or asks.")
        unknown = [i.id for i in interpretation.items if i.kind in ("chart", "control") and not i.chart_candidate]
        if unknown:
            changes.append("Chart type unknown for " + ", ".join(unknown) + "; it stays unknown until clarified.")
    narrow = [i.id for i in interpretation.items if i.box.w * canvas.width < step * 0.75]
    if narrow:
        changes.append("Widened to one grid column: " + ", ".join(narrow) + ".")
    cells = {i.id: grid_cell(i.box, interpretation.aspect_ratio) for i in interpretation.items if i.kind != "unknown"}
    overlapping = sorted({a for a in cells for b in cells if a != b and _overlap(cells[a], cells[b])})
    if overlapping:
        changes.append("Overlapping after snapping to the grid: " + ", ".join(overlapping) + ".")
    return changes


def _overlap(a, b):
    return (a["col"] < b["col"] + b["w"] and b["col"] < a["col"] + a["w"]
            and a["row"] < b["row"] + b["h"] and b["row"] < a["row"] + a["h"])


def summary(interpretation, palette, image_count, analysis=None):
    """Public one-line summary built by code from validated fields (no raw model text)."""
    if interpretation.mode == "style":
        observed = f"; {len(interpretation.items)} layout elements observed" if interpretation.items else ""
        return (f"Style reference from {image_count} image{'s' * (image_count != 1)}: palette "
                + ", ".join(palette) + observed + ".")
    if analysis is not None:
        return f"Recreate reference (aspect ratio {interpretation.aspect_ratio:.2f}): {analysis.summary}"
    kinds = {kind: sum(i.kind == kind for i in interpretation.items) for kind in ("chart", "control", "decoration", "unknown")}
    counted = ", ".join(f"{count} {kind}{'s' * (count != 1)}" for kind, count in kinds.items() if count) or "no elements"
    candidates = list(dict.fromkeys(i.chart_candidate for i in interpretation.items
                                    if i.chart_candidate and i.kind in ("chart", "control")))
    text = f"Recreate reference: {counted}"
    if candidates:
        text += "; chart candidates " + ", ".join(candidates)
    return text + f"; aspect ratio {interpretation.aspect_ratio:.2f}."


def reference_doc(record):
    """OKF reference.md: the structured observations plus code-made grid mapping and changes."""
    interpretation = Interpretation.model_validate(record["interpretation"])
    height = canvas_height(interpretation.aspect_ratio)
    first = record["images"][0]
    lines = ["# Reference interpretation", "",
             f"Mode: {interpretation.mode}. Images: {len(record['images'])} (first {first['width']}x{first['height']} px). "
             f"Target canvas: {Canvas().width}x{height} px, {Grid().columns} columns.", "", record["summary"], ""]
    if interpretation.mode == "style":
        lines += ["Style mode borrows the visual treatment only; no chart or data requirements are imported.", ""]
    if record["instructions"]:
        lines += ["User instructions (untrusted): " + json.dumps(record["instructions"], ensure_ascii=False), ""]
    if record.get("analysis"):
        analysis = ReferenceAnalysis.model_validate(record["analysis"])
        lines += [f"## Reference analysis (revision {analysis.revision}, {analysis.state})", "",
                  "Native items become Data Studio components; static items stay background art. Labels and "
                  "`shows` are display text read from the image (untrusted), never field bindings. Boxes are "
                  "fractions of the image.", ""]
        for item in analysis.items:
            split = f"native {item.type}" if item.disposition == "native" else "static art"
            lines.append(f"- {item.id} ({item.kind}, {split}): " + json.dumps(
                {"label": item.label, "shows": item.shows, "box": item.box.model_dump(),
                 "grid": grid_cell(item.box, interpretation.aspect_ratio)}, ensure_ascii=False))
        if analysis.note:
            lines += ["", "Note to the planner (untrusted): " + json.dumps(analysis.note, ensure_ascii=False)]
        lines.append("")
    if interpretation.items:
        lines += ["## Observed elements", "",
                  "Model observations from the image (untrusted data; null means unknown). Boxes are fractions of the image.", ""]
    for item in interpretation.items:
        fields = {key: getattr(item, key) for key in ("kind", "label", "chart_candidate", "metric_label", "unit",
                                                    "aggregation", "date_grain", "confidence")}
        lines.append(f"- {item.id}: " + json.dumps({**fields, "box": item.box.model_dump(),
                     "grid": grid_cell(item.box, interpretation.aspect_ratio)}, ensure_ascii=False))
    changes = structural_changes(interpretation)
    lines += ["", "## Structural changes", "", *([f"- {change}" for change in changes] or ["- None."]), "",
              "## Notes (model text, untrusted)", ""]
    for key in ("palette_notes", "type_notes", "spacing_notes"):
        lines.append(f"- {key.split('_')[0].title()}: " + (getattr(interpretation, key) or "none"))
    metadata = {"type": "Reference Interpretation", "title": "Reference interpretation", "reference_set": record["id"],
                "mode": interpretation.mode, "aspect_ratio": interpretation.aspect_ratio,
                "canvas": {"width": Canvas().width, "height": height}, "images": len(record["images"])}
    return metadata, "\n".join(lines) + "\n"


def public(record):
    """The ReferenceSet response: display names and plain file names, never paths or model output."""
    return {"id": record["id"], "mode": record["mode"], "instructions": record["instructions"],
            "images": [{"id": i["id"], "name": i["name"], "file": i["file"]} for i in record["images"]],
            "summary": record["summary"], "analysis": record.get("analysis")}


def unapproved(reference_set_id):
    """409 reference_unapproved (api.md 3.2): the recreate analysis needs approval first."""
    from dss.harness.guardrails import RunError
    return RunError("reference_unapproved", "Approve the reference analysis before continuing.", 409,
                    {"reference_set_id": reference_set_id})


def analysis_conflict(revision):
    """409 reference_analysis_conflict (api.md 3.2): the client edited a stale revision."""
    from dss.harness.guardrails import RunError
    return RunError("reference_analysis_conflict", "The reference analysis changed; reload it.", 409,
                    {"revision": revision})


def load(folder):
    path = folder / SET_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def image_entry(image):
    """The persisted descriptor of one image (no bytes)."""
    return {**{key: image[key] for key in ("id", "name", "file", "mime_type", "width", "height")},
            "bytes": len(image["content"]), "sha256": hashlib.sha256(image["content"]).hexdigest()}


def _front(path):
    text = path.read_text(encoding="utf-8")
    return (yaml.safe_load(text.split("---", 2)[1]) or {}) if text.startswith("---") else {}


def commit(folder, record, images, docs):
    """Replace the version's reference set atomically: everything lands, or nothing changes.

    `docs` maps a build-doc name to (frontmatter, body). references.json is written last (the
    commit point); any failure removes the new bytes and restores the previous documents.
    """
    from dss.harness.nodes.intake import write_doc
    docs_dir = folder / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    old = load(folder)
    targets = [folder / SET_FILE, docs_dir / "index.md", docs_dir / "log.md", *(docs_dir / name for name in docs)]
    backup = {path: path.read_bytes() for path in targets if path.is_file()}
    written = []
    try:
        for image in images:
            path = folder / image["file"]
            written.append(path)
            path.write_bytes(image["content"])
        for name, (metadata, body) in docs.items():
            write_doc(docs_dir / name, metadata, body)
        _index(docs_dir, {name: metadata["title"] for name, (metadata, _) in docs.items()}, write_doc)
        _log(docs_dir, f"reference set {record['id']} ({record['mode']}, {len(images)} image(s)) saved", write_doc)
        temporary = folder / (SET_FILE + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(folder / SET_FILE)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        for path in targets:
            if path in backup:
                path.write_bytes(backup[path])
            else:
                path.unlink(missing_ok=True)
        (folder / (SET_FILE + ".tmp")).unlink(missing_ok=True)
        raise
    keep = {image["file"] for image in record["images"]}
    for image in (old or {}).get("images", []):
        if image["file"] not in keep and FILE_NAME.fullmatch(image["file"]):
            (folder / image["file"]).unlink(missing_ok=True)


def remove(folder):
    """Clear the set: references.json first (the commit point), then reference.md, a reference-owned
    style.md and the retained bytes. Returns whether a set existed."""
    from dss.harness.nodes.intake import write_doc
    record = load(folder)
    docs_dir = folder / "docs"
    if record is None:
        return False
    (folder / SET_FILE).unlink()
    removed = []
    for name in ("reference.md", "style.md"):
        path = docs_dir / name
        if path.is_file() and (name == "reference.md" or _front(path).get("reference_set")):
            path.unlink()
            removed.append(name)
    for path in folder.iterdir():
        if FILE_NAME.fullmatch(path.name):
            path.unlink()
    index = docs_dir / "index.md"
    if index.is_file() and removed:
        lines = index.read_text(encoding="utf-8").splitlines(keepends=True)
        index.write_text("".join(line for line in lines if not any(f"({name})" in line for name in removed)), encoding="utf-8")
    if docs_dir.is_dir():
        _log(docs_dir, f"reference set {record['id']} removed", write_doc)
    return True


def _index(docs_dir, titles, write_doc):
    index = docs_dir / "index.md"
    if not index.exists():
        write_doc(index, {"type": "Index", "title": "Build documents"}, "# Build documents\n")
    text = index.read_text(encoding="utf-8")
    missing = [f"- [{title}]({name})" for name, title in titles.items() if f"({name})" not in text]
    if missing:
        index.write_text(text.rstrip("\n") + "\n" + "\n".join(missing) + "\n", encoding="utf-8")


def _log(docs_dir, entry, write_doc):
    log = docs_dir / "log.md"
    if not log.exists():
        write_doc(log, {"type": "Log", "title": "Build log"}, "# Build log\n")
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n- {now()}: {entry}\n")
