# Audit fix status

Work refers to the twelve findings in `CURRENT_EXECUTION_REVIEW.md`. The historical first-release ledger remains separate.

## Current checkpoint

Verification on Windows: **82 pytest tests passed** and **3 Edge Playwright scenarios passed**. The new checks cover WAL backup integrity, mid-review provider changes, invalid quiz JSON, and quiz selection preserving chat drafts and focus. Installed resource existence checks passed without a source-path environment override.

- AUD-01: local environment repaired using editable installation. Installed imports now locate Archify, the TypeScript helper and HTMX. Launcher explicitly selects this checkout's source. Full clean-install acceptance remains to be repeated.
- AUD-04: SQLite backup API replaces main-file copying. Regression exercises committed WAL data and backup integrity. Concurrent migration coordination remains open.
- AUD-05: review and chat copy immutable effective settings when work starts. Provider adapter configuration is isolated for both passes. Regression changes provider during architecture and verifies the current review stays on its original provider and subsequent work uses the new one.
- AUD-06: suggestion click handling is scoped to suggestion buttons. Browser regression checks quiz selection preserves an unsent chat draft and radio focus. Network error handling remains open.
- AUD-12: malformed quiz JSON returns 422; worker preserves structured provider exception codes. Chat streaming, usage accounting and whole-review deadline work remain open.

## Next concrete actions

1. Correct fallback quiz facts and distractors (AUD-02), including no-definition and reciprocal-import fixtures.
2. Strengthen evidence/relationship validation and complete-quality rules (AUD-03).
3. Correct cycle witness reporting and relationship semantic types (AUD-07, AUD-08).
4. Finish instructor panel and contextual quiz follow-up (AUD-10).
5. Complete source coverage/retrieval, independent Ollama operation, and remaining lifecycle checks (AUD-09, AUD-11, AUD-12).

No audit item is declared fully closed until its complete acceptance checks pass.

## Teaching and instructor checkpoint

Final verification: **86 pytest tests passed**, **3 Edge browser scenarios passed**, JavaScript syntax and Git whitespace checks passed. Browser acceptance includes quiz follow-up context, draft preservation, Escape/focus restoration, and narrow-screen presentation. Real-provider acceptance for these new schemas remains open.

- AUD-02: fallback no-definition questions no longer invent a definition; reciprocal imports are not used as false distractors; filler options are rejected. General fallback explanations still need stronger per-option reasoning and real-provider question-quality acceptance.
- AUD-03: invalid citations make review quality limited and cannot advance successful schedules; invalid references render as text. Unsupported relationship claims become inferred and produce a visible limitation. Full relationship provenance remains open.
- AUD-07: SCC analysis now extracts an actual cycle witness, with a regression proving every displayed hop exists. Counts describe mutually dependent groups rather than all cycles.
- AUD-08: relationship models have stable semantic kinds; comparisons expose typed additions/removals separately from wording and endpoint-only legacy fields. Regression covers reads changing to writes.
- AUD-09: partial AI context is visible and prevents complete-quality publication; saved-source retrieval prioritises explicitly mentioned files/definitions. Summary packets and more advanced retrieval remain open.
- AUD-10: instructor is now a right-side panel with narrow-screen drawer, close/Escape/focus restoration and draft preservation. Quiz follow-ups carry the question and selected answer into the same review's composer. Chat still redirects to a job page; inline progress and attempt-history/library work remain open.
- AUD-06: quiz requests disable duplicate submissions and preserve selections on network failure.

Desktop and narrow-screen synthetic screenshots were inspected locally and remain excluded from Git.
