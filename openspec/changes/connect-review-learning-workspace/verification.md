# Verification — connect-review-learning-workspace

**Evidence: 2/3 — the listed synthetic behavior is checked; real teaching quality and beginner effectiveness remain separate unfinished acceptance gates.**

Starting checkpoint: `582e3fa`. Tested application checkpoint: `a19163d79b31e4098014bd39d79ac66cf774a437`.

## Completion evidence

N01: Project cards enter the full saved review. The shared header identifies project, saved date, selected instructor provider and asynchronous current-file status. N02: Overview, Map, Follow a feature, Learn, Quiz and Changes share the instructor; narrow-screen keyboard trapping, Escape and focus restoration are browser checked. N03: Expand diagram enters an application map page; original artifact URLs and bytes are retained as named exports. N04: legacy zero-question, missing renderer and limited-coverage states offer deliberate next actions. Saved-page tests use a provider that raises if diagnostics or inference are called.

Sources: [workspace regression cases](../../../tests/test_connected_workspace.py), [browser journeys](../../../browser-tests/learning.spec.ts), [saved analysis/teaching](../../../src/archcoach/learning.py), [review services](../../../src/archcoach/review.py), [local API](../../../src/archcoach/app.py), [persistence](../../../src/archcoach/db.py).

The unfiltered 226-test gate, browser runs and diagnosed failures, strict 16-document validation, role mutation check, offline editable installation and isolated installed start/reuse/exit/restart evidence are recorded once in [the shared release verification](../verify-connected-learning-release/verification.md). That record also distinguishes Windows CI from the bounded sample's teaching defects and unfinished L17/N27 acceptance. No private reports, profiles or real learner responses are committed.

## Limits and next action

Captured dependencies and reading outlines do not establish runtime execution or passing tests. Valid citations do not establish correct teaching. Browser-close saving remains best effort; dynamic calls/configuration and unsupported languages remain qualified. N15/N20 remain awaiting real teaching inspection, and L17/N27 remains open. Keep this change unarchived and keep the tested application checkpoint linked to publication evidence; do not rewrite old snapshot artifacts.
