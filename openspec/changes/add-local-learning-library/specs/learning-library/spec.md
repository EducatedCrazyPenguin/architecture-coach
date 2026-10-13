## ADDED Requirements
### Requirement: Historical practice
Quiz answers SHALL append attempts without replacing historical attempts. Duplicate exact request keys SHALL be idempotent and conflicting reuse SHALL be rejected.
#### Scenario: Wrong answer then correction
- **WHEN** a learner retries an incorrect answer
- **THEN** both attempts remain while existing latest-answer callers show the correction
### Requirement: Offline revision
The application SHALL offer due questions and concepts across saved projects using saved evidence and explanations without provider access or recapture.
#### Scenario: No provider or current folder
- **WHEN** providers and original files are unavailable
- **THEN** saved revision remains usable and keeps its originating review
### Requirement: Data continuity
Legacy answers SHALL migrate without invented history and learning records SHALL follow their owning review's deletion.
#### Scenario: Legacy data
- **WHEN** the database upgrades
- **THEN** a SQLite backup and compatible latest answers are preserved
