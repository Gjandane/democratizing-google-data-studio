"""Check the submission deck against the AI Builder Cup template (task 1.3, final in 4.2).

Reads the expected section titles and brand images from the template itself, then checks
deck/AI-Builder-Cup-Submission.pptx and .pdf: slide count, section order, the six added
architecture slides, a picture or enough words on every content slide, the 90-word body cap,
fresh diagram PNGs, no TBD (unless --draft), the PDF page count and the template's SHA-256.

Usage: uv run --project integration python integration/check_deck.py [--draft]
Stdlib only. Exit 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "Submission Template _ AI Builder Cup.pptx"
OUT_PPTX = ROOT / "deck" / "AI-Builder-Cup-Submission.pptx"
OUT_PDF = ROOT / "deck" / "AI-Builder-Cup-Submission.pdf"
CONTENT = ROOT / "deck" / "content.json"
PROGRESS = ROOT / "docs" / "progress.md"
DIAGRAMS = ROOT / "deck" / "diagrams"

# The six slides this project adds after the template's Architecture slide (docs/plan.md, 1.3).
ADDED_TITLES = [
    "Parts and data flow",
    "The harness: three memories",
    "ADK graph and repair loop",
    "Token economy",
    "Recipe and engine",
    "Cloud Run deployment",
]
MIN_SLIDES, MAX_SLIDES = 17, 21
MAX_BODY_WORDS = 90
MIN_TEXT_WORDS = 25

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
R_ID = "{%s}id" % NS["r"]
R_EMBED = "{%s}embed" % NS["r"]


@dataclass
class Slide:
    title: str = ""
    body: str = ""
    has_text: bool = False
    picture_hashes: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def body_words(self) -> int:
        return len(self.body.split())


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Relationship id -> target part path for one package part."""
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", name + ".rels")
    if rels_path not in z.namelist():
        return {}
    out = {}
    for rel in ET.fromstring(z.read(rels_path)).iter(REL_NS + "Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        out[rel.get("Id")] = posixpath.normpath(posixpath.join(folder, rel.get("Target")))
    return out


def _paragraphs(sp: ET.Element) -> list[str]:
    paras = []
    for p in sp.iterfind(".//p:txBody/a:p", NS):
        paras.append("".join(t.text or "" for t in p.iter("{%s}t" % NS["a"])))
    return paras


def _top(sp: ET.Element) -> int:
    off = sp.find("./p:spPr/a:xfrm/a:off", NS)
    return int(off.get("y")) if off is not None else 1 << 62


def read_deck(path: Path) -> list[Slide]:
    slides = []
    with zipfile.ZipFile(path) as z:
        pres_rels = _rels(z, "ppt/presentation.xml")
        pres = ET.fromstring(z.read("ppt/presentation.xml"))
        for sld_id in pres.iterfind("./p:sldIdLst/p:sldId", NS):
            part = pres_rels[sld_id.get(R_ID)]
            rels = _rels(z, part)
            root = ET.fromstring(z.read(part))
            slide = Slide()
            text_shapes = []
            for sp in root.iter("{%s}sp" % NS["p"]):
                paras = _paragraphs(sp)
                if any(p.strip() for p in paras):
                    text_shapes.append((_top(sp), paras))
            if text_shapes:
                slide.has_text = True
                text_shapes.sort(key=lambda item: item[0])
                title_paras = [p for p in text_shapes[0][1]]
                first = next(i for i, p in enumerate(title_paras) if p.strip())
                slide.title = title_paras[first].strip()
                rest = title_paras[first + 1 :] + [p for _, paras in text_shapes[1:] for p in paras]
                slide.body = " ".join(p.strip() for p in rest if p.strip())
            for blip in root.iter("{%s}blip" % NS["a"]):
                target = rels.get(blip.get(R_EMBED))
                if target and target in z.namelist():
                    slide.picture_hashes.append(hashlib.sha256(z.read(target)).hexdigest())
            for target in rels.values():
                if "notesSlide" in target and target in z.namelist():
                    note_root = ET.fromstring(z.read(target))
                    slide.notes = " ".join(t.text or "" for t in note_root.iter("{%s}t" % NS["a"]))
            slides.append(slide)
    return slides


def pdf_pages(path: Path) -> int:
    data = path.read_bytes()
    counts = [int(n) for n in re.findall(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)", data)]
    counts += [int(n) for n in re.findall(rb"/Count\s+(\d+)[^>]*?/Type\s*/Pages\b", data)]
    if counts:
        return max(counts)
    return len(re.findall(rb"/Type\s*/Page(?![s\w])", data))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--draft", action="store_true", help="allow TBD placeholders (deck draft)")
    args = ap.parse_args()

    failures: list[str] = []
    passes = 0

    def check(ok: bool, label: str, detail: str = "") -> None:
        nonlocal passes
        if ok:
            passes += 1
            print(f"PASS  {label}")
        else:
            failures.append(label)
            print(f"FAIL  {label}" + (f": {detail}" if detail else ""))

    for p in (TEMPLATE, OUT_PPTX, OUT_PDF, CONTENT, PROGRESS):
        if not p.exists():
            print(f"FAIL  missing {p.relative_to(ROOT)}")
            return 1

    # Template: baseline hash, section titles, brand images.
    m = re.search(r"Template baseline:.*?SHA-256\s+([0-9a-f]{64})", PROGRESS.read_text(encoding="utf-8"))
    check(m is not None and sha256(TEMPLATE) == m.group(1), "template unchanged (SHA-256 = docs/progress.md baseline)",
          "no baseline found" if m is None else f"now {sha256(TEMPLATE)}")

    tpl = read_deck(TEMPLATE)
    brand = {h for s in tpl for h in s.picture_hashes}
    closing = tpl[-1]
    sections = []      # template titles expected in the output, in order
    optional = set()   # titles that may be removed (the cost slide)
    removed_note = removed_blank = False
    for i, s in enumerate(tpl):
        if i == len(tpl) - 1 and not s.has_text:
            continue   # Thank you slide (picture only), checked separately
        if not s.has_text:
            removed_blank = True   # the blank frame slide
            continue
        if s.title.startswith("Note:") and "download" in s.title.lower():
            removed_note = True    # the "Note: Please download" slide
            continue
        sections.append(s.title)
        if "(optional)" in s.title.lower() and "cost" in s.title.lower():
            optional.add(s.title)
    check(removed_note and removed_blank and not closing.has_text and len(optional) == 1,
          "template parsed: note slide, blank frame, picture-only closing slide and the optional cost slide found",
          f"note={removed_note} blank={removed_blank} closing_text={closing.has_text} optional={sorted(optional)}")
    arch = [t for t in sections if t.lower().startswith("architecture")]
    check(len(arch) == 1, "template has one Architecture slide", str(arch))
    if len(arch) != 1:
        print(f"\n{passes} passed, {len(failures)} failed")
        return 1

    out = read_deck(OUT_PPTX)
    titles = [s.title for s in out]

    check(MIN_SLIDES <= len(out) <= MAX_SLIDES, f"{MIN_SLIDES}-{MAX_SLIDES} slides", f"{len(out)} slides")

    # Expected order: template sections (cost optional), six added after Architecture, closing last.
    kept = [t for t in sections if t not in optional or t in titles]
    expected = []
    for t in kept:
        expected.append(t)
        if t == arch[0]:
            expected.extend(ADDED_TITLES)
    check(titles[:-1] == expected, "section titles in the template's order with the 6 added slides after Architecture",
          f"\n      expected {expected}\n      got      {titles[:-1]}")
    last = out[-1]
    check(not last.has_text and set(closing.picture_hashes) <= set(last.picture_hashes) and closing.picture_hashes,
          "last slide is the template's Thank you slide")
    check(not any(t.startswith("Note:") for t in titles) and all(s.has_text for s in out[:-1]),
          "note slide and blank frame slide removed")

    # Content per slide: a picture besides the brand images, or enough text; never too much body.
    thin, wordy = [], []
    for i, s in enumerate(out, 1):
        if s.body_words > MAX_BODY_WORDS:
            wordy.append(f"slide {i} '{s.title}': {s.body_words} words")
        if 1 < i < len(out):
            own_picture = any(h not in brand for h in s.picture_hashes)
            if not own_picture and s.body_words < MIN_TEXT_WORDS:
                thin.append(f"slide {i} '{s.title}': {s.body_words} words, no picture")
    check(not thin, f"every content slide has a picture or >= {MIN_TEXT_WORDS} words", "; ".join(thin))
    check(not wordy, f"no slide has more than {MAX_BODY_WORDS} words of body", "; ".join(wordy))

    # Diagram PNGs used by the deck are newer than their HTML source.
    content = json.loads(CONTENT.read_text(encoding="utf-8"))
    images = []
    for s in content["slides"]:
        images += [s["image"]] if s.get("image") else []
        images += [a["image"] for a in s.get("added", []) if a.get("image")]
    stale = []
    for rel in images:
        png = ROOT / rel
        html = DIAGRAMS / (png.stem + ".html")
        if not png.exists():
            stale.append(f"{rel} missing")
        elif html.exists() and png.stat().st_mtime <= html.stat().st_mtime:
            stale.append(f"{rel} older than {html.relative_to(ROOT)}")
    check(images and not stale, f"{len(images)} deck images exist and are newer than their HTML", "; ".join(stale))
    newest = max(((ROOT / rel).stat().st_mtime for rel in images if (ROOT / rel).exists()), default=0)
    check(OUT_PPTX.stat().st_mtime >= newest, "deck built after its newest image (no stale embedded images)",
          "rerun deck/build_deck.ps1")

    tbd = [f"slide {i} '{s.title}'" for i, s in enumerate(out, 1) if "TBD" in f"{s.title} {s.body} {s.notes}"]
    if args.draft:
        print(f"INFO  TBD allowed (--draft): {len(tbd)} slide(s)")
    else:
        check(not tbd, "no TBD left", "; ".join(tbd))

    pages = pdf_pages(OUT_PDF)
    check(pages == len(out), "PDF page count equals slide count", f"{pages} pages, {len(out)} slides")

    print(f"\n{passes} passed, {len(failures)} failed")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
