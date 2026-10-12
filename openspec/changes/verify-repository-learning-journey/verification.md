# Verification

L16: annotated synthetic Python/mixed-language facts plus non-Git DAZ and ambiguity regressions cover source validity, honest trace limits, unexecuted assertions and alternate-design prompt constraints. The headless part of L17 covers reading → map → recall → explain-back → failures/cancellation → change lesson. It does not establish learner comprehension.

## Shared verification checkpoint (12 October 2026)

**Evidence: 2/3 — implementation and synthetic/headless behavior are directly supported; real-provider teaching quality, learner comprehension and a complete daily-use release are not established.**

Source base: `30a8d1e`, branch `codex/repository-learning`. Tested application commits: `7508309` (saved-source/practice foundations) and `8897258` (web flows and regressions). Verification documents are committed separately; fresh Windows CI must cover the final pushed checkpoint. Private operational evidence stays outside Git.

- Full unfiltered `.venv` pytest: **183 passed, zero skips/deselections** (58.43 seconds), including the real pinned Archify renderer. Synthetic fixtures used a fresh system-temporary directory, `-p no:cacheprovider --tb=line`. One installed Starlette/httpx deprecation warning was emitted; no gate was weakened.
- Full `node node_modules/@playwright/test/cli.js test --global-timeout=240000`: **six passed** (1.1 minutes). Headless Edge used verified-free port 8878, isolated synthetic storage, hidden task-owned servers and fake providers. Exit stopped those servers; no listener remained. No user browser session, clipboard operation or foreground window was used.
- The browser fixture now refuses an occupied port, checks application identity, logs stdout/stderr and PID, uses the local Python environment, and never sends exit to an unowned server following failed startup.
- Strict pinned OpenSpec validation: **9/9 documents passed** (six focused changes, three main specs). `node --check src/archcoach/static/app.js`, `pip check` and `git diff --check` passed. Document validity does not establish application behavior.
- Regression sensitivity: temporarily inverted the invalid-evidence guard; the invalid-citation test failed as expected. Restored source byte-for-byte and reran that test successfully. No mutation remains.
- The initial capture selection failed because fixtures were inside Git-ignored `.test-data`; moving them outside the repository passed without weakening exclusions. A learning browser selector was corrected earlier. The first complete browser gate found a duplicate `Helper` text selector after human main-path labels were added; targeting the component heading fixed it, and the complete rerun passed.

## Installed-source and data boundaries

The supported Windows installation is editable from this checkout. Quiet inspection found Python **3.12.10**, installed package **0.1.0**, the `.venv` launcher, local HTMX asset and the new learning module resolving from this checkout. No Architecture Coach shortcut was found in standard user/public desktop locations; none was created. Quietly refreshed the editable installation with `python -m pip install -e . --no-deps --no-build-isolation --no-index`; it completed successfully without network dependency installation or profile access. These are installed-source/metadata checks, not visible launcher or lifecycle acceptance.

Migration regressions exercise schema 5 → 9, pre-migration SQLite recovery backups, legacy answers and owned-record deletion. The production profile was not opened or migrated for verification. Existing user settings, credentials, snapshots and learner records were not used as fixtures. No real model load, paid inference or target script execution occurred.

## Exact pending actions

- **L17:** request a learner usability session and selected-provider explanation/teach-back check. Observe what the learner can explain (purpose, input/output, validation failure, state ownership, change impact); record confusing points privately. Mock feedback is not live-model acceptance.
- **L18:** verify fresh Windows CI on the pushed checkpoint, then accept the normal daily-use lifecycle without disrupting active work. Quiet installed-source checks are complete; visible launcher/restart acceptance remains pending a separate explicit request. Preserve migration recovery backups on the next normal startup.
- The user explicitly authorized full automated renderer/headless release gates on 12 October; those local gates passed. This approval did not authorize real-model inference, downloads/loads or visible desktop launch.

**Next action:** commit/push the tested feature checkpoint and inspect its Windows CI. Keep L17/L18 unchecked until their remaining acceptance evidence exists; do not merge a finished-release claim into main.
