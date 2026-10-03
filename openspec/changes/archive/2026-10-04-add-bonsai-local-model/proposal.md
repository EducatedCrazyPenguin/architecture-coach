# Proposal

## Why

A downloaded local model should be selectable before switching providers. Settings currently uses the selected provider's model list for both local providers and treats a downloaded LM Studio model as ready even when it cannot load.

## What Changes

- Discover LM Studio language models independently of the selected provider, including `ternary-bonsai-2-27b`, while excluding embedding models.
- Keep Ollama and LM Studio suggestions separate and preserve saved model choices and the Qwen default.
- Distinguish a model being detected from verified execution and show actionable, bounded load errors for unsupported runtimes.
- Verify the selected model is used by all existing AI operations without invoking Codex or switching models.
- Add a separate Prism local provider and pinned Windows CUDA/CPU runtime setup and launcher, reusing the already downloaded GGUF. The user approved this runtime after the actual LM Studio load failure.

## Capabilities

### New Capabilities

- `local-model-selection`: independent local-model discovery, persistent selection, honest readiness and selected-model execution.

### Modified Capabilities

None. Existing improvement planning already uses the selected provider.

## Impact

Local provider adapters, configuration, settings presentation, runtime tooling, adapter and browser tests, and setup documentation. No database migration or Python dependency. Runtime binaries are pinned and downloaded outside the public repository. The exact downloaded PTQ1_0 Bonsai format currently fails to load in stock LM Studio; live acceptance will use the approved Prism runtime instead.
