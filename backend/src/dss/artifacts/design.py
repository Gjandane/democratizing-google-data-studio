"""Code-only Design stage: seed presets, accessible prefill and editable preferences."""
from pathlib import Path

from dss.artifacts import state as stages
from dss.artifacts.models import Design, ThemePreset, ValidationIssue
from dss.artifacts.okf import atomic_write, frontmatter, read_artifact, write_artifact
from dss.spec import references

KNOWLEDGE = Path(__file__).resolve().parents[3] / 'knowledge'
DEFAULTS = {'executive': 'studio_light', 'storytelling': 'field_notes',
            'operational': 'night_ops', 'analytical': 'graphite'}


def presets():
    result = []
    for path in sorted((KNOWLEDGE / 'themes').glob('*.md')):
        meta = frontmatter(path)
        if meta['type'] == 'Theme Preset':
            result.append(ThemePreset.model_validate({k: v for k, v in meta.items() if k != 'type'}))
    return result


def fonts():
    return frontmatter(KNOWLEDGE / 'datastudio/fonts.md')['fonts']


def linear(color):
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]


def contrast(first, second):
    def luminance(color):
        return sum(v * w for v, w in zip(linear(color), (.2126, .7152, .0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


def on_color(background):
    """All kit text on an accent uses the higher contrast black/white pair."""
    return max(('#000000', '#FFFFFF'), key=lambda text: contrast(text, background))


def snap_background(color, text):
    """Nearest sRGB blend toward black/white that meets the preset text contrast.

    Reference colors are already hex validated. Keep the preset's text, surface,
    font and kit; only the requested background/accent/series colors override it.
    """
    if contrast(color, text) >= 4.5:
        return color.upper()
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    candidates = []
    for end in (0, 255):
        for step in range(1, 256):
            mixed = [round(v + (end - v) * step / 255) for v in rgb]
            candidate = '#' + ''.join(f'{v:02X}' for v in mixed)
            if contrast(candidate, text) >= 4.5:
                candidates.append((sum((a - b) ** 2 for a, b in zip(rgb, mixed)), candidate))
                break
    return min(candidates)[1]


def selected_sections(outline):
    return sum(any(q.selected for q in section.questions) for section in outline.sections) if outline else 0


def validate(design, outline):
    """Structural errors are 422 at the boundary; editable semantic errors are issues."""
    result = design.model_copy(deep=True)
    issues = []
    def issue(path, message):
        issues.append(ValidationIssue(path=path, message=message))
    available = presets()
    if result.preset_id not in {p.id for p in available}:
        issue('/preset_id', 'Choose an available theme preset')
    if result.font_family not in {p.font_family for p in available}:
        issue('/font_family', 'Choose a font used by a theme preset')
    for role in ('background', 'surface'):
        if contrast(result.text, getattr(result, role)) < 4.5:
            issue('/' + role, 'Text contrast must be at least 4.5:1 on ' + role)
    if len(result.title) > 80:
        issue('/title', 'Use a title of at most 80 characters')
    if result.page_structure == 'per_section' and not 1 <= selected_sections(outline) <= 5:
        issue('/page_structure', 'Per-section pages need 1-5 sections with a selected question')
    result.issues = issues
    return result


def prefill(build, context, outline, style=None):
    preset = next(p for p in presets() if p.id == DEFAULTS[build['archetype']])
    values = {k: getattr(preset, k) for k in ('background', 'surface', 'text', 'accent', 'font_family')}
    palette = list(preset.palette)
    if style is not None:
        values['background'] = snap_background(style.background, preset.text)
        values['accent'] = style.accent
        palette = list(style.palette)
        for color in preset.palette:
            if len(palette) >= 3:
                break
            if color not in palette:
                palette.append(color)
    design = Design(revision=1, preset_id=preset.id, **values, palette=palette,
        page_structure='per_section' if 1 <= selected_sections(outline) <= 5 else 'single',
        density='compact' if build['archetype'] in ('operational', 'analytical') else 'comfortable',
        title=(context.title if context else build['title'])[:80], subtitle=None,
        source='reference' if style is not None else 'preset', issues=[])
    return validate(design, outline)


def reference_style(folder):
    """Only the active, reference-owned StyleProfile is eligible for prefill."""
    from dss.harness.nodes.style_extract import StyleProfile
    record = references.load(folder)
    path = folder / 'docs/style.md'
    if not record or record['mode'] not in ('style', 'recreate') or not path.is_file():
        return None
    meta = frontmatter(path)
    if meta['type'] != 'Style Profile' or meta.get('reference_set') != record['id']:
        return None
    return StyleProfile.model_validate({k: meta[k] for k in StyleProfile.model_fields if k in meta})


def load(folder):
    path = folder / 'docs/design.md'
    return read_artifact(path, Design) if path.is_file() else None


async def persist(harness, build, folder, design):
    old = load(folder)
    design = design.model_copy(update={'revision': old.revision + 1 if old else 1})
    transition = stages.edited(build, 'design')
    docs = folder / 'docs'
    before = {docs / name: (docs / name).read_bytes() if (docs / name).is_file() else None
              for name in ('design.md', 'index.md', 'log.md')}
    events = []
    async def collect(kind, payload):
        events.append((kind, payload))
    try:
        await write_artifact(docs / 'design.md', design, emit=collect)
        stages.save(harness.db, build['id'], transition)
    except Exception:
        # No event has escaped. Restore only changed files (a locked log may
        # have caused the failure), leaving the prior flags and documents paired.
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            elif not path.is_file() or path.read_bytes() != content:
                atomic_write(path, content.decode('utf-8'))
        raise
    # Event transport can fail after commit; saved edits already have draft/stale
    # flags, so recipe/run cannot consume a falsely confirmed artifact.
    for kind, payload in events:
        await harness.emit(build['id'], None, kind, payload)
    from dss.api.builds import build_response
    await harness.emit(build['id'], None, 'stage.changed', {'stage': 'design'})
    await harness.emit(build['id'], None, 'build.updated', {
        'build': build_response(harness.db, harness.models.settings.get(), build['id'])})
    return design
