"""Demo video storyboard check (task 5.1, docs/demo-video.md).

    uv run --project integration python integration/video/check_storyboard.py [--storyboard PATH] [--srt PATH]

Checks deck/video/storyboard.json against docs/demo-video.md: the eleven segments, the shots, the
caption cues (Text on screen rules), the callouts, the Connect masks, the end-card name, and that no
private .env value (hosted host, project number, project ID) occurs in the storyboard or, when it
exists, in deck/video/demo.srt. Read-only. Never prints a .env value. Prints one PASS/FAIL line per
check and exits 1 if any fails.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_repo import private_needle, read_env_values  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
STORYBOARD = ROOT / "deck" / "video" / "storyboard.json"
SRT = ROOT / "deck" / "video" / "demo.srt"
SEGMENT_COUNT = 11
TOTAL_RANGE = (225, 255)           # 3:45-4:15
SOURCES = {"live", "history", "image", "card"}
RECORDED = {"live", "history"}
SECTION_CARD_SEGMENTS = {2, 9, 10}  # at most 2 s each
FULL_CARD_SEGMENTS = {1, 11}
SECTION_CARD_MAX = 2.0
CONNECT_SEGMENT = 2
MAX_LINES, MAX_CHARS = 2, 42
MIN_CUE, MIN_PER_WORD = 2.0, 0.33
# Spec says 400-550 words, the plan's Done when 450-650: the check holds both.
WORDS_RANGE = (450, 550)
CALLOUT_MAX_WORDS = 6
ACCENTS = {"#4285F4", "#EA4335", "#FBBC04", "#34A853"}
PRIVATE_NAMES = ["DSS_AGENT_SERVER", "GCP_PROJECT_NUMBER", "GCP_PROJECT_ID"]
EPS = 1e-6


class CheckFailed(Exception):
    pass


def fail_if(problems, ok_note):
    if problems:
        shown = problems[:6] + ([f"... {len(problems) - 6} more"] if len(problems) > 6 else [])
        raise CheckFailed("; ".join(shown))
    return ok_note


def words(text):
    return len(text.split())


def check_segments(doc):
    segs = doc["segments"]
    problems = []
    if [s["id"] for s in segs] != list(range(1, SEGMENT_COUNT + 1)):
        problems.append(f"segment ids are not 1-{SEGMENT_COUNT} in order")
    if segs and segs[0]["start"] != 0:
        problems.append("segment 1 does not start at 0")
    for a, b in zip(segs, segs[1:]):
        if abs(a["end"] - b["start"]) > EPS:
            problems.append(f"gap or overlap between segments {a['id']} and {b['id']}")
    for s in segs:
        if s["end"] <= s["start"]:
            problems.append(f"segment {s['id']} ends before it starts")
    total = segs[-1]["end"] if segs else 0
    if not TOTAL_RANGE[0] <= total <= TOTAL_RANGE[1]:
        problems.append(f"total {total} s outside {TOTAL_RANGE[0]}-{TOTAL_RANGE[1]} s")
    return fail_if(problems, f"{len(segs)} segments, contiguous, total {total} s")


def segment_of(doc, start, end):
    for s in doc["segments"]:
        if s["start"] - EPS <= start and end <= s["end"] + EPS:
            return s["id"]
    return None


def check_shots(doc):
    segs = {s["id"]: s for s in doc["segments"]}
    shots = doc["shots"]
    problems = []
    ids = [sh["id"] for sh in shots]
    if len(ids) != len(set(ids)):
        problems.append("duplicate shot ids")
    for sh in shots:
        seg = segs.get(sh["segment"])
        if sh["source"] not in SOURCES:
            problems.append(f"{sh['id']}: source {sh['source']!r}")
        if seg is None:
            problems.append(f"{sh['id']}: unknown segment {sh['segment']}")
            continue
        if not (seg["start"] - EPS <= sh["start"] < sh["end"] <= seg["end"] + EPS):
            problems.append(f"{sh['id']}: outside segment {seg['id']}")
        if sh["source"] in RECORDED and not (isinstance(sh.get("speed"), (int, float)) and sh["speed"] > 0):
            problems.append(f"{sh['id']}: speed must be a positive number")
    for sid, seg in segs.items():
        own = sorted((sh for sh in shots if sh["segment"] == sid), key=lambda sh: sh["start"])
        if not own:
            problems.append(f"segment {sid} has no shot")
            continue
        edges = [seg["start"]] + [x for sh in own for x in (sh["start"], sh["end"])] + [seg["end"]]
        if any(abs(a - b) > EPS for a, b in zip(edges[0::2], edges[1::2])):
            problems.append(f"segment {sid} shots leave a gap or overlap")
        cards = [sh for sh in own if sh["source"] == "card"]
        if sid in SECTION_CARD_SEGMENTS | FULL_CARD_SEGMENTS and not cards:
            problems.append(f"segment {sid} has no card")
        if sid in SECTION_CARD_SEGMENTS:
            for sh in cards:
                if sh["end"] - sh["start"] > SECTION_CARD_MAX + EPS:
                    problems.append(f"{sh['id']}: section card over {SECTION_CARD_MAX:g} s")
    return fail_if(problems, f"{len(shots)} shots tile every segment; cards in place")


def check_cues(doc):
    cues = doc["cues"]
    problems = []
    seen = set()
    for i, c in enumerate(cues, 1):
        lines = c["text"].split("\n")
        if len(lines) > MAX_LINES:
            problems.append(f"cue {i}: {len(lines)} lines")
        for line in lines:
            if len(line) > MAX_CHARS:
                problems.append(f"cue {i}: line of {len(line)} chars")
            if not line.strip():
                problems.append(f"cue {i}: empty line")
        dur = c["end"] - c["start"]
        need = max(MIN_CUE, MIN_PER_WORD * words(c["text"]))
        if dur + EPS < need:
            problems.append(f"cue {i}: {dur:.2f} s, needs {need:.2f} s")
        seg = segment_of(doc, c["start"], c["end"])
        if seg is None:
            problems.append(f"cue {i}: not inside one segment")
        else:
            seen.add(seg)
    for i, (a, b) in enumerate(zip(cues, cues[1:]), 1):
        if b["start"] + EPS < a["end"]:
            problems.append(f"cues {i} and {i + 1} overlap or are out of order")
    missing = sorted({s["id"] for s in doc["segments"]} - seen)
    if missing:
        problems.append(f"segments without a cue: {missing}")
    total = sum(words(c["text"]) for c in cues)
    if not WORDS_RANGE[0] <= total <= WORDS_RANGE[1]:
        problems.append(f"{total} caption words, outside {WORDS_RANGE[0]}-{WORDS_RANGE[1]}")
    return fail_if(problems, f"{len(cues)} cues, {total} words, timing and lines ok")


def check_callouts(doc):
    frame = doc["frame"]
    end = doc["segments"][-1]["end"]
    problems = []
    for i, c in enumerate(doc["callouts"], 1):
        if words(c["label"]) > CALLOUT_MAX_WORDS:
            problems.append(f"callout {i}: label over {CALLOUT_MAX_WORDS} words")
        if c.get("color", "").upper() not in ACCENTS:
            problems.append(f"callout {i}: color not a Google accent")
        if not 0 <= c["start"] < c["end"] <= end:
            problems.append(f"callout {i}: times outside the video")
        b = c["box"]
        if not (b["w"] > 0 and b["h"] > 0 and b["x"] >= 0 and b["y"] >= 0 and b["x"] + b["w"] <= frame["width"]):
            problems.append(f"callout {i}: box outside the frame")
        if b["y"] + b["h"] > frame["caption_bar_top"]:
            problems.append(f"callout {i}: box under the caption bar")
    return fail_if(problems, f"{len(doc['callouts'])} callouts, labels and boxes ok")


def check_masks(doc):
    shots = {sh["id"]: sh for sh in doc["shots"]}
    problems = []
    for i, m in enumerate(doc["masks"], 1):
        sh = shots.get(m["shot"])
        b = m["box"]
        if sh is None:
            problems.append(f"mask {i}: unknown shot")
            continue
        if not sh["start"] - EPS <= m["start"] < m["end"] <= sh["end"] + EPS:
            problems.append(f"mask {i}: times outside shot {sh['id']}")
        if not (b["w"] > 0 and b["h"] > 0):
            problems.append(f"mask {i}: empty box")
    masked = {m["shot"] for m in doc["masks"]}
    connect = [sh["id"] for sh in doc["shots"] if sh["segment"] == CONNECT_SEGMENT and sh["source"] != "card"]
    for sid in connect:
        if sid not in masked:
            problems.append(f"Connect shot {sid} has no mask")
    if not connect:
        problems.append("no Connect footage shot")
    return fail_if(problems, f"{len(doc['masks'])} masks; every Connect shot masked ({', '.join(connect)})")


def check_credit(doc):
    if not str(doc.get("credit_name") or "").strip():
        raise CheckFailed("credit_name is empty (the user types it at the 5.1 STOP)")
    return "credit_name set"


def check_private(texts):
    values = read_env_values(PRIVATE_NAMES)
    hits, checked, skipped = [], [], []
    for name, value in values.items():
        needle = private_needle(name, value).lower()
        if not needle:
            skipped.append(name)
            continue
        checked.append(name)
        for label, text in texts.items():
            if needle in text.lower():
                hits.append(f".env {name} value in {label}")
    if hits:
        raise CheckFailed("; ".join(hits))
    note = f"not in {', '.join(texts)}: {', '.join(checked) or 'none'}"
    if skipped:
        note += f"; skipped (empty): {', '.join(skipped)}"
    return note


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--storyboard", type=Path, default=STORYBOARD)
    ap.add_argument("--srt", type=Path, default=SRT)
    args = ap.parse_args()

    results = []

    def run(name, fn, *a):
        try:
            results.append((True, name, fn(*a)))
        except CheckFailed as e:
            results.append((False, name, str(e)))
        except Exception as e:   # malformed field: still a FAIL line, never a traceback with data
            results.append((False, name, f"{type(e).__name__} {e}" if isinstance(e, KeyError) else type(e).__name__))

    raw = None
    try:
        raw = args.storyboard.read_text(encoding="utf-8")
        doc = json.loads(raw)
        results.append((True, "parse", f"{args.storyboard.name} is valid JSON"))
    except Exception as e:
        doc = None
        results.append((False, "parse", type(e).__name__))
    if doc is not None:
        run("segments", check_segments, doc)
        run("shots", check_shots, doc)
        run("cues", check_cues, doc)
        run("callouts", check_callouts, doc)
        run("masks", check_masks, doc)
        run("credit", check_credit, doc)
    texts = {args.storyboard.name: raw} if raw is not None else {}
    if args.srt.exists():
        texts[args.srt.name] = args.srt.read_text(encoding="utf-8", errors="replace")
    run("private values", check_private, texts)

    for ok, name, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    failed = sum(not ok for ok, _, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
