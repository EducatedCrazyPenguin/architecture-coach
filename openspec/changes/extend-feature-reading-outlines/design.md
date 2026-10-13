## Context

Approved connected repository learning roadmap at application checkpoint 582e3fa. Beginner English, optional code, Python and TypeScript first, ten-minute suggested sessions and up to ten grounded questions.

## Goals / Non-Goals

Python and TypeScript feature reading remains bounded static evidence rather than a runtime trace.
Keep the Python/FastAPI/Jinja/HTMX/SQLite application, existing worker and provider adapters. No remote repository downloads, live runtime tracing or automatic implementation.

## Decisions

Extend existing interfaces additively. Read captured source only; version derived views without rewriting snapshots or old artifacts. Validate input references locally. Use transactional migrations with the existing backup mechanism where persistence changes. No source-only observation or passing schema substitutes for runtime or learning acceptance.

## Risks / Trade-offs

Static analysis cannot establish arbitrary runtime behavior; show unsupported cases. Model citations establish locations, not semantic correctness. Preserve earlier L17 acceptance ownership and its limitations.

## Migration Plan

Run focused synthetic checks per behavior, then relevant headless browser gates. Record evidence before checking tasks. Publish only sanitized records. Existing reviews and attempts remain readable.
