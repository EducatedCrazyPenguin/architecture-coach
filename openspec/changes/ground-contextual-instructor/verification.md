# Verification — ground-contextual-instructor

**Evidence: 2/3 — the listed synthetic behavior is checked; real teaching quality and beginner effectiveness remain separate unfinished acceptance gates.**

Starting checkpoint: `582e3fa`. Tested application checkpoint: `49b80d72b97a69c2dde12847feacf1eb3f1405cd`.

## Completion evidence

N13: source ranges and component, original relationship index, quiz, lesson, walkthrough and saved-change selections are checked against the review before queueing and again before provider execution. Foreign IDs, traversal and out-of-range references fail. N14: validated selected excerpts precede broader packets and survive a crowded context budget; context and history omissions are disclosed. N15: simpler/example/line/deeper actions, optional code and beginner guidance are implemented and synthetic/UI checked, but actual explanation usability awaits L17. N16: narrowly detectable test-result, invented CLI, raw-whitespace and misquoted-source contradictions are rejected through existing bounded repair; hypothetical alternatives remain labelled. Private flags pause practice atomically, preserve history and require explicit resolution. These guards do not prove arbitrary model reasoning correct.

Sources: [workspace regression cases](../../../tests/test_connected_workspace.py), [browser journeys](../../../browser-tests/learning.spec.ts), [saved analysis/teaching](../../../src/archcoach/learning.py), [review services](../../../src/archcoach/review.py), [local API](../../../src/archcoach/app.py), [persistence](../../../src/archcoach/db.py).

The unfiltered 234-test gate, ten-scenario browser run and diagnosed failures, strict 16-document validation, role mutation check, offline editable installation and isolated installed start/reuse/exit/restart evidence are recorded once in [the shared release verification](../verify-connected-learning-release/verification.md). That record also distinguishes Windows CI from the bounded sample's teaching defects and unfinished L17/N27 acceptance. No private reports, profiles or real learner responses are committed.

## Teaching-guard correction — 17 October 2026

**Evidence: 2/3 — the source/evidence boundary is checked with synthetic providers and actual headless/installed runtime; real teaching effectiveness remains unverified.**

Red regressions reproduced two errors: matching a saved quotation anywhere in its cited file accepted unrelated line evidence, and Windows CRLF source rejected an otherwise exact multi-line quotation. Saved/captured fenced quotations now match a cited saved range with normalized line endings. Common headings, emphasis and list prefixes no longer bypass the existing narrow claim checks; fenced examples are treated as data, so hypothetical logs do not become alleged observed test results. These checks are not a complete Markdown parser or a semantic truth verifier.

The new browser journey exercises a wrong-range answer through the shared queue, successful bounded repair, repeated invalid output, visible failure without evidence links, retained draft and reload. Existing review bytes and target source are unchanged. The first broader test run exposed an accidental fixture-variable edit; that edit was restored and the attempt-history regression remains enforced.

Checks: **248 pytest cases passed** (89.74 seconds), **11 headless browser scenarios passed** (1.4 minutes), **16 strict OpenSpec documents passed**; the focused learning/API gate passed 75 cases. A quotation-condition mutation failed all four LF/CRLF/formatted-range cases; source was restored byte for byte and all four then passed. The installed editable CLI again passed isolated start/reuse/exit/restart, session and uncertainty persistence, unchanged synthetic source hashes, clean logs and zero inference jobs. No model or daily-use profile was loaded. Publication/CI evidence is recorded in the shared release verification after pushing the tested source.

N15/N20 and L17/N27 remain open; this correction does not replace learner observation or final authorized model inspection.

## Complete-line quotation correction — 22 October 2026

**Evidence: 3/3 — synthetic source/repair regressions and the headless application flow directly exercised this boundary; this does not verify arbitrary model reasoning.**

Five fresh red cases showed that substring matching accepted a truncated return expression, an empty code block and a declaration without its final colon. The latter bypassed the chat repair path despite a valid source location. Saved/captured quotations now require nonempty complete contiguous saved lines. Line endings and an excerpt's common indentation are normalized; relative indentation is preserved. A complete body line can still be displayed without its outer indentation. The shared instructor validator supplies this behavior to normal answers and structured feedback without changing historical answers or extending the one-repair budget.

Checks: **257 unfiltered pytest cases passed** (96.80 seconds), **eleven complete headless browser scenarios passed** (1.5 minutes), and the focused quotation/example/repair cases passed fifteen checks. The browser flow now supplies a truncated declaration with a correct citation and verifies a new repaired answer is saved; repeated malformed output remains failed with the draft retained. A deliberately inverted line comparison caused two of four focused cases to fail; exact source bytes were restored and all four passed. The installed CLI again passed protected start/reuse/exit/restart, retained synthetic learning state and unchanged source hashes, with zero inference jobs and clean logs. Specification validation and exact publication/CI are recorded in the shared release notes.

N15/N20 and L17/N27 remain open. No model, private project or daily profile was used. Normalized complete-line matching is a narrow quotation check, not proof that an explanation or hypothetical example is correct.

## Limits and next action

Captured dependencies and reading outlines do not establish runtime execution or passing tests. Valid citations do not establish correct teaching. Browser-close saving remains best effort; dynamic calls/configuration and unsupported languages remain qualified. N15/N20 remain awaiting real teaching inspection, and L17/N27 remains open. Keep this change unarchived and keep the tested application checkpoint linked to publication evidence; do not rewrite old snapshot artifacts.
