# Verification

## 1.1 Clean Windows installation and launch

- Tested commit: `672ab8e621e329d76f024644b4c35c22b8f537a1`.
- Cloned the commit to a disposable checkout whose folder name contains spaces. `install.cmd` exited 0 after installing the locked Python and Node dependencies; `archcoach doctor` found Python assets, Archify, Git, Node, and a compatible authenticated Codex CLI. A first sandboxed attempt correctly exited 1 when network access prevented pip from fetching pinned packages.
- Launched `Start Architecture Coach.cmd` against isolated local data. `/api/health` and the dashboard responded; `app.css`, `settings.css`, `compare.css`, `app.js`, and bundled `htmx.min.js` each returned 200. The Exit form returned 200 and the launcher process exited.
- In the same clean checkout, `python -m pytest tests/test_migrations.py -q` passed: **5 tests** covering legacy preservation, backup integrity, concurrent migration, and related schema behavior.
- All install and runtime files remain in ignored disposable acceptance data; no target project was changed.

## 1.2 Real-provider source claims

- Ran an authenticated Codex review of a disposable four-file record-creation fixture. The saved review was `complete` with **3 components, 4 relationships, 10 quiz questions, and no AI warnings**.
- Inspected every quiz question, selected correct option, explanation, and source reference against the captured fixture. All ten answers match the source. The two confirmed import relationships cite the import lines; two call relationships cite the call sites and are labelled inferred. Every displayed citation was locally validated. No factual defect was reproduced, so no defect test was added.
- The first attempt in the restricted execution sandbox produced a visibly limited static review because Codex could not write its own state database. Running the same disposable review with normal CLI permissions yielded the complete result above; the fallback did not masquerade as full quality.
- The fixture, source-derived review, and provider output are stored only under ignored private acceptance data.

## 1.3 Bounded large-project review and instructor retrieval

- Ran a real authenticated Codex review of a disposable **32-file** Python fixture, with the acceptance run deliberately limited to two 6,000-character source packets. It captured all 32 files, included 9 in the AI packets, omitted 23, and used **2 validated source summaries** before the final review passes. The report was labelled `limited`, including the omission and one inferred relationship warning.
- A GET of the saved review page returned 200 and visibly displayed the 23-file omission, two-summary note, and limited status. The source-context note belongs to the immutable review artifacts; the snapshot coverage separately records parser/capture coverage. The saved Markdown report was present.
- The instructor answered a question about an omitted module from the saved snapshot, returned the expected marker, and cited its exact saved line with `valid: true`. The source fixture had already gone out of scope before the page check, so the page did not rely on live project files.
- The real-provider output and fixture remain private under ignored acceptance data.

## 1.4 Full local-provider review and chat

- Started the local LM Studio server and confirmed the selected model ID `qwen/qwen3.8-27b` was ready. A fresh disposable one-file Python fixture went through the full architecture, critique, rendering, and saved-review publication flow with the **LM Studio adapter only**.
- The report was `complete`, had **10 quiz questions**, and had **no AI warnings**. The instructor then answered a question about whitespace handling from that saved review; its answer matched the captured code and carried three locally valid citations.
- The exact requested Ollama model `qwen3.6:27b` was not substituted. Its local server/model readiness remains a separate prerequisite: an `ollama list` check on this machine timed out while the installed Ollama app was starting an update. This does not affect the verified LM Studio path.
- Source and full model output remain in ignored private acceptance data.

## 1.5 Provider failure states and limits

- The clean-install `doctor` check confirmed a compatible, authenticated real Codex CLI; the real Codex and LM Studio acceptance reviews above completed without usage-limit failures. No actual account quota exhaustion was induced.
- Ran `python -m pytest -q tests/test_ai_adapter.py tests/test_jobs.py tests/test_review.py tests/test_context_and_chat.py tests/test_lmstudio.py tests/test_ollama.py`: **44 passed** on Windows. Controlled fake-CLI failures classified authentication, usage exhaustion, malformed output, and timeout; streaming reported actual token usage. Worker checks confirmed cancellation prevents review publication and schedule advancement, a terminated subprocess tree is reaped, and a failed scheduled occurrence does not requeue automatically. Local-adapter checks confirmed cancellation and timeout close the request.
- Observed limits: provider calls default to 300 seconds and a review to 900 seconds. A per-call timeout may save a visibly limited static report; an expired total review budget does not publish a review. Authentication and usage states require user-triggered retry after restoring access. These were controlled failure checks, while real authentication and successful provider responses were checked separately.

## Final regression check

- `python -m pytest -q`: **126 passed**, with one third-party `TestClient` deprecation warning.
- `pnpm test:browser`: **3 Edge browser scenarios passed**, including cancellation and malformed-AI limited-report behavior.
- `openspec validate close-audit-acceptance --strict`: passed; this verification-only change intentionally uses `skip_specs: true` and introduces no new product requirement.
