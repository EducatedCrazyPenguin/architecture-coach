# Design

## Context

The prior audit log spans multiple implementation checkpoints and may read like a live status ledger. All twelve items are mapped in the integration change's `audit-reconciliation.md`.

## Goals / Non-Goals

Finish real acceptance and report exact unavailable prerequisites. Do not backfill specifications for unrelated capabilities.

## Decisions

Use disposable fixtures for public tests. Use a private local log for real-provider output and publish only test names, counts, model IDs, and result states.

## Risks / Trade-offs

Large local models may be unavailable or slow; an unavailable check stays open rather than being replaced by a mocked result.
