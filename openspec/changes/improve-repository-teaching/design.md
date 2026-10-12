## Context

L01–L03 of docs/FUTURE_UPDATES.md are approved. Keep snapshot ownership and immutable saved artifacts. The review already contains lessons, questions and cited source.

## Decisions

Use existing lesson data with bounded excerpts extracted from locally valid saved ranges; never present generated code as captured code. Expose an on-demand Markdown export rendered from saved data without overwriting artifacts. Add metadata with legacy defaults and require it in new structured generation; bump review configuration version. Keep ten questions as the complete-review target. AI semantic correctness still needs acceptance inspection.

## Risks

Older records may omit metadata/evidence; present unavailable examples honestly. Teaching includes proposed explanations and must not imply runtime execution. No provider requests are needed for reading.

## Verification

Synthetic saved records, unavailable live folder/provider, escaped source, export-byte preservation, schema and compatible-model checks. Real-provider and learner-comprehension checks pending.

Evidence: 2/3 — design grounded in inspected source; live generation and learning benefit remain untested.
