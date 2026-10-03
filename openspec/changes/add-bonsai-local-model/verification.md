# Verification

## Automated behavior

- Starting checkout: `5d67fe14cb5ca83805f8a5b124ed849b9a4eadcb`, clean integration branch.
- Windows `.venv/Scripts/python.exe -m pytest -q`: 149 passed, including shutdown, private runtime key, transport integration and archive integrity regressions. No required Windows checks skipped.
- Windows `.venv/Scripts/python.exe -m pytest tests/test_prism.py -q`: 10 passed, including real adapter streaming with synthetic architecture, ten-question quiz, chat and pinned-CLI-validated plan output. Selected model provenance and saved-source isolation asserted.
- Windows `pnpm test:browser`: 4 passed after fixing the exact provider selector. Bonsai selection persists, existing model settings are preserved, and the narrow layout has no horizontal overflow. Synthetic screenshots remain ignored.
- `node tools/openspec.mjs validate add-bonsai-local-model --strict`: passed.
- Runtime tests cover verified/atomic/repeat installation, altered executable, unsafe archive paths, integrity failure, interrupted download, missing weights, loopback launch, one slot and Ctrl+C reaping.
- `pnpm audit --prod`: no known vulnerabilities.

## Real runtime observations

- Installed LM Studio discovers Bonsai under `ternary-bonsai-2-27b`, but native loading of the downloaded PTQ1_0 returns HTTP 500 `model_load_failed`. This confirms the author's published stock-runtime limitation; no execution success claimed from listing alone.
- User approved the separate Prism runtime. Official release `prism-b10754-2459f68` has pinned SHA256 digests for Vulkan, CUDA 12.4 and CPU Windows x64 archives.
- The smaller Vulkan runtime installed with its pinned hash verified. The downloaded PTQ1_0 loaded with 32768 context and returned a valid schema-constrained answer. Restricting Vulkan to the discrete GPU avoided slow mixed-GPU execution.
- Unauthenticated `/v1/models` requests returned 401; authenticated application requests succeeded. The runtime key stays in private storage and is excluded from Git.
- No weights, private source or operational logs are committed. Live review/quiz/instructor/plan acceptance is in progress.

## Publication

Pending final automated checks, real runtime acceptance and tested commit evidence. This change remains active until required acceptance is proved.
