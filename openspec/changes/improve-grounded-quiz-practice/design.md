## Context

Approved connected repository learning roadmap at application checkpoint 582e3fa. Beginner English, optional code, Python and TypeScript first, ten-minute suggested sessions and up to ten grounded questions.

## Goals / Non-Goals

Practice teaches repo facts without quota filler or claims of mastery.
Keep the Python/FastAPI/Jinja/HTMX/SQLite application, existing worker and provider adapters. No remote repository downloads, live runtime tracing or automatic implementation.

## Decisions

Extend existing interfaces additively. Read captured source only; version derived views without rewriting snapshots or old artifacts. Validate input references locally. Use transactional migrations with the existing backup mechanism where persistence changes. No source-only observation or passing schema substitutes for runtime or learning acceptance.

The first bounded provider sample omitted the requested follow-up despite a valid free-text answer. Explain-back now uses a small response model and matching JSON schema for correct points, missing reasoning, one question and citations. It reuses the chat queue, time budget, one-repair policy, claim/citation checks and text-message storage; old conversations require no rewrite or migration. Other instructor modes retain their existing schema. Schema validity still cannot prove reasoning correct: the sample also contained an inaccurate quiz distractor, retained and privately flagged rather than rewritten.

## Risks / Trade-offs

Static analysis cannot establish arbitrary runtime behavior; show unsupported cases. Model citations establish locations, not semantic correctness. Preserve earlier L17 acceptance ownership and its limitations.

## Migration Plan

Run focused synthetic checks per behavior, then relevant headless browser gates. Record evidence before checking tasks. Publish only sanitized records. Existing reviews and attempts remain readable.
