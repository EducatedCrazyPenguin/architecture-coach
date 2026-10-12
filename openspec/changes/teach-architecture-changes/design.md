## Context

Semantic comparison already separates file changes from membership/dependency changes. Learning records and plans belong to immutable saved reviews.

## Goals / Non-Goals

Goals: predict before revealing observed changes; cite both snapshots; transfer concepts without ranking designs; record user reports separately. Non-goals: compliance, live-file validation or automatic implementation certification.

## Decisions

Reuse compare_saved_reviews, validate same-project completed records, and read bounded excerpts around the first changed range. Show possible affected callers from each saved graph with inference labels. Concept transfer selects reviews explicitly and draws only matching saved questions/excerpts; missing metadata is an empty state. Persist versioned user follow-through notes referencing a plan and later same-project review. Never mark implementation or tests complete from publication or file differences.

## Risks / Trade-offs

Structural evidence cannot prove runtime impact or behavior correctness. A user report is labelled as such; changed source is an observation, not proof of the intended fix. Bounded excerpts disclose omitted files.

## Migration Plan

Add one owned follow-through table with cascading references, using existing transactional backup migrations.
