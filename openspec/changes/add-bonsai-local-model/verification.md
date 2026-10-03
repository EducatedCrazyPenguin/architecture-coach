# Verification

## Automated behavior

- Starting checkout: `5d67fe14cb5ca83805f8a5b124ed849b9a4eadcb`, clean integration branch.
- Windows `.venv/Scripts/python.exe -m pytest -p no:cacheprovider --basetemp <fresh-private-temp> -q`: 158 passed, including shutdown, private runtime key, transport integration, archive integrity and a real pinned-renderer regression. No required Windows checks skipped. Native rendering needs normal filesystem access; the sandbox's parent-directory realpath denial is not an application defect.
- Selected-model routing, stream parsing, nullable usage, cancellation, frozen job settings, saved-source isolation and plan provenance are covered with synthetic model responses. Tests also prove that missing authentication cannot cause an unauthenticated request.
- Windows `pnpm test:browser`: 4 passed after fixing the exact provider selector. Bonsai selection persists, existing model settings are preserved, and the narrow layout has no horizontal overflow. Synthetic screenshots remain ignored.
- `node tools/openspec.mjs validate add-bonsai-local-model --strict`: passed.
- Runtime tests cover verified/atomic/repeat installation, altered executable, unsafe archive paths, integrity failure, interrupted download, missing weights, loopback launch, one slot and Ctrl+C reaping.
- `pnpm audit --prod`: no known vulnerabilities.

## Real runtime observations

- Installed LM Studio discovers Bonsai under `ternary-bonsai-2-27b`, but native loading of the downloaded PTQ1_0 returns HTTP 500 `model_load_failed`. This confirms the author's published stock-runtime limitation; no execution success claimed from listing alone.
- User approved the separate Prism runtime. Official release `prism-b10754-2459f68` has pinned SHA256 digests for Vulkan, CUDA 12.4 and CPU Windows x64 archives.
- The smaller Vulkan runtime installed with its pinned hash verified. The downloaded PTQ1_0 loaded with 32768 context and returned a valid schema-constrained answer. Restricting Vulkan to the discrete GPU avoided slow mixed-GPU execution.
- Unauthenticated `/v1/models` requests returned 401; authenticated application requests succeeded. The runtime key stays in private storage and is excluded from Git.
- Real acceptance caught an incorrectly nested response-format payload: the runtime silently treated it as an empty schema. The adapter now uses the standard `response_format.json_schema.schema` wrapper. An adversarial enum-constrained smoke request proved grammar enforcement, and reported token usage was read from the native stream.
- The runtime's grammar constrains output without exposing the schema to the model. Both local OpenAI-compatible adapters now include the application-owned schema in the system prompt. Main-path IDs and component types are explained explicitly; a rejected parsed response accompanies the single bounded repair across review, chat and plans.
- Static generic dependency confirmation now uses resolved edges, never label wording. Tests retain limited status for unsupported runtime confirmation and prove that diagram-only failure does not invalidate a complete report.
- A real non-Git Python fixture in a folder containing spaces produced a complete review with two concrete components, four findings and ten source-cited MCQs. All ten correct answers were inspected against the fixture. Follow-up instructor chat completed with five valid saved-source citations.
- The same selected Bonsai model generated a ready behavior-change plan after one bounded repair. The pinned OpenSpec validator passed; provenance named `ternary-bonsai-2-27b`. Source hashes stayed unchanged and generation created no planning files in the fixture. Codex execution was explicitly forbidden throughout this check. The review/chat/plan workflow took 219.6 seconds.
- The original saved review used the interactive fallback graph when Archify rejected overlapping labels. Keyboard selection, evidence details and zoom were checked in a real browser. The geometry-only spacing repair then delivered the same architecture through pinned Archify in two attempts, in separate verification artifacts; immutable review artifacts were preserved.
- The runtime is installed for the normal launcher. An authenticated structured request through normal application storage passed; the user's selected provider and existing model settings were preserved.
- No weights, private source, runtime keys, screenshots or operational logs are committed. Real acceptance evidence remains in ignored private storage.

## Publication

Code checkpoints `dda837f` and `c6360aa` passed GitHub Windows CI. Final source checkpoint, CI and publication evidence will be recorded before archiving. All six implementation/acceptance tasks are verified; publication is the one remaining task.
