## Context

L01–L03 of docs/FUTURE_UPDATES.md are approved. Keep snapshot ownership and immutable saved artifacts. The review already contains lessons, questions and cited source.

## Decisions

Use existing lesson data with bounded excerpts extracted from locally valid saved ranges; never present generated code as captured code. Expose an on-demand Markdown export rendered from saved data without overwriting artifacts. Add metadata with legacy defaults and require it in new structured generation; bump review configuration version. Keep ten questions as the complete-review target. AI semantic correctness still needs acceptance inspection.

The real teaching check found nine correct answers at the same position. Balance only freshly generated AI quizzes during critique validation: rank question IDs by a stable hash, assign balanced positions, and rotate each option/explanation pair together. Do not reorder questions or rewrite saved reviews. Reject suspected positional wording through the existing bounded repair path; request self-contained option explanations in the prompt. The wording guard is conservative: ambiguous phrases can require a rephrasing, and it does not prove semantic correctness. Include the ordering policy version in review configuration so the new behavior cannot reuse an older quiz. This fixes presentation bias, not model reasoning.

## Risks

The resumed local sample corrected import/call and restart advice, but its lessons still called an unexecuted test proof and used persistence language for temporary state. Tighten the common critique guidance for tests, durability and recommended interfaces, covering self-check answers as well as lesson text. Prompt construction tests verify delivery of this guidance; they cannot establish model obedience. Keep L17 open and record the sampled limitations rather than presenting valid citations as semantic acceptance.

Older records may omit metadata/evidence; present unavailable examples honestly. Teaching includes proposed explanations and must not imply runtime execution. No provider requests are needed for reading.

## Verification

Synthetic saved records, unavailable live folder/provider, escaped source, export-byte preservation, schema and compatible-model checks. Real-provider and learner-comprehension checks pending.

Evidence: 2/3 — design grounded in inspected source; live generation and learning benefit remain untested.
