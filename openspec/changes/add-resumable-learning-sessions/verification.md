# Verification — add-resumable-learning-sessions

**Evidence: 2/3 — the listed synthetic behavior is checked; real teaching quality and beginner effectiveness remain separate unfinished acceptance gates.**

Starting checkpoint: `582e3fa`. Tested application checkpoint: `49b80d72b97a69c2dde12847feacf1eb3f1405cd`.

## Completion evidence

N21: transactional schema 10 adds per-review session state, uncertainty outcomes and private issues. Suggested six-step sessions have no timer/lock; drafts, mode/context, selected file/step, question position and next step survive reopening. Normal navigation/Exit waits for saves; browser-close keepalive is best effort. N22: My learning deterministically offers unfinished session, due recall, mistakes/uncertainty and an unpractised saved concept with reasons, without a provider. N23: nine glossary concepts pair general definitions with separate saved evidence; unsupported advanced topics require explicit hypothetical exercise. N24: existing prediction, tradeoff, approval-plan and later-change services remain connected; planning publication and source edits never establish implementation/test success. Strengths remain beside suggestions.

Sources: [workspace regression cases](../../../tests/test_connected_workspace.py), [browser journeys](../../../browser-tests/learning.spec.ts), [saved analysis/teaching](../../../src/archcoach/learning.py), [review services](../../../src/archcoach/review.py), [local API](../../../src/archcoach/app.py), [persistence](../../../src/archcoach/db.py).

The unfiltered 234-test gate, ten-scenario browser run and diagnosed failures, strict 16-document validation, role mutation check, offline editable installation and isolated installed start/reuse/exit/restart evidence are recorded once in [the shared release verification](../verify-connected-learning-release/verification.md). That record also distinguishes Windows CI from the bounded sample's teaching defects and unfinished L17/N27 acceptance. No private reports, profiles or real learner responses are committed.

## Reopened draft-persistence follow-up — 17 October 2026

**Evidence: 2/3 — API reproduction and an isolated patched browser flow passed; the complete browser gate failed, so the follow-up is not verified or published as application code.**

Two API regressions reproduced unrelated draft updates returning 422 when saved position metadata no longer resolves. The prepared correction validates position fields when explicitly changed, preserves older metadata during unrelated updates, and shares the normal draft payload with the page-close handler instead of resending stale selections and unrelated session state. Three boundary cases cover unavailable files, changed step counts and old quiz positions; explicit invalid updates still fail. Removing the new outline-update condition reproduced both older-outline failures; source was restored exactly and all three cases then passed.

The patched tree passed **251 pytest cases** (82.20 seconds), strict validation of sixteen documents and the isolated stale-context browser scenario (3.4 seconds). Its full browser run passed ten scenarios but failed the close-save persistence assertion: the final draft was sent while stored text remained the earlier draft. A later two-scenario diagnostic stalled in the preceding instructor scenario and was stopped. Earlier attempts also stalled while waiting for synthetic page-close responses. The task-owned servers logged clean shutdown; the failure trace archive could not be read. The exact cause of the isolated-versus-full-run difference remains unconfirmed; queued autosave ordering is a hypothesis, not an established diagnosis. No assertion, timeout or required scenario was removed to claim success.

N21 is reopened. The unpublished correction and regression changes are preserved in the ignored local patch `.acceptance-data/pending-draft-persistence.patch` (SHA-256 `e99d4378776dc7315f93c983fce60aa73af92aa824270541c30a481d99f91bc3`); its reapply check passed. The checkout's application/test bytes were restored to the fully tested `7ee5adf` checkpoint, keeping the editable installation off the pending patch. The patch contains application/synthetic-test changes only, with no private project source. It is local operational continuity, not another task ledger.

**Next:** check and apply the preserved patch locally, inspect normal autosave ordering and actual keepalive response/state during the complete context, then run the focused and full headless gates without weakening the persistence assertions. After two failures, diagnose and report before another retry. Do not repeat the browser campaign blindly or load a model. Publish the correction and recheck N21 only after its full behavior passes. Normal navigation/Exit waits for saves; browser-close/crash persistence remains best effort.

## Limits and next action

Captured dependencies and reading outlines do not establish runtime execution or passing tests. Valid citations do not establish correct teaching. Browser-close saving remains best effort; dynamic calls/configuration and unsupported languages remain qualified. N15/N20 remain awaiting real teaching inspection, and L17/N27 remains open. Keep this change unarchived and keep the tested application checkpoint linked to publication evidence; do not rewrite old snapshot artifacts.
