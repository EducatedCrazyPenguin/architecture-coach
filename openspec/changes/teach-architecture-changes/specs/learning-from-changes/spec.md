## ADDED Requirements

### Requirement: Learn from saved semantic changes
The application SHALL identify both saved reviews, show bounded before/after source and qualified possible callers, and reuse the common semantic comparison without inventing architecture changes from wording or source-only edits.

#### Scenario: Source-only edit
- **WHEN** a learner selects two saved reviews whose source changed but architecture did not
- **THEN** the exercise displays the saved code change separately from an empty structural delta and identifies uncertainty

### Requirement: Transfer a concept with separate evidence
The application SHALL compare a selected concept using two explicitly selected saved reviews without inventing dependencies between their projects.

#### Scenario: Missing concept evidence
- **WHEN** one selected review lacks matching questions or valid citations
- **THEN** its side shows insufficient saved evidence instead of a fabricated example

### Requirement: Distinguish improvement states
The application SHALL distinguish a draft, saved planning files, user-reported work and observed later source changes without certifying implementation or tests.

#### Scenario: Plan follow-through
- **WHEN** a learner records a report against a later saved review from the same project
- **THEN** the report retains its origin and the page separately displays semantic/source changes; publication alone never marks implementation complete
