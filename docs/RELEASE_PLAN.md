# Architecture Coach first-release hardening

This release keeps the existing Python 3.12, FastAPI, Jinja2, HTMX, SQLite,
Codex, and Archify design. Work is divided into 40 tasks across phases A-J.
`docs/RELEASE_STATUS.json` is authoritative and `python tools/release_status.py`
validates it and regenerates the readable checklist.

The release must provide trustworthy source capture, exclusive worker ownership,
cooperative cancellation, deterministic static analysis, evidence-validated
architecture, configuration-aware reuse, bounded Codex execution, hardened local
HTTP routes, resilient rendering, reproducible Windows setup, and end-to-end
acceptance. Existing private projects are used only for local acceptance; their
source, paths, reports, logs, and screenshots must never be committed.

A task is verified only when implementation and its behavioral verification are
recorded. Blocked acceptance remains incomplete. Hosted accounts, automatic
refactoring, GitHub synchronization, native desktop packaging, and additional
diagram families remain deferred.
