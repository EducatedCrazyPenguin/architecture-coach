# Design

## Context

See proposal.md. The existing LM Studio adapter already streams OpenAI-compatible JSON schema responses, tracks reported usage and closes cancelled requests. The installed server lists Bonsai PTQ1_0 but returns model_load_failed on load. The user explicitly approved Prism runtime integration.

## Goals / Non-Goals

Goals: reuse streamed response handling, independently discover local choices, retain configured provider identity across jobs, and make Bonsai usable with its supported Windows runtime.

Non-goals: automatic code implementation, model downloads, cloud fallback, installing Prism's optional WebUI/tool ecosystem, or changing LM Studio itself.

## Decisions

- Extract shared OpenAI-compatible streaming into a small base adapter. LM Studio retains its model loading API; Prism checks a running llama-server's context instead. Avoid copying the existing stream reader.
- Fixed loopback endpoints keep configuration simple and prevent sending source to a remote base URL. Prism uses port 1235 and the stable alias `ternary-bonsai-2-27b`.
- Add a nullable `prism_model` setting using existing settings storage. Include the effective model in fingerprints and plan provenance. Freeze the right adapter at job start.
- Cache independent local discovery for Settings for thirty seconds. Discovery never loads weights or calls the Codex CLI when a local provider is selected.
- Pin official Prism release `prism-b10754-2459f68` and asset SHA256 digests. Install into application data through a private staging directory and atomic rename. Use the stdlib for downloads and safe zip extraction; do not execute downloaded setup scripts.
- Default to the smaller author-supported Vulkan Windows build, with optional CUDA and CPU builds. This avoids a large CUDA/DLL download while retaining GPU acceleration on this machine.
- Provide a separate foreground Bonsai launcher with clean Ctrl+C shutdown; the app connects to this runtime and cancels individual requests without terminating the independently launched server. Do not claim Exit app stops an external model service.
- Use documented non-thinking structured output for bounded coach tasks, with the author's non-thinking sampling parameters. No tool definitions or execution are supplied.

## Risks / Trade-offs

- Native runtime needs memory and a supported GPU/driver → CUDA and CPU choices, explicit startup errors, one slot and 32768 context.
- Downloaded does not mean loadable → show detected state and preserve bounded server errors; real acceptance separate from synthetic tests.
- Future runtime updates → pinned version and hashes, update only through a reviewed change.

## Migration Plan

Settings additions are additive; saved Qwen and other model choices remain unchanged. Rollback selects an existing provider and stops the separate Bonsai process. Models and operational logs are never committed.
