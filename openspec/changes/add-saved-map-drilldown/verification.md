# Verification — add-saved-map-drilldown

**Evidence: 2/3 — the listed synthetic behavior is checked; real teaching quality and beginner effectiveness remain separate unfinished acceptance gates.**

Starting checkpoint: `582e3fa`. Tested application checkpoint: `a19163d79b31e4098014bd39d79ac66cf774a437`.

## Completion evidence

N05: Conservative saved-path roles separate runtime source, tests, tooling, supporting files and unknowns; component type no longer defaults to backend. N06: A 45-file fixture exposes internal imports, limits the drawing to 40 nodes/80 edges, discloses omissions and supports component/search/neighbour scopes. N07: full saved per-file and component import counts require valid line evidence; internal imports and missing coverage explain zeros. N08: keyboard node selection, source-backed edge links, search, fit/reset and neighbour highlighting prepare typed unsent questions. Arrow Enter/Space selection prepares its exact saved import range; the parent validates the sending iframe, review, range and source-component membership. Foreign-window and mismatched-membership messages are rejected in the browser. Dependencies are not taught as execution order.

Sources: [workspace regression cases](../../../tests/test_connected_workspace.py), [browser journeys](../../../browser-tests/learning.spec.ts), [saved analysis/teaching](../../../src/archcoach/learning.py), [review services](../../../src/archcoach/review.py), [local API](../../../src/archcoach/app.py), [persistence](../../../src/archcoach/db.py).

The unfiltered 226-test gate, browser runs and diagnosed failures, strict 16-document validation, role mutation check, offline editable installation and isolated installed start/reuse/exit/restart evidence are recorded once in [the shared release verification](../verify-connected-learning-release/verification.md). That record also distinguishes Windows CI from the bounded sample's teaching defects and unfinished L17/N27 acceptance. No private reports, profiles or real learner responses are committed.

## Limits and next action

Captured dependencies and reading outlines do not establish runtime execution or passing tests. Valid citations do not establish correct teaching. Browser-close saving remains best effort; dynamic calls/configuration and unsupported languages remain qualified. N15/N20 remain awaiting real teaching inspection, and L17/N27 remains open. Keep this change unarchived and keep the tested application checkpoint linked to publication evidence; do not rewrite old snapshot artifacts.
