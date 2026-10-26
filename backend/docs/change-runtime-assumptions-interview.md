# Runtime assumptions interview (closed; accepted decisions)

Started: 2026-10-26. Closed by user after answer 30. The user directs plan updates and a
frontend-task re-audit now, with a fresh-session handoff; ask again only for a real break
or material implementation ambiguity. No more hypothetical interview rounds.

Consolidated continuation brief: [HANDOFF-stage-settings.md](HANDOFF-stage-settings.md).
Accepted decisions are authorized for planning. Product code has not been changed here;
canonical cross-part architecture/contracts/tasks still need the program-root update.

## User direction

- The user requested one-at-a-time review of embedded assumptions, then ended the interview
  after answer 30 and authorized proceeding with the necessary planning updates.
- Make token caps adjustable across prompt/brief creation and HTML generation, including
  the request and repair paths. User selected A on question 1: app Settings with separate
  defaults per stage. Selected values and controls are recorded below and in the handoff.
- Retain the already approved HIGH thinking for both reference stages; do not ask for that
  approval again. Later answers extend editable thinking/default choices to the other roles.
- The attached usage screenshot reports 6,632 input, 32,298 output and 38,930 total tokens.
  These are different quantities; it does not establish a required output size for every page,
  a model maximum, or how that interface accounts for thinking inside its output figure.
- This request replaces treating a fixed 8k brief trial as the complete proposed solution.
  It does not approve the earlier performance or structural proposals wholesale.
- Expanded user direction with answer 23: independently selectable model at every LLM
  stage, including interview. Default interview = Flash 3.8; dashboard analysis = Argon;
  detailed HTML prompt/brief = Argon; HTML execution, including no-reference = Flash 3.8;
  routine model work = Flash 3.8 LOW. This extends earlier reference-only model-selector
  scope. Analysis and both HTML execution modes now default to HIGH; interview retains
  existing LOW by the closing default. Deterministic work
  remains code, not new LLM calls. "Full details" requires complete relevant design intent,
  component bindings/definitions and constraints within the chosen budgets, with no arbitrary
  prose target; it does not authorize sending source rows, history, credentials or hidden thoughts.

## Verified current behavior

| Stage | Model role | Thinking | Input cap | Output cap (thinking included) | Deadline |
| --- | --- | --- | --- | --- | --- |
| Reference brief / prompt authoring | planner | HIGH | 12,000 | 4,000 | 120 s total |
| Reference HTML, initial | worker | HIGH | 12,000 | 16,000 | 600 s/page shared with repair |
| Reference HTML, repair | worker | HIGH | 24,000 | 16,000 | remaining page deadline |
| HTML without a reference | planner | LOW | 12,000/attempt | 16,000 | 120 s provider request |

- Config code defaults: planner `gemini-4-argon`, worker `gemini-3.8-flash`.
  Model identities are settings; token limits, thinking and stage deadlines are not currently
  exposed through Config/from_env or GET/PUT settings. Effective deployment settings were
  not read in this interview.
- Retained HIGH comparison: both page-1 brief failures returned MAX_TOKENS, 3 answer tokens
  plus 3,997 thinking tokens, before any reference HTML request or publication. This proves
  a brief cap failure in those runs, not a successful HIGH HTML comparison.
- Brief prose has separate ceilings: 12,000 aggregate characters, 8,000 overall characters,
  2,000 characters per slot treatment. Raising output tokens alone leaves these in place.
- Reference-design guidance also targets about 6,000 characters. Dashboard-design guidance
  prescribes light gray/white cards, pastel KPI tiles and a particular content ordering, with
  prohibitions on gradients, emoji and most numbering. These are discretionary style choices
  to review, not evidence that the user selected them for every reference.
  Direct verification after answer 20: prompts/v1/reference_html.md already explicitly gives
  the reference brief/treatment precedence over the default light-card layout. Do not claim
  that reference precedence is absent or ask the user to re-approve that settled mode behavior.
- Input enforcement counts the complete request with an allowance of
  `max(chars/4 estimate, ceil(folded provider count * 1.20) + 512)` for reference stages.
  Images and schema matter; this is not a cap on the user's text alone.
