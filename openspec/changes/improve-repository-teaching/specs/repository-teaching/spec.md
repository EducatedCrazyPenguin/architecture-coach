## ADDED Requirements

### Requirement: Saved teaching and practice
The application SHALL show useful saved lessons beside quizzes and extract examples only from validated captured source. It SHALL identify generated examples separately and preserve existing artifact bytes.

#### Scenario: Both teaching formats exist
- **WHEN** a saved review contains lessons and questions
- **THEN** both are accessible with saved source evidence and an on-demand Markdown export

#### Scenario: Current code is unavailable
- **WHEN** a project folder or provider is unavailable
- **THEN** reading teaching and exporting saved content requires neither recapture nor generation

### Requirement: Learning orientation
The application SHALL display readable component names and the selected provider, and SHALL expose a learning start for the saved review.

#### Scenario: Local provider selected
- **WHEN** the selected provider is local
- **THEN** dashboard labeling identifies that provider rather than Codex

### Requirement: Meaningful questions
New structured questions SHALL identify their concept and difficulty and explain source-grounded choices. Older questions SHALL remain readable without invented metadata.

#### Scenario: Legacy quiz
- **WHEN** a question lacks concept metadata
- **THEN** it is labelled unclassified and remains answerable
