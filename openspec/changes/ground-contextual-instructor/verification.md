# Verification — ground-contextual-instructor

**Evidence: 2/3 — the listed synthetic behavior is checked; real teaching quality and beginner effectiveness remain separate unfinished acceptance gates.**

Starting checkpoint: `582e3fa`. Tested application checkpoint: `49b80d72b97a69c2dde12847feacf1eb3f1405cd`.

## Completion evidence

N13: source ranges and component, original relationship index, quiz, lesson, walkthrough and saved-change selections are checked against the review before queueing and again before provider execution. Foreign IDs, traversal and out-of-range references fail. N14: validated selected excerpts precede broader packets and survive a crowded context budget; context and history omissions are disclosed. N15: simpler/example/line/deeper actions, optional code and beginner guidance are implemented and synthetic/UI checked, but actual explanation usability awaits L17. N16: narrowly detectable test-result, invented CLI, raw-whitespace and misquoted-source contradictions are rejected through existing bounded repair; hypothetical alternatives remain labelled. Private flags pause practice atomically, preserve history and require explicit resolution. These guards do not prove arbitrary model reasoning correct.

Sources: [workspace regression cases](../../../tests/test_connected_workspace.py), [browser journeys](../../../browser-tests/learning.spec.ts), [saved analysis/teaching](../../../src/archcoach/learning.py), [review services](../../../src/archcoach/review.py), [local API](../../../src/archcoach/app.py), [persistence](../../../src/archcoach/db.py).

The unfiltered 234-test gate, ten-scenario browser run and diagnosed failures, strict 16-document validation, role mutation check, offline editable installation and isolated installed start/reuse/exit/restart evidence are recorded once in [the shared release verification](../verify-connected-learning-release/verification.md). That record also distinguishes Windows CI from the bounded sample's teaching defects and unfinished L17/N27 acceptance. No private reports, profiles or real learner responses are committed.

## Limits and next action

Captured dependencies and reading outlines do not establish runtime execution or passing tests. Valid citations do not establish correct teaching. Browser-close saving remains best effort; dynamic calls/configuration and unsupported languages remain qualified. N15/N20 remain awaiting real teaching inspection, and L17/N27 remains open. Keep this change unarchived and keep the tested application checkpoint linked to publication evidence; do not rewrite old snapshot artifacts.