- Brief has no content repair; HTML has one. Transport retry is a separate allowance:
  once on eligible HTTP 429/500/503 before a response, not on MAX_TOKENS or HTTP 504.
- Current HTML is sanitized background composition around fixed native chart/control slots.
  It is not the same output task as coding an entire standalone interactive dashboard.
- The width schema allows 1200-1920 px but prompts recommend 1200 for native-editor placement.
  Measurement caps height at 4000 px and text minimum at 12 px; the spec allows 1-5 pages.
  Background capture normally uses 3x scale, dropping to 2x when designed backgrounds reach
  2 MiB. Theme/font and bundled icon/geography choices impose further creative limits.

Sources: src/dss/config.py; src/dss/api/settings.py; src/dss/harness/llm.py;
src/dss/harness/context.py; src/dss/harness/nodes/reference_brief.py;
src/dss/harness/nodes/designer.py; prompts/v1/reference_html.md;
.blueprint/qa/task-24.11/high-comparison/README.md. Read-only explorer mappings supplement
the direct doc/source inspection. No new live model request or test run in this interview.
Additional mapped sources: skills/dashboard-design.md; skills/reference-design.md;
src/dss/spec/models.py; src/dss/render/design_page.py; src/dss/render/background.py.

Additional upstream mapping (read-only explorer after answer 21): Blueprint currently uses
LOW thinking, 14k input/6k output and one row plus one SQL repair; Context 10k/3k LOW;
Outline proposal 8k/3k LOW, suggest/Other 6k/2k LOW; reference extraction 12k/4096 without an
explicit thinking level; capability extraction 24k/8k LOW. Profile prompts target 6,000 UTF-8
bytes and reduce value details; columns after 40 have name/type only. Under input pressure,
Blueprint may drop observation labels then the observation section. These are unresolved
quality assumptions to explain later, not newly accepted settings or proven failure causes.
Source mappings: src/dss/harness/context.py, nodes/context.py, outline.py, blueprint.py,
reference_extract.py, capability_check.py; src/dss/data/profile.py; spec/references.py,
requirements.py and feasibility.py.

## Decision log (interview closed)

Entries preserve the sequence of decisions. Later answers and closing defaults resolve any
earlier remarks about a question being next/open; do not resume those historical prompts.

1. **Answered A (2026-10-26):** app Settings with independent defaults for each stage.
   Per-build overrides were not selected; editable code/configuration files are not the
   required user-facing adjustment mechanism.
   A visible Settings/API change crosses program interfaces; record the desired behavior here
   and coordinate its contract/frontend planning at the program root before implementation.
2. **Answered A (2026-10-26):** default output cap for each Flash HTML generation/repair call
   is 65,536 tokens including thinking, configurable in Settings. This is an approved planning
   decision; current runtime remains 16,000 until implementation. The current 16,000 is below the
   screenshot's 32,298 output tokens; 32,768 leaves little headroom even before resolving that
   interface's thinking accounting. A cap permits output, not a target or a success guarantee.
   Official Google model documentation checked 2026-10-26 lists Flash 3.8 output limit 65,536:
   https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash . Google's thinking guide
   confirms max_output_tokens includes thinking:
   https://ai.google.dev/gemini-api/docs/thinking#token-limits-and-max_output_tokens .
   This is documentation verification, not a live compatibility test of the app's ADK route.
   Other stage budgets remain open.
3. **Answered A (2026-10-26):** Argon reference-brief output cap defaults to 32,768 tokens,
   including HIGH thinking, adjustable through app Settings. This is an approved planning
   decision, not an implemented change or proof of empirical sufficiency.
   Current runtime cap 4,000 stopped the two retained HIGH briefs at 3 answer
   plus 3,997 thinking tokens. Argon writes the instructions, while Flash writes the HTML.
   The screenshot's supplied prompt was approximately 6k tokens (user estimate); that is not
   an automatic output requirement. Official Argon model page verified 2026-10-26:
   https://ai.google.dev/gemini-api/docs/models/gemini-4-argon lists 65,536 as the normal
   synchronous output ceiling. A larger setting does not require that much generated text.
   The separate prose decision is answered in question 4; the 120 s deadline remains open.
