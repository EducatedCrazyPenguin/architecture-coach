## ADDED Requirements

### Requirement: N13 Typed saved selection
Chat SHALL accept validated component, relationship, source range, step, lesson, quiz or saved-change selections and show a clearable subject beside the composer.

#### Scenario: N13 Typed saved selection behavior
- **WHEN** A foreign identifier or out-of-range line is submitted
- **THEN** the request is rejected before queueing inference

### Requirement: N14 Selected evidence first
Context SHALL include the selected saved excerpt before broader source packets and disclose truncated source or history. Live project changes SHALL NOT enter saved-review discussion.

#### Scenario: N14 Selected evidence first behavior
- **WHEN** The source budget is crowded
- **THEN** the selected range remains available while omissions are disclosed

### Requirement: N15 Beginner explanation actions
Default guidance SHALL start with a part's job, one saved example and one idea at a time, define terms and keep code optional. Simpler, example, line and deeper actions SHALL create unsent drafts without discarding existing questions.

#### Scenario: N15 Beginner explanation actions behavior
- **WHEN** The learner chooses a simpler explanation while a draft exists
- **THEN** the existing draft and its saved context remain intact

### Requirement: N16 Correction and quality boundaries
New answers SHALL reject invalid citations and deterministically detectable unsupported claims, distinguish quotations from hypothetical illustrations and expose uncertainty. Private flags SHALL pause future question practice without deleting history; valid locations SHALL NOT be treated as proof of reasoning.

#### Scenario: N16 Correction and quality boundaries behavior
- **WHEN** A learner flags a saved question
- **THEN** future practice excludes it until explicitly resolved and old attempts remain available

#### Scenario: Saved quotation must match its cited range
- **WHEN** a new instructor answer labels a fenced block as saved or captured code
- **THEN** its text must occur within a cited saved range after line-ending normalization, including formatted labels; a wrong range gets at most one repair before a visible failure

#### Scenario: Explanations distinguish formatted claims from examples
- **WHEN** an answer uses headings, lists, emphasis or fenced examples
- **THEN** the narrow source-only claim checks apply to prose despite formatting, while a hypothetical fenced log is not treated as an observed test result

Evidence: 2/3 — approved intent and current implementation guide these scenarios; verification is recorded separately and real learning effectiveness is not established.
