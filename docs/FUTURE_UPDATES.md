# Future updates: learning architecture through your repositories

Planning checkpoint: **12 October 2026**, application checkout `30a8d1e`.

**Status: implementation checkpoint; release acceptance pending.** The focused OpenSpec changes below own task completion and evidence. The original roadmap remains here as context, not a second status ledger.

| Slice | Authoritative tasks and checks |
|---|---|
| L01–L03 | [Teaching](../openspec/changes/improve-repository-teaching/tasks.md) · [verification](../openspec/changes/improve-repository-teaching/verification.md) |
| L04–L06 | [Walkthroughs](../openspec/changes/add-guided-source-walkthroughs/tasks.md) · [verification](../openspec/changes/add-guided-source-walkthroughs/verification.md) |
| L07–L09 | [Learning library](../openspec/changes/add-local-learning-library/tasks.md) · [verification](../openspec/changes/add-local-learning-library/verification.md) |
| L10–L12 | [Instructor practice](../openspec/changes/add-instructor-learning-modes/tasks.md) · [verification](../openspec/changes/add-instructor-learning-modes/verification.md) |
| L13–L15 | [Learning from changes](../openspec/changes/teach-architecture-changes/tasks.md) · [verification](../openspec/changes/teach-architecture-changes/verification.md) |
| L16–L18 | [Journey acceptance](../openspec/changes/verify-repository-learning-journey/tasks.md) · [verification](../openspec/changes/verify-repository-learning-journey/verification.md) |

Run `pnpm spec:progress` for checked/total/remaining/blocker counts. Task counts are not estimates of effort. Source features are not a verified desktop release.

**Evidence: 2/3 — current implementation and synthetic/headless checks support the learning features; learner comprehension and real-provider teaching quality remain unverified.** Source observations in the original planning section below were directly supported (3/3) at base `30a8d1e`. Its historical baseline test results are recorded evidence; fresh gates are in the linked verification checkpoint.

## Outcome

Help the learner explain what a repository does, trace one feature through its code, identify responsibilities and data ownership, reason about failures and change impact, and justify a small design improvement. A quiz score alone must not stand for architecture understanding.

> 🧠 **From Hindsight memory (Key decisions and rationale)** — The intended learning loop uses immutable repository evidence to teach, answer follow-up questions, and explain later changes. These are historical decisions; current implementation was checked separately below.

Keep the current Python/FastAPI/Jinja/HTMX/SQLite stack, single worker, independent providers, saved snapshots, semantic comparisons, and explicit approval boundary for planning-file writes. Build the teaching experience on these foundations.

## Starting point: preserve these capabilities

| Existing capability | Current evidence | What to preserve |
|---|---|---|
| Captured source, analysis coverage, locally validated citations | [capture](../src/archcoach/capture.py), [analysis](../src/archcoach/analyze.py), [review validation](../src/archcoach/review.py) | Read-only inspection; disclose omissions; do not execute target code |
| Interactive graph, component responsibilities, typed relationships | [diagram adapter](../src/archcoach/diagram.py), [review page](../src/archcoach/templates/review.html) | Real connected diagrams; confirmed imports distinct from inferred runtime relationships |
| Ten MCQs, four choices, per-option explanations, saved latest answers | [models](../src/archcoach/models.py), [quiz endpoint](../src/archcoach/app.py), [answer storage](../src/archcoach/db.py) | Repository-specific questions and immediate cited feedback |
| Instructor side panel, contextual quiz follow-up, inline progress and cancellation | [browser code](../src/archcoach/static/app.js), [browser scenarios](../browser-tests/release.spec.ts) | Same-review conversations, draft preservation, keyboard and narrow-screen behavior |
| Architecture history, semantic comparison, finding-to-OpenSpec plans | [comparison page](../src/archcoach/templates/compare.html), [plan service](../src/archcoach/plans.py) | Separate observed implementation from proposed changes |
| Codex, Ollama, LM Studio, independent Prism/Bonsai | [provider factory](../src/archcoach/ai.py), [Bonsai acceptance](../openspec/changes/archive/2026-10-04-add-bonsai-local-model/verification.md) | Selected provider only; no silent cloud fallback; bounded work |

