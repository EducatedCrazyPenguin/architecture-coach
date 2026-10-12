# Verification

L16: annotated synthetic Python/mixed-language facts plus non-Git DAZ and ambiguity regressions cover source validity, honest trace limits, unexecuted assertions and alternate-design prompt constraints. The headless part of L17 covers reading → map → recall → explain-back → failures/cancellation → change lesson. It does not establish learner comprehension.

## Shared verification checkpoint (12–13 October 2026)

**Evidence: 2/3 — implementation and synthetic/headless behavior are directly supported; real-provider teaching quality, learner comprehension and a complete daily-use release are not established.**

Source base: `30a8d1e`, branch `codex/repository-learning`. Tested application commits: `7508309` (saved-source/practice foundations), `8897258` (web flows and regressions), and `1cd3d3b` (variadic parameter/shadowing regression). Verification documents are committed separately. Fresh [Windows CI](https://github.com/EducatedCrazyPenguin/architecture-coach/actions/runs/38290776237) passed on source commit `1cd3d3b2d37c71c3999ce89831a7802d1c12d5ef`; an earlier run on `a6d2802` also passed. Private operational evidence stays outside Git.

- Full unfiltered `.venv` pytest: **184 passed, zero skips/deselections** (60.80 seconds), including the real pinned Archify renderer. Synthetic fixtures used a fresh system-temporary directory, `-p no:cacheprovider --tb=line`. One installed Starlette/httpx deprecation warning was emitted; no gate was weakened.
- Full `node node_modules/@playwright/test/cli.js test --global-timeout=240000`: **six passed** (1.1 minutes). Headless Edge used verified-free port 8878, isolated synthetic storage, hidden task-owned servers and fake providers. Exit stopped those servers; no listener remained. No user browser session, clipboard operation or foreground window was used.
- The browser fixture now refuses an occupied port, checks application identity, logs stdout/stderr and PID, uses the local Python environment, and never sends exit to an unowned server following failed startup.
- Strict pinned OpenSpec validation: **9/9 documents passed** (six focused changes, three main specs). `node --check src/archcoach/static/app.js`, `pip check` and `git diff --check` passed. Document validity does not establish application behavior.
- Regression sensitivity: temporarily inverted the invalid-evidence guard; the invalid-citation test failed as expected. Restored source byte-for-byte and reran that test successfully. No mutation remains. A final review found omitted variadic parameter names and possible false resolution of a shadowed callable; a new regression failed before the one-line fix, then all 26 learning regressions passed. The full 184-test run includes it.
- The initial capture selection failed because fixtures were inside Git-ignored `.test-data`; moving them outside the repository passed without weakening exclusions. A learning browser selector was corrected earlier. The first complete browser gate found a duplicate `Helper` text selector after human main-path labels were added; targeting the component heading fixed it, and the complete rerun passed.

## Installed-source and data boundaries

The supported Windows installation is editable from this checkout. Quiet inspection found Python **3.12.10**, installed package **0.1.0**, the `.venv` launcher, local HTMX asset and the new learning module resolving from this checkout. No Architecture Coach shortcut was found in standard user/public desktop locations; none was created. Quietly refreshed the editable installation with `python -m pip install -e . --no-deps --no-build-isolation --no-index`; it completed successfully without network dependency installation or profile access. These checks establish the quiet installed-source upgrade, not visible launcher acceptance. The default daily port had no listener; no user service was stopped.

Migration regressions exercise schema 5 → 9, pre-migration SQLite recovery backups, legacy answers and owned-record deletion. The production profile was not opened or migrated for verification. Existing user settings, credentials, snapshots and learner records were not used as fixtures. No real model load, paid inference or target script execution occurred.

## Installed launcher acceptance

L18's required automated and quiet installation checks passed. The actual `.venv/Scripts/archcoach.exe` started with `--no-browser`, without `PYTHONPATH`, using an empty temporary profile on verified-free port 8878. Its new learning route responded; a second launcher returned “already running” without disrupting the owned worker. CSRF-protected exit returned normally, schema 9 contained zero projects/jobs, and the port was released. Hidden process output/PID and the receipt remain local. No persistent service, model request or production-profile migration was performed. Visible shortcut launch stays explicitly pending unless requested, as the roadmap defines.

## Exact pending actions

- **L17:** request a learner usability session and selected-provider explanation/teach-back check. Observe what the learner can explain (purpose, input/output, validation failure, state ownership, change impact); record confusing points privately. Mock feedback is not live-model acceptance.
- **L18:** verified for its automated/quiet completion criteria. Visible normal-launch acceptance remains an explicitly deferred check requiring a separate request; preserve migration recovery backups on the next normal startup. No full educational/daily-use release is claimed while L17 remains open.
- The user explicitly authorized full automated renderer/headless release gates on 12 October; those local gates passed. This approval did not authorize real-model inference, downloads/loads or visible desktop launch.

**Next action:** arrange the separately requested learner/live-provider session for L17; optionally verify visible normal launch when explicitly requested. Keep L17 unchecked and these changes active until that evidence exists; do not merge a finished-release claim into main.
