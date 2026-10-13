## Why

Ordinary instructor chat does not distinguish asking for an answer from practising reasoning. Learners need gradual help and feedback grounded in the selected saved review.

## What Changes

- Add opt-in hint, explain-back, simpler/deeper, and design modes to the existing instructor queue.
- Reuse saved explanations without a provider and preserve drafts when choosing a question.
- Record the interaction mode and question origin with each message; use explicit source-based feedback instructions.

## Capabilities

### New Capabilities
- `instructor-practice`: snapshot-grounded help and reasoning practice.

### Modified Capabilities

## Impact

Chat request models, worker, review context, private SQLite message metadata, instructor controls and synthetic tests. No new provider, model load, target writes or language proficiency score.