The latest recorded application baseline is **158 pytest tests and four browser scenarios** in the Bonsai verification record. The prior audit acceptance is [archived](../openspec/changes/archive/2026-10-01-close-audit-acceptance/verification.md). Old unchecked-looking narrative in `AUDIT_FIX_STATUS.md` describes earlier checkpoints, not the current learning backlog. No active OpenSpec change was present at this planning checkpoint.

## Gaps found in the current implementation

| Direct source observation | Learning consequence (inference) | Planned owner |
|---|---|---|
| `review.html` and `report_markdown` render lessons only when the quiz is absent | New reviews can contain lessons without exposing their explanation or exercise | L02 |
| Main path stores component IDs; the review page prints those IDs directly | A beginner sees names without a step-by-step account of input, transformation, output and failures | L01, L04–L06 |
| Python analysis records imports and definition locations, not a resolved runtime call trace | An import graph cannot establish execution order; walkthroughs need additional, qualified evidence | L04 |
| Quiz schema has no concept/difficulty fields; static fallback repeatedly asks about analysis coverage and methodology | Ten structurally valid questions need not teach ten useful repository ideas | L03 |
| `save_quiz_answer` upserts one row per review/question, replacing the previous answer | First attempt, retries and later recall cannot be distinguished | L07 |
| No shared concept revision queue or learning-library screen appears in the inspected routes/templates | Learning remains attached to individual reviews rather than accumulating across repos | L08–L09 |
| Instructor follow-up inserts a question and selected answer into an ordinary chat composer | There is no dedicated hints/teach-back workflow or saved evidence of understanding | L10–L11 |
| Comparison shows component, relationship and file changes | It does not yet turn a change into a guided explanation and prediction exercise | L13 |
| Dashboard provider badge says “Codex” even when the selected adapter supplies local readiness | A learner can misread where reasoning will run | L01 |

These findings establish source behavior and missing modeled flows. They are not a new whole-repository security audit or a claim that all runtime scenarios were checked.

## Learning sequence

Use the same sequence across projects, with concrete examples from each saved review:

1. **Orient:** user purpose, entry points, runtime/framework, source vs tests/config/generated files.
2. **Follow:** input → validation → coordination → domain work → state/external service → output, only where present.
3. **Explain boundaries:** responsibility, interface, dependency direction, cohesion and coupling.
4. **Reason about reliability:** failure paths, data ownership, retries, validation, tests and trust boundaries.
5. **Predict a change:** callers affected, behavior to preserve, smallest improvement, tradeoffs and acceptance checks.
6. **Transfer:** identify the same principle in another repository without assuming the implementations are interchangeable.

Introduce architecture vocabulary when the learner encounters it. Expand terms on first use and offer an actual saved-code example. Do not prescribe microservices, queues, caching, or dependency inversion to a small project without a specific problem. Deployment and scaling discussions must distinguish captured configuration from hypothetical growth scenarios.

