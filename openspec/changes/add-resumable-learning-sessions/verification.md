# Verification — add-resumable-learning-sessions

**Evidence: 2/3 — the listed synthetic behavior is checked; real teaching quality and beginner effectiveness remain separate unfinished acceptance gates.**

Starting checkpoint: `582e3fa`. Tested application checkpoint: `49b80d72b97a69c2dde12847feacf1eb3f1405cd`.

## Completion evidence

N21: transactional schema 10 adds per-review session state, uncertainty outcomes and private issues. Suggested six-step sessions have no timer/lock; drafts, mode/context, selected file/step, question position and next step survive reopening. Normal navigation/Exit waits for saves; browser-close keepalive is best effort. N22: My learning deterministically offers unfinished session, due recall, mistakes/uncertainty and an unpractised saved concept with reasons, without a provider. N23: nine glossary concepts pair general definitions with separate saved evidence; unsupported advanced topics require explicit hypothetical exercise. N24: existing prediction, tradeoff, approval-plan and later-change services remain connected; planning publication and source edits never establish implementation/test success. Strengths remain beside suggestions.

Sources: [workspace regression cases](../../../tests/test_connected_workspace.py), [browser journeys](../../../browser-tests/learning.spec.ts), [saved analysis/teaching](../../../src/archcoach/learning.py), [review services](../../../src/archcoach/review.py), [local API](../../../src/archcoach/app.py), [persistence](../../../src/archcoach/db.py).

The unfiltered 234-test gate, ten-scenario browser run and diagnosed failures, strict 16-document validation, role mutation check, offline editable installation and isolated installed start/reuse/exit/restart evidence are recorded once in [the shared release verification](../verify-connected-learning-release/verification.md). That record also distinguishes Windows CI from the bounded sample's teaching defects and unfinished L17/N27 acceptance. No private reports, profiles or real learner responses are committed.

## Limits and next action

Captured dependencies and reading outlines do not establish runtime execution or passing tests. Valid citations do not establish correct teaching. Browser-close saving remains best effort; dynamic calls/configuration and unsupported languages remain qualified. N15/N20 remain awaiting real teaching inspection, and L17/N27 remains open. Keep this change unarchived and keep the tested application checkpoint linked to publication evidence; do not rewrite old snapshot artifacts.
