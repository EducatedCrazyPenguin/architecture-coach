# Audit reconciliation at the OpenSpec adoption checkpoint

The first-release ledger in `docs/RELEASE_STATUS.json` remains a dated record of its own checks. `docs/AUDIT_FIX_STATUS.md` is a running audit log, not a second live task counter. This table maps the twelve audit findings to current implementation evidence and the one successor change for unfinished acceptance.

| Audit | Current evidence | Remaining owner |
|---|---|---|
| AUD-01 installed resources | `tests/test_installation.py`, source/asset resolution and launcher checks | Clean checkout with spaces: `close-audit-acceptance` 1.1 |
| AUD-02 fallback quiz truth | `tests/test_review.py` and quiz source evidence checks | Real-provider question quality: `close-audit-acceptance` 1.2 |
| AUD-03 unsupported claims | `validate_architecture_snapshot`, `validate_evidence_items`, quality limits | Source-backed relationship acceptance: `close-audit-acceptance` 1.2 |
| AUD-04 WAL backup | `tests/test_migrations.py` including concurrent migration | Closed by passing regression |
| AUD-05 frozen provider settings | `tests/test_app.py` running-job configuration regression | Closed by passing regression |
| AUD-06 quiz draft preservation | Edge browser test and network-failure behavior | Closed by passing browser check |
| AUD-07 cycle witnesses | SCC witness test in `tests/test_analysis.py` | Closed by passing regression |
| AUD-08 typed relationships | semantic comparison regression in `tests/test_history.py` | Closed by passing regression |
| AUD-09 bounded context | source-summary/coverage regressions in `tests/test_review.py` | Large real project acceptance: `close-audit-acceptance` 1.3 |
| AUD-10 instructor side panel | Edge browser test for focus, draft and answer flow | Closed by passing browser check |
| AUD-11 independent local providers | Ollama and LM Studio adapter tests | Real full local review/chat: `close-audit-acceptance` 1.4 |
| AUD-12 progress and failures | fake CLI, streamed usage, timeout/cancel tests | Real provider failure-state check: `close-audit-acceptance` 1.4 |

No item is marked closed here solely because an earlier release ledger says verified. The successor change owns only the remaining acceptance evidence; implementation tasks from the previous audit stay in their historical record.
