## Decisions
Keep latest answers for existing callers; append attempts and update their simple due schedule in one transaction. A request key is bound to its exact review/question/selection/mode. Import legacy latest answers as one historical attempt, without invented earlier history. Correct same-day retries do not increase recall streak. Use saved review data for concept grouping and revision; never load models or recapture files. Notes and revision state follow review deletion through foreign-key ownership.
## Verification
Migration/backup, retries, conflicts, fixed clocks, no-provider pages and deletion ownership with synthetic records. No private production database migration during development.
Evidence: 2/3 — behavior will be checked on fixtures; daily installation pending.
