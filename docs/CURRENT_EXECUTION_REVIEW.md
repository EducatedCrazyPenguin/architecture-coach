# Current execution review

Audited on 2026-09-16 at commit `3dd57fd5592a12aba97d9b3331ebe457093d73c4`.

The application has a useful foundation, but its current installation and teaching output need correction before treating it as a dependable architecture instructor. Keep the stack and core service boundaries. Prioritise truthful results and a working installed application before adding more features.

This is an audit, not an implementation checkpoint. Application code and registered project data were not changed. All new reproductions used synthetic files and isolated storage. Private audit output is excluded from Git.

## Verification performed

- Current checkout was clean on `main` at the audited commit.
- Windows Python suite: **80 passed**, one dependency deprecation warning.
- Windows Edge Playwright suite: **3 passed**.
- Tested the existing installed environment separately from source-tree tests: Archify, the JavaScript/TypeScript helper, and HTMX were all unavailable at the paths the installed application computes.
- Added disposable probes for fallback quiz accuracy, unsupported AI claims, citation handling, cycle reporting, semantic comparison, settings changes during a review, invalid quiz requests, and SQLite backups with committed data in the write-ahead log.
- An additional Edge interaction reproduced quiz clicks replacing an existing chat draft and moving focus to the chat textarea.
- Did not rerun real paid AI reviews, inspect private projects, revalidate GitHub CI, or change the user's running application. Provider findings below distinguish code inspection from end-to-end verification.

The older `40/40` release ledger describes historical checks. It is not proof that these newer changes satisfy every release guarantee. Do not count a previously verified item as fresh acceptance evidence for the current revision.

## Keep these choices

| Keep | Why it helps | Evidence in the current application |
|---|---|---|
| FastAPI, Jinja, HTMX, ordinary CSS and SQLite | Appropriate complexity for a personal local app; no stack rewrite is needed. | Separate capture, analysis, AI, rendering, storage and presentation modules. |
| Immutable source snapshots and deduplicated blobs | Explanations remain tied to the version actually reviewed. | Capture and chat regressions pass, including changing live files after a review. |
| Review-bound conversations and bounded history | Follow-up answers can use saved evidence without silently switching project versions. | `tests/test_context_and_chat.py`. Improve evidence selection while retaining these boundaries. |
| Shared queue, transaction-based review claims and OS-backed ownership | Prevents routine duplicate reviews and concurrent workers. | Ownership, concurrent enqueue, cancellation and scheduler tests pass. Retain these mechanisms while improving lifecycle edge cases. |
| Separate architecture and critique passes | Keeps describing the system separate from recommending changes. | `ReviewEngine.run`; model/schema validation exists at the boundaries. |
| Application-owned architecture model and renderer adapter | Rendering failures can preserve a useful report, and renderer changes need not rewrite history. | Two-attempt rendering/fallback regressions pass. |
| Semantic history and unchanged-check events | Can avoid invented changes and preserve conversations and progress. | Reuse, source-change and identity regressions pass. Strengthen relationship semantics below. |
| Findings with evidence, smallest change and tradeoffs | The right structure for practical learning without an arbitrary architecture score. | Existing finding model, exports and implementation-task output. |

The directed SVG fallback is a real improvement over the earlier card grid: it has arrows, selection, source membership and incoming/outgoing dependencies. Keep that capability, but fix the underlying facts and the installed renderer path before presenting all diagram arrows as confirmed.

## Prioritised findings and completion checks

All items below remain open. P1 means correctness, reliable operation or data integrity should be addressed first; P2 means a substantial reliability or product improvement.

### AUD-01 · P1 · The installed app cannot resolve its supporting assets

**Reproduced.** The current virtual environment imports `archcoach` from `site-packages`. `Settings.archify_cli` walks two parents up as though the module still lives in `src/archcoach`; the JavaScript helper and HTMX use the same assumption. All three existence checks return false in this environment. Source-tree tests explicitly use `src`, so they do not catch this installation failure.

Locations: `src/archcoach/config.py:54`, `src/archcoach/analyze.py:43`, `src/archcoach/app.py:79`, `Start Architecture Coach.cmd`, `install.cmd`.

**Change:** standardise on the intended editable source-checkout installation, repair the present environment, and fail clearly when required assets are unavailable. If ordinary wheel installation is retained, package and resolve resources deliberately instead of deriving a repository root from `site-packages`.

**Done when:** the normal launcher in a folder with spaces loads local HTMX, performs compiler-based TypeScript analysis, and produces an Archify diagram. Verify using the installed entry point with no `PYTHONPATH=src` override. Preserve the last valid report if a renderer subsequently fails.

### AUD-02 · P1 · Some fallback quiz answers are factually wrong

**Reproduced.** A one-line `value = 1` project produces the question “Which file contains the parsed definition 'No named definition was parsed'?” and claims that this nonexistent definition was found in the source. Distractors include `None of these (3)` and `None of these (4)`. With `a.py` importing `b.py` and `b.py` importing `a.py`, the quiz marks one of those true dependency statements wrong.

Location: `src/archcoach/review.py:127` through `heuristic_quiz`.