The proposed lesson pattern is: **brief explanation → annotated saved-code example → MCQ → explain-back → small optional exercise**. The IES guide recommends spaced learning, worked examples with exercises, graphics with verbal explanations, and explanatory questions; applying those principles here is a design proposal, not evidence this app already improves learning. [IES practice guide](https://ies.ed.gov/ncee/wwc/PracticeGuide/1)

## Ordered delivery

**18 tasks below are the original acceptance scope**; live task state belongs to the linked OpenSpec changes. Counts describe this roadmap only, not effort, elapsed time, or unfinished historical release tasks. Add the focused regression when changing each behavior; phase 6 supplements those checks rather than delaying testing.

### 1. Teach clearly using the review we already have

Suggested change: `improve-repository-teaching`. Dependencies: none.

- **L01 — A useful learning start.** Offer “Start learning this repo,” the next unfinished step, and a beginner-friendly purpose/entry-point summary. Display human component names with technical IDs in expandable detail; identify the actual selected provider. **Completion:** a learner can choose a saved review and identify what it does and where to begin; local mode is labelled correctly; old reviews remain usable.
- **L02 — Teach beside the quiz.** Show useful generated lessons alongside MCQs instead of suppressing them; include them in new Markdown exports. Extract worked examples from validated saved ranges; a comment such as “inspect this file” is not a worked example. Distinguish exact captured code from a proposed example. Preserve legacy lessons and existing artifact bytes; a newly requested export may be generated separately from saved data. **Completion:** a review containing both lessons and questions exposes both; empty or insufficient teaching produces an honest empty state; exported teaching and evidence agree with the selected snapshot.
- **L03 — Improve question substance.** Add versioned concept tags and intended difficulty to new questions; link a question to its teaching example where available. Cover responsibility, flow, dependency meaning, failure handling, tests and constrained tradeoffs when the source permits. Keep ten MCQs as the complete-review target; insufficient evidence must be disclosed rather than filled with trivia. **Completion:** synthetic fixtures have answerable, distinct questions and plausible distractors; explanations justify each option; source-poor fallback is explicitly limited and does not claim complete teaching.

Likely code: `models.py`, critique schema/prompts, `review.py`, review/dashboard templates, `app.js`. Checks: focused review/API tests plus headless reading and export scenarios. Semantic question quality needs a source-by-source rubric; valid JSON alone is insufficient.

**Checkpoint:** understand one component and answer one cited question without needing an instructor to decode the page. No extra provider required.

### 2. Walk through a real feature

Suggested change: `add-guided-source-walkthroughs`. Depends on L01 and L03.

- **L04 — Saved feature-path model.** Select one representative use case initially. Store bounded steps with component/symbol, source range, input/output, branches, and evidence status. Extend deterministic analysis only for supported local constructs; use qualified AI interpretation elsewhere. **Completion:** each displayed step resolves to saved source; branch-dependent or dynamic calls are labelled; missing trace evidence produces an unknown rather than an invented order.
- **L05 — Follow the map and code together.** Previous/next steps highlight the relevant components and relationships in the existing graph, with saved code and explanation beside it. Expose responsibility, callers, dependencies and state ownership through component details. **Completion:** selecting a step opens the matching saved range and graph element; both diagram and textual fallback support keyboard navigation; navigation cannot silently switch reviews.
- **L06 — Show failures and tests on the same path.** Annotate validation, exception/error handling and relevant test assertions where supported. Ask “What happens if this input is invalid?” or “What would break if this boundary changed?” **Completion:** explanations cite the branch/assertion they discuss; a captured test is never represented as executed or passing; unavailable error/test coverage is explicit.

Likely code: analysis/helper, versioned architecture model/schema, source context, review page and diagram presentation. Checks: branching Python, mixed-language and limited DAZ fixtures; headless step/code/graph synchronization. No universal call-graph engine or second diagram dependency.

Use different abstraction levels only when they explain something useful: system surroundings → application/data stores → components → saved code. Do not infer deployment infrastructure. C4 separates these zoom levels and recommends using only useful ones; dynamic views describe a particular interaction and should be selective. Start with the existing graph plus numbered walkthrough steps. [C4 diagrams](https://c4model.com/diagrams), [dynamic views](https://c4model.com/diagrams/dynamic)

**Checkpoint:** the learner can narrate one feature, identify its state boundary, and point to one failure path. This is the first substantial learning release; ship it before building the full library.

### 3. Remember learning across reviews and repos

Suggested change: `add-local-learning-library` (successor to LEARN-002). Depends on L03.

- **L07 — Preserve attempts.** Add append-only quiz attempts, distinguishing first answer, retry, and delayed practice. Keep existing latest-answer views compatible; migrate legacy answers as one known historical attempt without inventing missing history. **Completion:** wrong → correct retains both attempts; duplicate network submissions are idempotent; backup/migration checks preserve existing answers, messages and lessons.
- **L08 — A small revision queue.** Reuse saved questions and explanations in an opt-in short session; prioritize incorrect answers and questions due for later recall. Use a simple documented schedule before an adaptive algorithm. **Completion:** due/wrong ordering is deterministic; repeated scheduling produces no duplicates; revision works with providers off and never captures source or loads a model.
- **L09 — Concept library and honest progress.** Group cited examples, mistakes, corrections and learner notes across projects. Show practiced concepts, recent first-attempt results and what needs another explanation. Keep originating review/date and stale-source warning. **Completion:** every example has its saved origin; a newer review does not overwrite old learning; project/review removal handles owned learning records explicitly without orphaned private excerpts.

Likely code: database migrations, learning queries/routes, templates and quiz submission. Checks: deterministic clock, retries, old schemas, absent source folder and no-provider sessions. Suggested initial concepts: responsibilities, dependencies, flow, state, validation/failures, testing, change impact and tradeoffs. Do not claim mastery from one correct answer or calculate an architecture-health score.

**Checkpoint:** revisit a mistaken answer later and explain the same concept using a second repository.

### 4. Make the instructor practise reasoning with you

Suggested change: `add-instructor-learning-modes`. Depends on L03 and L07; trace-aware prompts also depend on L04.

- **L10 — Progressive help.** Add optional hints → saved-code explanation → full answer, with “simpler” and “deeper” follow-ups. Reuse stored explanations before generating more text. **Completion:** hints do not reveal the answer immediately; full explanation remains available on demand; context includes question, attempt and cited snapshot while preserving an unsent draft.
- **L11 — Explain it back.** Ask for a short explanation in the learner's own words. Return specific correct points, missing reasoning and one next question against an explicit source-backed rubric. **Completion:** feedback tolerates valid wording differences, cites corrections, and can say uncertain; judging code understanding does not become a language-fluency score; cancellation leaves the answer/draft intact.
- **L12 — Constrained design exercises.** Offer one scenario grounded in the repo: swap storage, add a validation rule, handle an unavailable service, or separate a responsibility. State assumptions and allow multiple defensible designs. **Completion:** alternatives explain costs and behavior to preserve; factual MCQs have one defensible answer under stated constraints; open design answers are not rejected merely for differing from the model's preference.

Likely code: tutor context/prompts, versioned interaction records, existing worker, chat routes and side panel. Checks: fake-provider output, misunderstood explanations, missing evidence, timeouts and context limits. Explanation requests use only the selected provider and explicit queue actions; no background inference.

**Checkpoint:** explain why an answer is right and defend one small design decision, instead of memorizing an option.

### 5. Learn from actual evolution

Suggested change: `teach-architecture-changes`. Depends on L04 and L09; improvement links depend on existing plan service.

- **L13 — Turn differences into a lesson.** Pair old/new saved excerpts with the common semantic comparison. Ask the learner to predict affected callers before revealing observed changes and a qualified impact explanation. **Completion:** source-only and wording-only changes do not become invented architecture changes; both snapshots remain identified; identity/coverage uncertainty is visible.
- **L14 — Compare a principle across repos.** Show one concept using two explicitly selected saved reviews, for example how each separates UI from persistence. Explain different goals and constraints. **Completion:** both sides cite their own snapshot; no relationship between unrelated repositories is invented; size/dependency counts do not rank one design as universally better.
- **L15 — Follow an improvement through.** Link a lesson/finding to an approved plan and a later selected review. Distinguish drafted, planning files saved, implementation reported by user, and source changes observed. **Completion:** plan publication alone never marks implementation done; later source evidence supports the claimed change; test outcomes are unknown unless separately supplied and qualified.

Likely code: comparison service/view, saved learning links, plan references and tutor context. Checks: renamed components, same-branch comparison, source-only edits, cross-project citation isolation and conflicting plan outcomes. Repo-level assumptions about scaling, transactions, trust boundaries and observability are discussed only where evidence or an explicitly hypothetical exercise supports them.

**Checkpoint:** describe why a real change matters and what it cost, including a sound decision worth keeping.

### 6. Verify teaching and daily use

Suggested change: `verify-repository-learning-journey`. Depends on the implemented slices above.

- **L16 — Educational regression fixtures.** Maintain a small synthetic Python repo, mixed Python/TypeScript repo and non-Git DAZ example with annotated facts and teaching expectations. **Completion:** checks reject broken citations and invented execution/deployment claims; fixtures include tiny/ambiguous projects and alternate valid designs; correctness rubrics cover content as well as schema.
- **L17 — Observe a complete learning session.** Check orientation → walkthrough → quiz → explain-back → later revision → change lesson. Use headless browser gates, then a user-requested usability session. **Completion:** keyboard/narrow-screen flows preserve focus and drafts; offline revision and provider failures remain useful; record what the learner can explain and where they are confused without claiming an educational effect from screen-load tests.
- **L18 — Ship a verifiable Windows update.** Run locked dependency checks, relevant pytest/Windows CI and headless browser gates; upgrade the daily-use installation and existing shortcut if present. **Completion:** migration recovery and installed files/version/shortcut metadata are checked; private source and learning history are preserved; visible shortcut launch and real-provider/GPU gates stay explicitly pending unless requested.

Use fake providers and isolated synthetic data for ordinary checks. Inspect scripts/server children, verify a free port and service identity, keep any authorized temporary service hidden/logged/bounded, and stop only task-owned processes. Real model loads, inference, rendering, downloads and desktop launches need the user's explicit request under the working agreements. Never weaken a gate to claim completion.

## Acceptance for the learning update

Completion requires evidence for each implemented task, not just an unchecked count reaching zero. The learner should be able to:

- Explain one repository's purpose, entry point and main responsibilities using saved evidence.
- Walk one feature from input to output, including one failure path, and distinguish imports from runtime order.
- Answer the repository MCQs and explain a previously mistaken answer later.
- Use the concept in another repo and justify a small change with constraints and tradeoffs.
- See the next review accurately separate changed architecture from changed source or wording.

The app must preserve target source, historical reviews, conversations and learning records. Code citations verify locations, not the truth of every AI interpretation. User-observed comprehension is the useful acceptance evidence; an inferred improvement in learning is not a measured outcome.

## Earlier backlog continuity

**UX-001 — Persistent instructor panel:** implementation and recorded browser acceptance now cover the side panel, inline job progress/failures/cancellation, saved-review context, draft preservation, `#chat`, close/Escape/focus restoration and narrow-screen behavior. Preserve these in every UI change. New learning-mode accessibility is covered by L10–L11 and L17; this is not a claim of a full accessibility certification.

**LEARN-002 — Personal local learning library:** implemented with synthetic checks; owned by L07–L09. Full learner acceptance remains in L17. It includes saved concepts/examples/mistakes/corrections, cross-project revision, stale-review indicators, and deletion ownership checks. It supports all current selected providers for deliberate explanation requests; provider-free revision uses saved material. Private content stays in application storage; exporting it requires a deliberate user action.

## Defer until the core learning loop works

Do not add more providers, hosted accounts, GitHub sync, a generic course platform, gamified points, a vector database, automatic refactoring, or model-managed implementation. A separate learning document editor and comprehensive call-graph engine are unnecessary for this roadmap. Additional diagram families and live runtime instrumentation remain separate future decisions.

Preserve OpenMAIC as an independent app; this plan changes Architecture Coach only. Read arbitrary external repos from a folder the user has chosen; automatic remote downloading is a separate consent/scope decision.

**Next concrete action:** complete the explicitly pending gates in `verify-repository-learning-journey/verification.md`: real-provider teaching quality and a requested learner usability session (L17). Full local pytest (184 passed), all six headless browser scenarios, strict specs and Windows CI have passed; the quiet installed launcher start/reuse/exit and metadata checks complete L18. Visible normal launch remains explicitly pending unless requested. Do not infer understanding from quiz correctness or merge a fully verified release claim before those checks.

**Not checked during planning:** current installed version/shortcut, fresh automated runtime results, live-provider readiness, or the learner's actual comprehension. No app, browser, model or target repository was launched or modified for this plan.