4. **Answered A (2026-10-26):** remove the fixed prose-character ceilings and numeric prose
   target. This covers the 6,000-character guidance, 12,000 aggregate, 8,000 overall and 2,000
   per-slot maxima in skill prose, provider schema and local validation. Ask for sufficient
   concrete detail without repetition within the selected output-token cap.
   Preserve nonempty structured overall/slot fields, valid page/slot ids, exact slot coverage,
   content/asset/security/native-component checks and refusal on actual token truncation.
   Complete downstream input fit remains a separate requirement; no automatic content trimming
   or removal of semantic/security checks is authorized. Approved planning decision only:
   runtime and prompt/schema character caps remain until implementation.
5. **Answered A (2026-10-26):** Flash reference-HTML complete input cap defaults to 131,072
   tokens per request for initial, later-page, repair and revision paths, adjustable through
   this stage's app Settings. Replaces the 12,000 initial / 24,000 repair limits when built.
   Count the full request:
   instructions, brief, components, reference images, schema and any prior HTML/CSS/comments.
   The larger accepted output budgets make draft/revision context materially larger. This is
   headroom, not an empirical guarantee that every request fits or that a model uses the cap.
   Preserve complete-request enforcement, mandatory facts and clear over-budget failure;
   counting allowance/combined provider capacity/overflow behavior remain separate questions.
6. **Answered A (2026-10-26):** Argon reference-brief complete input cap defaults to 131,072
   tokens per call, adjustable in app Settings and applied consistently to first/later-page/
   revision requests. Current runtime still uses 12,000 until implementation.
   This gives the brief writer room to inspect a larger previous HTML page with reference
   images, theme, components, shared CSS and user instructions. Count/enforce complete mandatory input,
   not only user text, without trimming authoritative facts. This is proposed headroom,
   not proof every request fits. No-reference designer caps are not included in this choice.
7. **Answered A (2026-10-26):** retain conservative reference-stage input measurement, with
   the 20% percentage margin adjustable in Advanced Settings. Enforce the larger
   of its complete-request character estimate and provider folded count plus 20% plus 512
   tokens. Instructions/schema/tools are folded into countable text; earlier local measurements
   showed roughly 5% undercount against actual request usage. A provider count of 100,000
   therefore consumes at least 120,512 of the configured allowance, even if its text estimate
   is lower. This is an acceptance bound, not extra generated/billable tokens.
   Keep the 512-token fixed allowance and character-estimate minimum; expose the percentage
   for the reference stages with a 20% default and report measured versus enforced counts
   distinctly. Offline models without counters retain estimates. No runtime change yet.
   Assembly reserve and combined provider context/output capacity remain implementation
   constraints to account for explicitly. Over-budget behavior is question 8.
   No-reference designer settings are a separate scope choice.
8. **Answered A (2026-10-26):** when complete mandatory input exceeds the configured cap,
   stop before generation and show the stage, enforced count and limit; user may change
   Settings and retry. Keep input caps hard: no automatic expansion, summaries, dropped
   requirements or reduced output/meaning. Preserve provider capacity/output checks.
   This is a clean failure/retry policy, not a new persistent paused-run/resume API.
9. **Answered A (2026-10-26):** separate thinking-level selectors for the two reference
   stages in app Settings, initialized to the already approved HIGH defaults,
   offering the selected model's supported levels (LOW/MEDIUM/HIGH for the current models),
   for each reference stage, including repair/later-page/revision requests.
   This asks about editability, not whether to enable HIGH again. Thinking continues sharing
   the configured output allowance; a level does not reserve a fixed number of tokens.
   Other routes, including no-reference LOW, have not been included by inference.
10. **Answered A (2026-10-26):** independent reference-brief and reference-HTML model
   selectors in Settings, defaulting to Argon/Flash respectively. Current planner_model
   setting serves blueprint, no-reference designer and reference_brief; worker_model serves
   reference_html plus other worker nodes. Independent selectors allow a reference-stage
   experiment without changing the other stages' model choices. This does not select
   new model families or non-Gemini providers, nor authorize changing other routes. Model
   availability/capability validation, legacy-setting migration and fallback need explicit
   treatment in the design; automatic fallback is a separate user choice below.