**Change:** build questions from explicit supported facts, check distractors against all relevant facts, and explain each option specifically. For a target of ten questions, use distinct supported code examples and concepts; if the snapshot cannot support ten meaningful questions, disclose that limitation rather than pad with fabricated content. Retain grading against the saved review.

**Done when:** fixtures with no definitions, one file, reciprocal imports, unusual test-folder names and a large documentation file have exactly one correct option per question, no filler choices and directly relevant evidence. Review real generated question quality separately from JSON validity.

### AUD-03 · P1 · Unsupported architecture claims can be published as complete

**Reproduced.** A synthetic AI response with a made-up relationship marked `inferred=false`, an out-of-range component citation and nonexistent quiz evidence was accepted. Citation validity became false, but review quality was still `complete` and the successful schedule date advanced. The template also rendered invalid citations as clickable links. Relationship confirmation currently trusts the model's boolean rather than verifying supporting facts.

Locations: `src/archcoach/models.py:43`, `src/archcoach/review.py:213`, `src/archcoach/review.py:571`, `src/archcoach/templates/review.html:4`.

**Change:** give relationships explicit evidence/provenance and locally reconcile confirmed static dependencies with analysis. Treat other claims as inferred unless their support has been validated. Prevent invalid critical evidence from qualifying a report as complete; request bounded repair or retain a clearly limited report. Render invalid evidence as non-link text. Do not confuse a valid line reference with proof that a claim is true.

**Done when:** the synthetic invalid response above cannot advance the successful review date or show unsupported links/edges as confirmed. A valid inferred relationship remains allowed and visibly labelled.

### AUD-04 · P1 · Migration backups can lose committed data

**Reproduced.** Held a version-three database open in WAL mode, committed a marker row, then triggered migration. The live database contained the row; the backup contained zero marker rows. `shutil.copy2` copies the main database without incorporating committed pages still in its write-ahead log.

Location: `src/archcoach/db.py:113`.

**Change:** create a consistent SQLite backup through the database backup API; coordinate schema upgrades so concurrent initialisation does not operate from a stale version check. Preserve historical snapshot bytes.

**Done when:** the backup passes integrity checks and contains all committed projects, messages and quiz progress with an existing connection and uncheckpointed WAL. Include a concurrent-start upgrade regression.

### AUD-05 · P1 · Changing settings changes an already running review

**Reproduced.** Updating the provider through the settings API during the first pass caused one review to observe `codex` for architecture and `ollama` for critique. The UI says settings apply to new jobs, but it mutates the running engine and adapter immediately. The original configuration fingerprint can consequently describe a different configuration from the one actually used. The inverse switch could send later context to a cloud provider after a job began locally.

Locations: `src/archcoach/app.py:391`, `src/archcoach/review.py:431`, `src/archcoach/review.py:493`.

**Change:** freeze effective settings and resolved provider/model per job at a documented boundary. Use that immutable configuration for all passes, fingerprints, provenance and limits. Apply later settings edits to subsequent work.

**Done when:** switching providers/models during a blocked synthetic pass never changes the running job, and the next job uses the new selection. No real source should be sent to either provider for this regression.

### AUD-06 · P2 · Clicking a quiz answer overwrites the chat draft

**Reproduced in Edge.** Started with a draft question; clicking a quiz option changed the textarea to `question-0`, moved keyboard focus there and scrolled toward chat. Quiz cards/forms and suggested chat buttons all use `data-question`, and one generic click listener handles all of them.

Locations: `src/archcoach/static/app.js:49`, `src/archcoach/templates/review.html:45`.

**Change:** scope suggestion handlers to their actual buttons or give quiz identifiers a separate attribute. Keep selection, feedback and follow-up actions distinct. Add failed-request handling so a network failure does not silently discard the user's action.

**Done when:** selecting, submitting and revisiting answers preserves an unsent chat draft and expected keyboard focus on desktop and narrow screens.

### AUD-07 · P2 · Cycle reporting invents an ordered path

**Reproduced.** For edges `a → c`, `c → b`, `b → a`, the analysis reports `a → b → c → a`; every displayed hop is absent. The strongly connected component algorithm identifies the correct group, but alphabetically sorting its members does not produce a valid cycle traversal.

Locations: `src/archcoach/analyze.py:383`, `src/archcoach/review.py:196`.

**Change:** retain the bounded SCC algorithm. Report a mutually dependent group, or extract a real witness cycle with a source-backed edge for every displayed hop. An SCC count should not be called the number of all cycles.

**Done when:** every displayed arrow is present in the resolved graph and cites its import, including groups containing several overlapping cycles.

### AUD-08 · P2 · Semantic comparisons cannot distinguish relationship types

**Reproduced.** Changing a relationship from sending data to reading data between the same components yields no relationship change. Comparison stores only endpoint pairs, and the relationship model has a free-text label without a separate semantic type.

Locations: `src/archcoach/models.py:43`, `src/archcoach/review.py:346`.

**Change:** introduce a stable relationship kind separate from presentation wording; compare kind, endpoints and confirmation category. Keep wording and diagram geometry excluded. Expose dependency and manifest changes in the main review's Changes section, which currently concentrates on component counts.

