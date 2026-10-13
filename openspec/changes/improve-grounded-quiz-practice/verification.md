# Verification — improve-grounded-quiz-practice

**Evidence: 2/3 — the listed synthetic behavior is checked; real teaching quality and beginner effectiveness remain separate unfinished acceptance gates.**

Starting checkpoint: `582e3fa`. Tested application checkpoint: `49b80d72b97a69c2dde12847feacf1eb3f1405cd`.

## Completion evidence

N17: saved lessons present an objective, explanation, cited excerpt, relevance and self-check; generated illustrations are separate. File size alone no longer creates a placeholder lesson. N18: schemas, generation, validation, exports and screens permit zero to ten distinct questions. A one-function fixture supports one question; a constant-only fixture supports none. Historical questions and answer order are unchanged. N19: one visible question, saved hint/source/reveal, ordinary offline feedback and explicit Not sure preserve first attempts, retries and recall. Reload preserves the displayed question. N20: optional explain-back/design jobs retain selection, draft and history, with an explicit correct-points/missing-reasoning/next-step rubric and no English or mastery score. Explain-back now requires three bounded fields and citations; incomplete or bundled questions receive at most one repair, then an explicit failed answer. The browser checks the displayed next question and preserves failure/cancellation drafts. The first real sample exposed inaccurate distractor reasoning and omitted follow-up, so final model feedback quality still awaits L17.

Sources: [workspace regression cases](../../../tests/test_connected_workspace.py), [browser journeys](../../../browser-tests/learning.spec.ts), [saved analysis/teaching](../../../src/archcoach/learning.py), [review services](../../../src/archcoach/review.py), [local API](../../../src/archcoach/app.py), [persistence](../../../src/archcoach/db.py).

The unfiltered 234-test gate, ten-scenario browser run and diagnosed failures, strict 16-document validation, role mutation check, offline editable installation and isolated installed start/reuse/exit/restart evidence are recorded once in [the shared release verification](../verify-connected-learning-release/verification.md). That record also distinguishes Windows CI from the bounded sample's teaching defects and unfinished L17/N27 acceptance. No private reports, profiles or real learner responses are committed.

## Limits and next action

Captured dependencies and reading outlines do not establish runtime execution or passing tests. Valid citations do not establish correct teaching. Browser-close saving remains best effort; dynamic calls/configuration and unsupported languages remain qualified. N15/N20 remain awaiting real teaching inspection, and L17/N27 remains open. Keep this change unarchived and keep the tested application checkpoint linked to publication evidence; do not rewrite old snapshot artifacts.
