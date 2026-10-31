# Demo video: spec (release Phase 5)

A ~4-minute screen-capture demo for the AI Builder Cup judges, with no voiceover: on-screen text
carries the story over background music (change 2026-10-31 demo video, user cards). The MP4 stays a
local, git-ignored file the user uploads; the scripts, storyboard and card templates are committed.

## Story

- Takeaway: it interviews you, designs a prototype you can comment on, then builds a real Data
  Studio report in your own account. The architecture (ADK 2.0 graph, the three memories, Cloud
  Run with the local build agent) is mentioned briefly, in text.
- Tone: conversational, first person ("I upload my sales CSV...", "it asks me..."), plain words;
  light jargon only in the architecture segment.
- Opening: the pain. Data Studio is free and powerful, but a good dashboard still takes hours of
  drag-and-drop and design sense. What if you could just talk it through?
- Closing: the GitHub URL (essentials, Links) on the end card; the text says the hosted link is in
  the submission. The hosted URL never appears. The user's name or team is on the end card only
  (the user types it into the storyboard at 5.1's STOP), with the music credit when the track
  needs one.

## Storyboard

Target 4:00, accepted 3:45-4:15. Segment times are targets; the builder may move a boundary by up
to 10 s to fit the footage.

| # | Time | Segment | Footage | Must say or show |
|---|---|---|---|---|
| 1 | 0:00-0:20 | Hook | title card over a montage of finished reports (never d1: its "planned" tags are stale) | the pain, the promise |
| 2 | 0:20-0:40 | Connect | live run: upload samples/ecommerce_sales.csv and the screenshot of a report I like (the reference report, Recording), Recreate | my data plus a dashboard I like; callout: also research mode, BigQuery tables, a CSV in GCS |
| 3 | 0:40-1:05 | Context and outline | live run: Context (the notes box, then the drafted context with its Audience and KPI cards, one edited), Outline (the picks) | it drafts who the dashboard is for and what it must answer, like an analyst would, and I correct it |
| 4 | 1:05-1:35 | Design and prototype | live run: Design (the preset), Blueprint (the table), Prototype (the HTML prototype) | a designer's layout before anything is built |
| 5 | 1:35-1:55 | Edit by comment | live run: click-to-comment on the prototype title with the applied ask, the revised prototype | edit any prototype by clicking it; a built dashboard gets new versions |
| 6 | 1:55-2:05 | Honest refusal | live run: the refused ask as a separate comment, the feasibility refusal, then Discard | what you approve is what gets built |
| 7 | 2:05-2:20 | Trace and cost | live run: activity strip with token counts, the Trace modal (graph nodes, calls, tokens) | every step traced back to its graph node, with its token cost |
| 8 | 2:20-2:45 | Build | live run: Generate recipe, Build in Data Studio, the recipe ops turning ok, the engine's Chrome building the report (gdigrab, sped up, speed labeled), the finished report | a real report, in your own account |
| 9 | 2:45-3:10 | Screenshot recreation | an existing finished build in History (reference screenshot, generated data, prototype), its report as screenshot pans from the engine's Chrome | no data at all? a screenshot alone is enough: it recreates or borrows the style, and synthesizes sample data to match |
| 10 | 3:10-3:45 | Architecture | d5, d4, d8 (deck/img) with callouts | ADK 2.0 graph of LLM and code nodes; harness with three memories (skills, OKF semantic memory instead of RAG, episodic SQLite); Cloud Run plus a build agent on the visitor's machine |
| 11 | 3:45-4:00 | Judge path and end | docs/img/onboarding-4.8-*.png (check code under an opaque box), then the end card | "Set up this computer" once, then build into your own account; GitHub URL; hosted link in the submission; name; music credit |

## Text on screen

- Every segment has captions in a bottom caption bar: at most 2 lines of at most 42 characters, at
  least 40 px at 1080p, white on a dark semi-opaque bar, the diagrams' font stack
  (deck/diagrams/_base.css). Each cue stays on screen at least 2 s and at least 0.33 s per word
  (about 3 words/s); cues never overlap.
- Callouts: a short label (at most 6 words) with a box or arrow in a Google accent (#4285F4,
  #EA4335, #FBBC04, #34A853) on the UI element the caption is about, never covered by the caption
  bar.
- Section title cards (at most 2 s each) at segments 2, 9 and 10; the title card at 1 and the end
  card at 11 are full cards.
- Total caption text: 400-550 words.
- Sped-up footage carries a visible speed label (for example "8x"); cut waits carry a "later"
  marker. Nothing implies a step ran faster than it did.

## Ask texts

- Applied comment (segment 5), on the prototype's title: `Change the title to "<a title>".` Field,
  format and style asks stop at feasibility (AGENTS.md gotcha), so the applied edit is always the
  title form.
- Refused ask (segment 6): a separate prototype comment Data Studio can't build (for example a 3D
  globe of orders); after the refusal is on screen, Discard the batch, then confirm the feasibility
  state isn't stale before Generate recipe (a stale flag makes the recipe `409
  feasibility_blocked`, AGENTS.md gotcha). Never use an outline Other on a built version.

## Storyboard file

`deck/video/storyboard.json` is the single source for the cut: segments (id, title, target start
and end), shots (id, segment, source: `live`, `history`, `image` or `card`; for recorded shots the
raw clip, in and out points and speed, filled in by 5.2), cues (start, end, text), callouts
(start, end, label, box), masks (shot, start, end, box: an opaque rectangle), `credit_name`
and `music_credit`. The user edits caption text there;
`integration/video/check_storyboard.py` checks it against this spec.

## Privacy

Never on screen, in a caption, the SRT or a committed file: a Google account email or avatar, the
hosted URL or its host (`DSS_AGENT_SERVER`), the project number (`GCP_PROJECT_NUMBER`), the GCP
project ID (`GCP_PROJECT_ID`, for example in a BigQuery table name), an API key, an access, check or
job code. Crop it out (the Data Studio header and avatar: keep x>=270, y>=80, AGENTS.md gotcha) or
cover it with an opaque box; a blur is not enough. `check_storyboard.py` reads those values from
.env (parsed, whitespace stripped, never printed) and fails when one occurs in the storyboard or the
SRT (when demo.srt exists); every Connect shot needs a mask over the sources table's `bq_table`
(`project.dataset.table`); Settings is never opened on camera. The frames are checked by eye on a
contact sheet.

## Recording

- Fresh live run on the local app (`./start.sh`, real engine, the engine's Chrome signed in), from
  a new recreate build on samples/ecommerce_sales.csv plus the reference report's screenshot
  (below), with backend 31.1 in (clean titles, grain words). It makes one new report in the user's account; more
  only on a rerun, each listed in the progress entry with its report id.
- The app is recorded by Playwright with the installed Chrome (`channel="chrome"`, a throwaway
  profile, no browser download; its video needs `uv run --project integration playwright install
  ffmpeg`) at a 1920x1080 viewport with `record_video_size` 1920x1080. A 10 s test clip comes first:
  if the UI text isn't legible at 1080p, record the window with ffmpeg gdigrab instead.
- Reference report (change 2026-10-31, user cards): the user's existing report
  https://datastudio.google.com/u/0/reporting/98e6423a-2872-4fdf-a4f9-9b6c570d95be/page/tEnnC is
  the look the live run aims for. 5.2 screenshots its pages from the engine's Chrome (avatar and
  header cropped, Privacy) into deck/video/raw/ (git-ignored) and uploads them as the build's
  reference in Recreate mode; stages are recorded as Recreate mode shows them. What recreate
  can't build from the CSV is decided in the app with the code-built alternatives (never
  synthetic data on this build). The finished report is shown to the user next to the reference
  on a card before the clips count (5.2's STOP).
- One clip per stage, so a failed step reruns only its stage: `--build <id> --from <stage>`
  resumes an existing build. The recorder logs each shot's start and end in its clip with the API
  event that ends it, so the waits can be cut.
- Local mode has no live view (the backend runs dsengine without `--screencast`), so the build
  footage is the engine's headed Chrome window recorded with ffmpeg gdigrab, in front and
  unoccluded, plus the Recipe panel's ops turning ok.
- The finished report tour, for the live build and the History build alike, is screenshot pans
  from the engine's Chrome over CDP (AGENTS.md gotchas on blank report tabs and waits); the avatar
  is cropped.
- The screenshot recreation segment walks an existing finished build in History (no new model
  calls); the user names it at 5.2 if the newest such build isn't the one to show.
- Live model nodes fail nondeterministically (AGENTS.md gotcha): rerun the failed step once per
  new failure; block only on a repeat at the same step. An engine `partial` is rerun once; a second
  `partial` blocks, naming the failed ops (each rerun makes another report).

## Assembly

- `integration/video/make_video.py` builds the cut from the storyboard with ffmpeg: trims,
  speed-ups, cards, captions and callouts (rendered from HTML templates in deck/video/cards/ by
  headless Chrome, as render_diagrams.py does, or by ffmpeg; the builder picks), and the music.
- Output `deck/video/demo.mp4`: 1920x1080, 30 fps, H.264 yuv420p, AAC stereo, `+faststart`;
  captions burned in; `deck/video/demo.srt` with the same cues for closed captions.
- Music: the user's track at `deck/video/music.mp3` (YouTube Studio Audio Library), looped or
  trimmed to length, 2 s fade in, 3 s fade out; the mix is about -16 LUFS integrated with true
  peak at most -1 dBTP.
- Git-ignored: `deck/video/*.mp4`, `deck/video/*.srt`, `deck/video/raw/`, `deck/video/build/`, `deck/video/music.*`.