**Done when:** rewording an import label produces no architecture change, while imports/calls/reads/writes and confirmed/inferred changes are detected consistently in automatic and selected comparisons. Preserve legacy readers.

### AUD-09 · P2 · Large-project context limits are not visible enough

**Code inspection.** `build_source_packets` truncates files and omits later files, then concatenates the raw packets into each final prompt; there is no per-packet summary stage. The source coverage note is saved under artifacts but not shown in the review template or included in the quality decision. Chat selects source using broad architecture anchors rather than the question or cited quiz example, so increasing the packet budget does not guarantee relevant evidence is included.

Locations: `src/archcoach/context.py:51`, `src/archcoach/review.py:479`, `src/archcoach/review.py:571`, `src/archcoach/review.py:640`.

**Change:** distinguish captured, statically parsed and AI-inspected coverage in the UI and export. Implement the planned bounded summary stage or explicitly document a different bounded strategy. Retrieve saved evidence relevant to the question before filling remaining context. Carry omitted coverage into confidence and reuse decisions.

**Done when:** a question about a late-sorting file in a large synthetic snapshot includes its relevant saved lines, and partial inspection is visible without opening internal artifacts. Test oversized files as well as many small files.

### AUD-10 · P2 · Instructor and quiz remain separate experiences

**Confirmed feature gap.** The tutor remains the final report section. Checking an answer returns a stored explanation to the question card; it neither provides a contextual instructor follow-up nor opens a side panel. Quiz persistence overwrites the previous answer, so it cannot yet support a history of misconceptions and later corrections.

Locations: `src/archcoach/templates/review.html`, `src/archcoach/app.py:246`, `src/archcoach/db.py:596`, `docs/FUTURE_UPDATES.md`.

**Change:** implement the proposed right-side instructor panel and narrow-screen drawer. Feed a selected question, chosen answer, correct answer and cited snapshot into an explicit follow-up action. Show the explanation immediately without requiring another AI call; allow deeper questions through the selected provider. Record attempts separately if building revision/library features.

**Done when:** the learner can answer a question, understand each option, inspect its saved code and ask why while keeping the diagram visible. Closing the panel preserves the draft and conversation. Keyboard focus and Escape work. A newer review never silently replaces its context.

### AUD-11 · P2 · Ollama still depends on an installed compatible Codex CLI

**Code inspection; not a new real-provider test.** Both provider modes first require `CodexAdapter.available()`. Ollama is then invoked through Codex's local-provider mode. This is a valid shared-runner design, but does not solve the case “Ollama is installed and Codex CLI is unavailable.” Model auto-selection also needs its resolved choice recorded, rather than fingerprinting only a blank model setting.

Locations: `src/archcoach/ai.py:154`, `src/archcoach/ai.py:212`, `src/archcoach/review.py:31`.

**Change:** if independent local operation is required, add a direct local Ollama adapter behind a small shared provider interface. Keep schema validation, snapshot restrictions, cancellation and usage handling common. Use detected model choices in Settings and report readiness without conflating local availability with account authentication.

**Done when:** an installed local model can review and answer snapshot questions with Codex absent, while Codex mode still uses saved authentication. Switching modes must obey AUD-05. Test a full structured review and chat, not just a one-line connectivity response.

### AUD-12 · P2 · Error and progress information is incomplete across the worker

**Code inspection plus a reproduced API error.** The worker passes chat exceptions to `fail_job` without their structured error code; chat does not forward AI event/usage callbacks into the job. Review token totals omit calls whose output failed validation. The nominal review deadline is checked for AI calls but is not propagated into subsequent rendering/comparison budgets. An invalid JSON body sent to the quiz route returns HTTP 500 instead of a useful client error.

Locations: `src/archcoach/worker.py:75`, `src/archcoach/worker.py:102`, `src/archcoach/review.py:493`, `src/archcoach/review.py:621`, `src/archcoach/app.py:246`.

**Change:** preserve provider error codes through the queue, stream chat activity and real usage, count failed/repair calls when usage is reported, and apply one deadline through every stage. Share request validation between form and API services. Treat unavailable usage as unknown.

**Done when:** fake-provider authentication, quota, malformed output, timeout and cancellation yield distinct job states; repair usage is included; cancellation/deadline prevents publication; malformed quiz JSON returns 422. Verify the worker path, not only adapter unit tests.

## Recommended order

1. **Restore dependable operation:** AUD-01, AUD-04, AUD-05.
2. **Stop incorrect teaching and interactions:** AUD-02, AUD-03, AUD-06, AUD-07, AUD-08.
3. **Finish the learning workflow:** AUD-10, supported by AUD-09 and AUD-11.
4. **Close acceptance gaps:** AUD-12 and regression checks for every item above; rerun real-provider acceptance after the implementations are verified.

These are **12 open work items**, not twelve equal-sized tasks or an estimate of engineering effort. No application fixes were made in this audit. Preserve the passing tests, but extend them to test the actual installed entry point, semantic truth, teaching quality and adverse interactions. Reassess the relevant release-ledger entries against the fixed revision before declaring release acceptance again.