11. **Answered B (2026-10-26), user-specified model:** explicit reference-stage fallback is
   `gemini-3.8-flash`; clearly show actual fallback use. Currently ModelRouter.refresh replaces the
   effective planner with the worker when a successful availability listing omits the selected
   planner; it logs a warning but does not change the stored planner_model. A listing failure
   logs and retains the configured route; it is not proof that the model is unavailable.
   The user's explicit backup choice applies to both independent reference-stage routes.
   When the primary already resolves to Flash 3.8, do not make a duplicate fallback call:
   exhaust only allowed same-model retries, then stop. Never recurse or alternate models.
   Keep primary Settings intact and retain requested versus actual model identities in evidence.
   The two independent selected models and their supported thinking/output/context/image/JSON
   capabilities must be validated; no silent thinking downgrade or cap expansion is implied.
   Scope of other routes' legacy fallback remains separate from this reference-stage decision.
   Exact fallback trigger and shared deadline behavior need the next decisions.
12. **Answered A (2026-10-26):** trigger fallback when selected model is unavailable, overloaded,
   or returns eligible provider/service failures after its allowed transient retries. Treat
   a failed availability listing as unknown, not proven absence. Preserve the selected stage's
   input/output/thinking requirements and mandatory validation; fallback has to support them.
   Content failures (output truncation, invalid brief/HTML or failed layout checks) are not
   fallback triggers; follow their separate repair/failure policy. Fallback preserves
   configured hard caps, validity/publication checks, cancellation and total deadline.
   Whole-stage timeout exhaustion cannot start more work; detailed time allowances are next.
13. **Answered A (2026-10-26):** Argon/reference-brief stage deadline defaults to 600 seconds
   (10 minutes) per page, adjustable in app Settings, including count, generation,
   eligible retry and fallback. Current 120 s; output default will rise from 4,000 to 32,768
   including HIGH thinking. This is a maximum wait,
   not a target or proof that every 32k response will complete. Stage and provider-request
   timers must agree for this route; other ordinary planner/worker timeouts do not change.
   Retry/fallback cannot reset or multiply this stage's total deadline. Cancellation remains
   responsive; retaining an old published version on failure is unchanged.
14. **Answered A (2026-10-26):** Flash/reference-HTML total stage deadline defaults to
   1,200 seconds (20 minutes) per page, adjustable in app Settings. Current runtime 600 seconds
   covers count/generation/transport retry/measurement and one HTML repair. With output
   increasing from 16,000 to 65,536 including HIGH thinking, the selected allowance is
   shared across count, generation, eligible retry, measurement/repair and allowed fallback.
   This is headroom for first generation plus repair, not a
   latency promise or required wait. Later pages each receive their own stage deadline;
   do not turn this into a report-wide clock or a fresh clock per attempt. Cancellation,
   cleanup, atomic publication and other ordinary nodes' deadlines remain unchanged.
15. **Answered A (2026-10-26):** reference-HTML defaults to two automatic validation repairs
   (at most three content generation attempts/page), adjustable in app Settings. Distinct from transport
   retries, fallback and a user's later retry. Current one repair after the first generation
   (two generations/page maximum), then reference failure stops publication. That current
   runtime remains until implementation of the selected two-repair policy.
   Repairs target explicit schema/HTML/slot/measurement errors and retain the latest usable
   draft plus authoritative facts; do not append an unbounded reply history. The selected
   1,200 s/page clock and configured input/output caps bound all attempts together. No
   automatic chart/requirement changes or acceptance of still-invalid HTML. More repair
   chances are not a fidelity or timing guarantee. Brief repair is a separate next question.
