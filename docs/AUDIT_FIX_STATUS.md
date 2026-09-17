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

## Independent Ollama checkpoint

- AUD-11: implemented a direct loopback-only Ollama HTTP adapter. Web, CLI and headless review services select it independently of Codex. The default local model is `qwen3.6:27b`; no automatic model substitution or cloud fallback occurs. Cloud-backed model entries are excluded.
- Streaming structured responses, reported usage, cancellation, timeout, incomplete/malformed output and missing-model states have automated coverage.
- A real local synthetic instructor answer succeeded with the installed `qwen3.5:9b-q8_0`, a deliberately unavailable Codex command, valid JSON and a source citation. Operational output remains private.
- **Prerequisite for requested-model acceptance:** the running local server did not list `qwen3.6:27b` during this check. Complete its installation in that server and refresh Settings; then run full review/chat acceptance on that exact model. It has not been represented as verified.
- Next: inline instructor job progress, whole-job usage/deadline handling, and fuller real-provider acceptance.
- Verification: **94 pytest tests passed**, **3 Edge browser scenarios passed**, compile and whitespace checks passed. A settings regression proves local readiness never calls Codex diagnostics. Instructor jobs now expose stream activity and sum reported token usage from repair calls within a shared time budget.

## Inline instructor and review usage checkpoint

- AUD-10: answers now remain in the instructor side panel. The panel displays job stage, elapsed time, reported token usage, cancellation and terminal failures. Closing it keeps the request running and preserves the draft. Conversation refresh uses only the selected saved review; source citations retain local validation and text is inserted safely.
- AUD-12: review usage now includes malformed responses and schema-repair calls, with cumulative streaming totals. Whole-pipeline deadline enforcement remains open.
- Browser acceptance verifies that instructor submission leaves the saved-review URL unchanged and displays the saved answer. All three synthetic Edge scenarios passed. A regression verifies conversations remain readable after the source file is removed.
- Requested-model acceptance remains blocked: the local Ollama server still lists only `qwen3.5:9b-q8_0`, not `qwen3.6:27b`. No substitute is selected automatically.
- Next: stronger quiz explanations, full pipeline timeout handling, and exact-model real acceptance.

Verification: **95 pytest tests passed**, **3 Edge browser scenarios passed**; JavaScript syntax check passed.

## LM Studio and deadline checkpoint

- AUD-11: Architecture Coach now also supports a direct, loopback-only LM Studio provider. It uses LM Studio's OpenAI-compatible `v1/models` and schema-constrained `v1/chat/completions` endpoints without Codex CLI, plugins, tools, web access, or cloud fallback. Settings include a server model ID and default to the detected local Qwen identifier `qwen/qwen3.8-27b`.
- The provider reports a clear readiness state when the local server is not started or the selected model has not been loaded. Its structured output, streaming, token usage, cancellation, timeout, malformed response and missing-model states have automated coverage.
- AUD-02: deterministic quiz feedback now identifies the selected unsupported claim and explains why that kind of claim is unsupported, rather than repeating one generic sentence for every wrong option.
- AUD-12: the total review deadline is checked at every stage and bounds both Archify render attempts and comparison rendering. Reaching it prevents review publication. Regression covers an expired total budget and one shared renderer budget.
- **Prerequisite for real LM Studio acceptance:** start the LM Studio Developer server on `127.0.0.1:1234` and load the Qwen model. At this checkpoint the server was not running, so no private source was sent and no real-provider review is claimed.

## Migration concurrency checkpoint

- AUD-04: startup now takes a separate data-directory migration lock before reading a schema version, creating a backup, or applying a migration. The schema version is re-read after SQLite's write lock is acquired. A simultaneous second launcher waits and then observes the completed upgrade.
- The legacy WAL-safe backup remains intact. A threaded regression verifies that two concurrent startups complete, produce one version-three backup, and leave the database at the current schema version.

## Relationship evidence checkpoint

- AUD-03: confirmed static relationships now preserve their reconciled import citation. The review renders that evidence beside every listed relationship. AI-provided citations are validated against the saved snapshot, while a claimed relationship without matching static support remains inferred and keeps the review limited.
- Architecture output schemas now require relationship citations for new provider responses. Legacy reviews remain readable because relationship evidence is additive. Regression confirms fallback import arrows retain their source line and invalid relationship evidence is visibly unverified.
