# Spec Delta

## Purpose

Let users select an installed local language model and run the existing coach operations with clear runtime requirements and no silent provider substitution.

## ADDED Requirements

### Requirement: Independent model selection
Settings SHALL show each local provider's own language-model suggestions regardless of the currently selected provider, preserve saved model IDs, and allow an exact server model ID. Embedding models SHALL be excluded from LM Studio suggestions.

#### Scenario: Bonsai is discovered before switching provider
- **WHEN** Codex is selected and LM Studio lists Bonsai, Qwen and an embedding model
- **THEN** LM Studio suggestions include Bonsai and Qwen, exclude the embedding model, and do not contain Ollama's model names

#### Scenario: Discovery is unavailable
- **WHEN** a local server is stopped or returns malformed model metadata
- **THEN** Settings remains usable, explains discovery is unavailable, and preserves saved values

### Requirement: Dedicated supported Bonsai runtime
The system SHALL offer a separate Prism local provider using the author's pinned runtime on loopback port 1235. Installation SHALL verify download hashes and reject unsafe archive paths. Launch SHALL use the existing GGUF without downloading weights, require at least 32768 context tokens, expose one slot, and provide an explicit way to stop the server.

Model API requests SHALL use a private local API key shared through application storage, never browser settings or reports.

#### Scenario: Install and launch Bonsai
- **WHEN** the user installs the pinned Windows runtime and launches it with a downloaded Bonsai GGUF
- **THEN** the server exposes `ternary-bonsai-2-27b` on loopback, and no target project or global LM Studio configuration is modified

#### Scenario: Invalid download or missing weights
- **WHEN** an archive fails integrity checks or the selected GGUF does not exist
- **THEN** installation or launch fails clearly without publishing an incomplete runtime or downloading another model

#### Scenario: Unauthenticated model API access
- **WHEN** a request to the launched Prism model API omits its private key
- **THEN** the runtime rejects it and the application can still make authenticated local requests

### Requirement: Selected-model-only execution
Review architecture, critique, repository quiz, instructor chat and improvement plans SHALL use the selected local model and saved source. Missing or failed models SHALL never invoke Codex or switch to another local model.

#### Scenario: All coach operations run locally
- **WHEN** Prism is selected with a working Bonsai model
- **THEN** review, ten quiz questions, cited instructor response and a validated improvement draft use that model with no Codex execution

#### Scenario: Model cannot load
- **WHEN** a selected LM Studio model is detected but loading fails
- **THEN** the app reports the load error and runtime remedy, and does not label discovery alone as verified execution

#### Scenario: Cancellation and malformed output
- **WHEN** local generation times out, is cancelled, or returns malformed structured data
- **THEN** the request closes and the existing failure or limited-report handling remains visible