16. **Answered A (2026-10-26):** reference-brief defaults to one automatic validation repair
   before Flash HTML starts (two content generations maximum for this page's brief),
   adjustable in Settings. Current runtime has zero; no implementation yet. Give concrete schema/page/slot/
   content validation feedback and preserve reference images, requirements, bindings and
   user instructions. Within the same selected 600 s brief stage and input/output budgets;
   HTML is not called until the brief passes every check. Ordinary provider retries and
   fallback remain separate. Output-token truncation policy is question 17 and is not
   implicitly approved as a content-repair trigger by this question.
17. **Answered A (2026-10-26):** on output-token cutoff/MAX_TOKENS in either reference
   stage, stop and report stage/page/attempt, cap and available usage. Cutoff may happen
   during thinking with no usable answer or midway through JSON/HTML. It differs from a
   completed but invalid answer. Keep earlier published artifacts and let the user
   adjust Settings/retry. Do not automatically consume validation repairs, fall back to another
   model or lower thinking for a deterministic token cutoff. No automatic fresh regeneration
   or continuation is selected. This supersedes treating HTML cutoff as validation repair.
   No partial brief may start HTML and no partial HTML may publish. Missing usage remains
   unknown; preserve safe diagnostics without hidden thought contents. This question concerns
   output cutoff, not the already settled input-overflow policy.
18. **Answered A (2026-10-26):** reference-stage generation-transport defaults to two
   retries (three transport attempts maximum), waiting 1 s then 2 s; count adjustable per
   reference stage in Settings. Current runtime:
   Current one retry after 1 second on HTTP 429/500/503 before any response is yielded;
   no retry on 504, completed invalid content or token cutoff. Retain that eligible-error
   scope and before-any-response boundary when implementing the selected larger count.
   Same selected/effective model and request; model fallback is evaluated only after eligible
   primary failures exhaust this policy. Shared stage deadline bounds all attempts, backoff,
   repairs and fallback. A stream already yielding a response is not restarted automatically.
   This is distinct from two HTML repairs/one brief repair; no extra repair, broader HTTP
   error class, API-key fallback, silent cap/level change or no-reference retry change is implied.
19. **Answered A (2026-10-26):** save a readable Markdown rendering of Argon's brief plus
   its canonical validated JSON per page/version, accessible for inspection/download.
   Current runtime brief is a validated
   PageBrief object serialized as JSON inside Flash's complete request; no standalone readable
   reference-brief Markdown artifact is written by these nodes. Source inspected:
   reference_brief.brief returns PageBrief; designer._page passes brief.model_dump into
   reference_html_context, and that context wraps it with other instructions/images/facts.
   This is an approved planning decision, not an implemented export. This is the Argon brief,
   not a claim to capture Flash's entire effective request. Markdown is a readable rendering;
   canonical structure/slot validation stays intact. No hidden thoughts or secrets in these
   user-visible artifacts. Any file/API/UI exposure must be coordinated at the program root.
20. **Answered A (2026-10-26):** automatic HTML handoff by default, with an app Settings
   option to pause for brief review/edit/approval before that page's HTML request.
   If enabled, apply per-page briefs sequentially: later-page
   briefing depends on page 1's measured width/CSS. Editing concerns design instructions;
   authoritative native bindings/ids, source definitions, required coverage and validations
   remain code-controlled. Edited brief must pass the same validation/input-budget checks.
   Persist exactly which validated brief was used for generation; this is not final fidelity
   approval. A new human gate/API/UI cannot be implemented only in this backend part: record
   the preference here and coordinate contracts/state transitions at the program root.
   Human review wait is outside model-stage clocks: persist the review state rather than
   keeping a model stream alive; recheck candidate freshness/bindings before generation.
21. **Answered yes/A (2026-10-26), explicitly configurable:** include HTML generation
   without a reference in its own app Settings profile.
   Current no-reference designer is a separate single-stage planner route: LOW thinking,
   12k input, 16k output, provider request 120 s, one HTML repair, kit fallback behavior.
   Expose a distinct "HTML without a reference" settings profile for its applicable
   model/thinking/token/time/retry/repair parameters. User: "Yes please, but make it
   configurable". Review numeric/default choices next; do not copy HIGH/Flash/20 minutes
   or change kit fallback by inference.
   A single-stage route has no Argon-brief review gate. Previous no-reference fingerprint
   invariants remain until the user explicitly approves changes to its behavior/defaults.
   Already settled by prior PRD user decision: retain native Data Studio charts/controls;
   HTML owns decoration. This interview does not re-approve the unselected structural proposal.
22. **Answered A (2026-10-26):** no-reference HTML token-budget defaults match the accepted reference-HTML starting
   values (131,072 complete input; 65,536 output including thinking), stored and edited
   independently rather than linked. This question selects
   only the starting token-budget policy, not model, thinking, time or fallback defaults.
   The user's answer explicitly authorizes these no-reference request-budget changes when
   implemented; preserve other no-reference behavior pending subsequent decisions.
23. **Answered B plus wider direction (2026-10-26):** no-reference HTML execution defaults
   to Flash 3.8, independently selectable. Current runtime still uses Argon for both design
   and HTML without a separate brief. The wider user instruction is recorded above: model
   selection at every LLM stage; Flash interview/execution, Argon dashboard analysis/full
   prompt creation, Flash LOW for routine work. Other stage settings remain configurable;
   do not change a model's level/budgets by the name alone or add new provider families.
   Selected-model compatibility with the accepted 65,536 output and thinking/input settings
   must be validated; fallback and other profile defaults remain upcoming choices.
24. **Answered A (2026-10-26):** use Argon-brief -> Flash-execution with or without a
   reference image. Current no-reference runtime is one stage and skips briefing. Argon analyzes
   confirmed requirements/native components and creates a full brief even without an image;
   Flash writes the HTML. Reuse the configured brief-stage profile (Argon HIGH, 131,072 input,
   32,768 output, 600 s, one validation repair) while retaining independently configurable
   no-reference execution settings. This adds a model stage to
   no-reference generation, not just a route-name change; no-reference brief has no invented
   reference image. Reuse inspection/review behavior where enabled; contracts/UI planning
   must explicitly cover this new route. This supersedes the no-reference single-stage
   preservation assumption; no runtime implementation yet.
25. **Answered A (2026-10-26):** HIGH thinking defaults for Argon's dashboard-analysis
   stages, covering reference
   image interpretation plus native chart/metric/data planning (Blueprint). Model choice is
   already Argon for analysis by the user's wider direction; native planning already routes
   to Argon today but requests LOW, while image extraction has no explicit thinking level.
   Each analytical stage remains independently editable. Do not silently classify complex native
   planning as routine Flash LOW. Their existing independent output ceilings are 4096 for
   reference extraction and 6000 for Blueprint; budgets/time must be reviewed next before
   enabling HIGH, rather than reproducing the 4k brief failure elsewhere. These are planning
   decisions only; runtime remains unchanged. The already approved brief HIGH is retained.
26. **Answered A (2026-10-26):** Argon reference interpretation and native
   chart/data planning. Current interpretation 12,000 input / 4096 output; planning 14,000
   input / 6000 output. Both will start with 131,072 input / 32,768 output including
   thinking, matching the selected Argon brief budgets but independently stored/editable per
   stage. This is headroom,
   not proof of sufficiency. Full effective requests, image/schema overhead and the selected
   conservative allowance count; maintain hard-cap/validation/provider-capacity checks.
   Other scope/count/prose/profile-compression limits are not silently removed by larger
   token settings. Analysis deadlines are next; no current runtime budgets changed yet.
27. **Answered A (2026-10-26):** each Argon analysis stage defaults to 600 seconds total
   (10 minutes), independently adjustable in app Settings. Current reference interpretation uses a
   30 s worker provider bound; native planning uses 120 s/planner request, without a
   user-configurable shared analysis-stage clock. The selected clock covers the stage's count,
   generation, eligible retries, validation/repair and fallback; never resets per attempt.
   A stage can plan all pages, so this is per analysis action, not a new full allowance
   per output row/page. Align the actual provider client timeout with this stage profile
   and remaining time; do not alter unrelated upload/profile/query/engine bounds or routine
   30 s worker behavior by inference. Preserve cancellation and no partial publication.
28. **Answered A (2026-10-26):** HIGH thinking for Flash HTML execution without a reference,
   independently editable from reference execution. Current single-stage
   designer requests LOW; after answer 24 this becomes Flash execution after an Argon brief.
   The selected default matches reference HTML's approved execution default. Routine Flash work remains
   LOW by user direction; HTML execution is a separate profile. This level shares the
   selected 65,536 output allowance with generated HTML, and no model name implies a
   reasoning level automatically. Reference execution/Argon HIGH decisions are unchanged.
29. **Answered A (2026-10-26):** no-reference execution operating defaults copy
   reference HTML's selected initial preset of 1,200 s total/page, two validation repairs
   after initial generation, and two eligible pre-response transport retries with 1 s/2 s
   delays; all three controls stored/editable independently in its own profile.
   Current runtime has 120 s/provider request, one repair and one transport retry.
   The selected policy establishes a shared stage clock for the
   no-reference route as well; align actual client and per-attempt remaining deadlines.
   Input/output budgets, Flash model and HIGH thinking are already selected. This choice
   does not silently alter standard-kit fallback or copy other stages' failure policies;
   those are subsequent explicit questions.
30. **Answered A (2026-10-26):** allow automatic no-reference layout fallback when completed generated HTML still fails
   validation after allowed repairs. Current no-reference path may replace a failed design
   with a standard code-owned layout/kit; reference builds retain their strict no-kit rule.
   Use a standard layout for that page, clearly label its use and expose an enable/disable
   switch in the no-reference Settings profile. Standard layout retains every approved
   native component/data definition/coverage check; it is not fake data or model-drawn charts.
   This question covers exhausted validation/layout repair, not silent recovery from hard
   token cutoff/input overflow or cancellation. Those retain the selected stop policy where
   already approved and the closing defaults resolve the unasked scope. Other service/timeout
   failures are not newly authorized fallback triggers by this layout-specific decision.

## Decided by default after the user ended questions

Source: user 2026-10-26, "let's stop the questioning with the hypotheticals now ... proceed
with updating the necessary files including reaudting frontend tasks ... handoff ... another
session for fresh context". These defaults resolve the unasked queue; they are not unanswered
questions to replay in the next session.

- Preserve existing behavior outside accepted changes. Interview stays Flash LOW initially;
  routine model work is Flash LOW as explicitly directed. Unselected stage token/repair/time
  defaults retain current values and become explicit in the settings design where applicable.
- Keep native charts, source truth, validation, security, assets/fonts, canvas bounds, profile
  compression and scope/count limits. Keep existing reference-over-house-style precedence.
  Do not implement the previously unselected structural proposal under this change.
- Use the selected conservative counting and honest hard-cap failure principles for the new
  generation profiles. Do not let automatic standard-layout fallback hide a token cutoff or
  input overflow; the approved automatic fallback concerns exhausted layout validation.
  Preserve other error behavior unless a coherent new profile requires a documented default.
- Show the minimum evidence needed for accepted controls: stage/effective model, selected
  budgets/levels, measured/enforced input counts, available answer/thinking counts, failures
  and actual model/layout fallback. Missing provider values stay unknown. No speculative
  cost dashboard, hidden thought text, raw provider error leakage or extra telemetry project.
- Snapshot effective settings for each generation action; changes affect the next action,
  not an in-flight request/retry. Persist the used settings/brief identity. Human review wait
  is outside model clocks; a resume checks freshness before using current generation settings.
- Keep sampling at existing/provider defaults and avoid unrequested new sliders, dependencies,
  layout redesigns or additional memory/data features. Complete relevant brief intent and
  native bindings must not be silently lost to the old arbitrary brief/projection truncations.
- Revisit only an observed failure or material implementation ambiguity. The original real
  dashboard visual acceptance STOP remains; this request does not waive that future review.

## Open work and boundaries

- The questionnaire is closed. Preserve the 30 answers and the user's wider routing direction;
  apply the documented defaults rather than resuming the question queue.
- Task 24.11 remains blocked. Its reproducible <100 ms feasibility test failure, original
  fidelity checks and visual approval remain unresolved; this interview does not waive them.
- Do not implement the unapproved 8k trial or structural proposal while interviewing.
- Next: fresh program-root architect session applies canonical planning docs/contracts top-down,
  re-audits affected frontend tasks with an independent reviewer, stamps/lints, and writes a
  concrete builder handoff. Do not leave this as a second unreviewed proposal.
