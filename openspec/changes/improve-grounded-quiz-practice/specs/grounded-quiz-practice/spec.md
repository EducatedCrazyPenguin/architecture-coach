## ADDED Requirements

### Requirement: N17 Teach before testing
Lessons SHALL have a learning objective, a plain explanation, a saved example, practical relevance and a small self-check. Generated alternatives SHALL be labelled illustrations.

#### Scenario: N17 Teach before testing behavior
- **WHEN** A tiny function-only project is reviewed offline
- **THEN** its saved boundary and inputs are taught without inventing a runtime role

### Requirement: N18 Evidence rather than quota
Fresh quiz schemas and validation SHALL permit zero to ten distinct questions, aiming for ten only when evidence supports them. Static fallback SHALL use declarations and dependencies rather than analyzer trivia. Old quizzes SHALL retain bytes and order.

#### Scenario: N18 Evidence rather than quota behavior
- **WHEN** A small snapshot supports one question
- **THEN** one grounded question is saved with an explanation for reduced coverage

### Requirement: N19 Honest offline attempts
Practice SHALL show one question at a time with a question-specific saved hint and option feedback. Not sure SHALL be a separate outcome, never a correct answer. Retries and idempotent submissions SHALL retain first attempts.

#### Scenario: N19 Honest offline attempts behavior
- **WHEN** The learner records uncertainty then retries correctly
- **THEN** both attempts remain with their distinct outcomes and saved feedback works offline

### Requirement: N20 Optional explain-back
The learner SHALL be able to discuss an explanation or hypothetical change with an explicit rubric for correct ideas, missing ideas and one next step. Skipping SHALL be allowed and English fluency SHALL NOT be graded.
Explain-back output SHALL contain nonempty correct-points and missing-reasoning fields, exactly one follow-up question and locally validated citations. Missing fields SHALL receive at most one repair within the existing time budget; repeated invalid output SHALL remain a failed answer, preserving prior messages.

#### Scenario: N20 Optional explain-back behavior
- **WHEN** The learner chooses explain-back after practice
- **THEN** an unsent question carries saved context without declaring mastery

#### Scenario: Incomplete feedback is not a successful answer
- **WHEN** the provider omits the follow-up question twice
- **THEN** one repair is attempted and the answer is saved as failed, while the learner's question and previous conversation remain readable

Evidence: 2/3 — approved intent and current implementation guide these scenarios; verification is recorded separately and real learning effectiveness is not established.
