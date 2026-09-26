# Verification notes

Checked on Windows on 2026-09-26 against the OpenSpec integration branch. Task completion and demonstrated behavior are separate: strict document validation alone does not establish application behavior.

| Tasks | Evidence |
|---|---|
| 1.1–1.3 | OpenSpec 1.13.2 resolves from the lockfile; generated `.agents/skills/openspec-*` and project context validate. `pnpm spec:check` passes two active changes. A deliberately malformed staged delta fails the real pinned CLI in `tests/test_plans.py`. Windows CI runs strict validation. `pnpm spec:progress` derives counts from checkboxes. `audit-reconciliation.md` maps all twelve earlier findings; the five unfinished acceptance checks have one successor change. |
| 2.1–2.2 | `tests/test_plans.py` exercises a real staged validator, timeout, missing runtime, cancellation, fake provider repair, shared queue priority, immutable draft persistence, and source provenance. Real authenticated Codex returned a valid plan from a disposable fixture in 26 seconds. |
| 2.3–2.5 | Edge browser acceptance previews exact files, approves a plan, then continues through review and comparison. Python tests cover revision, ZIP, CSRF, stale source, conflict, idempotent retry after filesystem publication, blocked unsafe path, and an actual Windows junction. No reviewed source is written before approval. |
| 3.1–3.3 | `tests/test_specs.py` covers main, proposed, archived, malformed, and unsupported documents; bounded assessments with code citations; specification-only edits without fabricated architecture changes; saved instructor context. A legacy snapshot without a spec index remains readable. |
| 4.1 | `python -m pytest -q`: **126 passed**. `pnpm test:browser`: **3 passed** on Edge. `pnpm spec:check`: **2 changes valid**. Real authenticated Codex and local LM Studio `qwen/qwen3.8-27b` each generated a pinned-CLI-validated plan from a disposable project (26s and 117s). The local model result was not substituted for another provider. Private model output, source snapshots, and operational logs stayed outside Git. |

The OpenSpec integration change remains active until publication and remote commit agreement are verified. The separate `close-audit-acceptance` change retains earlier real-project acceptance work, including clean-install and large-project checks; its unchecked tasks are not counted as completed here.
