## ADDED Requirements

### Requirement: Progressive saved-review help
The application SHALL offer a reading hint and explicit saved explanation without a provider, and deliberate instructor modes without overwriting an unsent draft.

#### Scenario: Offline help
- **WHEN** a learner opens a saved question with providers unavailable
- **THEN** a hint points to saved evidence without displaying the correct option and the full saved explanation is revealable

### Requirement: Source-grounded reasoning practice
The instructor SHALL use the selected snapshot and an explicit correctness/missing-reasoning/next-question rubric for explain-back, and SHALL allow multiple defensible designs under stated constraints.

#### Scenario: Explain-back request
- **WHEN** a learner submits an explanation for a saved question
- **THEN** the queued request includes the saved question, attempt and evidence with application-controlled rubric instructions, and the interaction origin is persisted

#### Scenario: Unknown question or provider failure
- **WHEN** a request names a question outside the selected review or the provider fails
- **THEN** the application rejects the unknown question or records failure without a successful answer or source switch
