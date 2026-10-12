## Context

The roadmap has eighteen tasks. OpenSpec task counts measure completion checks, not effort. Current working agreements restrict live inference, rendering, downloads and desktop windows.

## Goals / Non-Goals

Goals: factual teaching fixtures, safe headless checks, reproducible evidence and continuity. Non-goals: claiming educational effectiveness from automated tests, lowering gates, downloading a model or opening the daily app.

## Decisions

Seed isolated synthetic saved reviews and blobs directly. Serve a bounded fake-provider worker app on a verified free port; log its PID/output and stop only its owned process. Headless Edge uses the established Playwright stack and never the user's active browser session. Do not replace required renderer/live gates with mocks; record them separately as pending. Keep learner comprehension acceptance pending a requested session.

## Risks / Trade-offs

Passing a content rubric and browser check does not establish that a real learner understands architecture. Required gates needing explicit resource use remain unfinished until requested. Installed-file checks do not prove shortcut launch.

## Migration Plan

Use synthetic profiles for checks and existing transactional backups for real upgrades, only after required release gates pass.
