# Future updates

This backlog records product changes for a later update. Each item stays separate from the verified first-release ledger until it is selected for implementation.

## UX-001 — Persistent Architecture Tutor side panel

**Status:** proposed

Move **Ask about this snapshot** from the final report section into a persistent panel on the right side of a saved review, similar to the Codex conversation panel.

### Intended behaviour

- Keep the tutor available while the user reads the overview, diagram, changes, findings, and lessons.
- Open and close it from a clearly labelled **Ask instructor** button in the review header.
- Use a fixed or sticky right panel on wide screens without hiding the report.
- Use an accessible slide-over drawer on narrow screens.
- Keep every conversation tied to the selected immutable review and show that review's date or identifier in the panel.
- Keep suggested questions, cited answers, job progress, failures, and the message composer inside the panel.
- Preserve chat history when the panel is closed or the user moves between sections of the same review.
- Let the existing `#chat` link open and focus the panel for compatible saved links.
- Support keyboard focus, Escape to close, and a visible close button.

### Scope

This is primarily a presentation change. The existing snapshot-based chat storage, evidence validation, queue priority, cancellation, and source boundaries should remain unchanged.

### Acceptance checks

- A user can ask a question while keeping any report section visible.
- Opening and closing the panel does not reload or lose the conversation.
- Citations still open source from the conversation's saved snapshot.
- A newer review never silently replaces the panel's selected review.
- Desktop and narrow-screen Playwright scenarios pass with keyboard-only operation.

## LEARN-002 — Personal local learning library

**Status:** proposed

Build a private library from completed repository quizzes so concepts can be revised across projects without recapturing source.

### Intended behaviour

- Save concepts, cited examples, incorrect answers, and later corrections locally.
- Offer spaced review sessions using evidence from the immutable review that created each question.
- Group questions by concepts such as boundaries, coupling, data flow, testing, and dependency direction.
- Keep private source excerpts inside `%LOCALAPPDATA%\ArchCoach`; export only when the user explicitly chooses a destination.
- Work with either the Codex account provider or Ollama through Codex CLI.
- Detect when a cited review is old and link to the newer project review without rewriting the original question.

### Acceptance checks

- A learner can open one revision queue spanning several projects.
- Incorrect answers return later and understood concepts appear less often.
- Every explanation identifies its originating project review and saved evidence.
- Deleting a project removes its private library entries through existing database ownership rules.
