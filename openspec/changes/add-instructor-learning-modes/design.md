## Context

The existing shared chat queue owns provider selection, bounds, cancellation, history and saved-source citations. Quiz questions already carry expected reasoning and evidence.

## Goals / Non-Goals

Goals: gradual help, explicit source-grounded explain-back rubric, constrained design practice, saved provenance, draft protection. Non-goals: adaptive tutoring, automatic inference, fluency grading or automatic implementation.

## Decisions

Extend ChatRequest with an allowlisted mode and optional saved question ID. Resolve the question server-side and supply its saved latest attempt and locally valid excerpts. Keep mode instructions application-owned and source text untrusted. Store versioned metadata alongside messages in an additive migration with the existing SQLite backup path. Show a provider-free reading hint and revealable stored explanation before deliberate AI requests.

## Risks / Trade-offs

Prompt instructions cannot prove educational correctness. Synthetic checks establish context and failure handling; real comprehension needs a requested learner session. Design answers explicitly permit alternatives and unknowns. The selected provider remains unchanged.

## Migration Plan

Add a nullable/default-empty message context column; old messages remain ordinary chat. Rollback uses the existing pre-migration SQLite backup.
