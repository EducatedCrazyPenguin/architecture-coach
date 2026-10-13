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

#### Scenario: Beginner starts without reading syntax
- **WHEN** a learner chooses a simple explanation from a saved review
- **THEN** the instructor draft selects simpler mode without submitting it or overwriting an unsent draft, teaching guidance explains one idea in plain language before code and lesson code stays available through a keyboard-accessible disclosure

#### Scenario: Teaching instructions improve
- **WHEN** the application changes its architecture, source-summary or critique teaching prompt
- **THEN** new review checks regenerate teaching rather than reusing the old configuration, while existing reviews and their captured evidence remain unchanged

#### Scenario: Generated example may omit existing work
- **WHEN** a lesson displays a generated code illustration
- **THEN** the screen and Markdown teaching export warn that it may omit steps and must be checked against the full saved source before replacing working code

#### Scenario: Teaching distinguishes observations from guarantees
- **WHEN** the application requests lessons, self-check answers and quiz explanations
- **THEN** its shared guidance treats captured tests as unexecuted expectations, temporary state as distinct from durable storage, and recommended interfaces as distinct from enforced access control; valid citation locations alone do not establish those guarantees

### Requirement: Meaningful questions
New structured questions SHALL identify their concept and difficulty and explain source-grounded choices. Older questions SHALL remain readable without invented metadata.

#### Scenario: Generated answers favour one position
- **WHEN** a new ten-question AI quiz repeats the correct answer position
- **THEN** the application balances the four correct positions deterministically before saving, keeps each explanation with its option and preserves question identity, source citations and correct answer meaning

#### Scenario: Wording depends on option position
- **WHEN** generated quiz text uses explicit choice-letter references or all/none-of-the-above choices that cannot safely be reordered
- **THEN** validation rejects that output through the existing bounded repair and limited-review path instead of silently changing its meaning

#### Scenario: Saved quiz already has attempts
- **WHEN** a learner reopens or reuses an existing saved review
- **THEN** its question order, options, answer indices and attempts remain unchanged; the new ordering policy applies only to newly generated quizzes

#### Scenario: Legacy quiz
- **WHEN** a question lacks concept metadata
- **THEN** it is labelled unclassified and remains answerable
