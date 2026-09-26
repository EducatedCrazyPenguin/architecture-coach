# Spec Delta

## Purpose

Allow a learner to turn a saved architecture finding into a validated implementation plan while retaining control over writes to the reviewed project.

## ADDED Requirements

### Requirement: Generate a source-backed plan
The app SHALL generate one OpenSpec change from a saved review finding, its valid evidence, current project goal, and optional learner constraint using the selected provider.

#### Scenario: Finding becomes a draft
- **WHEN** the learner requests a plan for a saved finding
- **THEN** an asynchronous job returns a draft tied to that review, finding, snapshot, and provider configuration

### Requirement: Validate and preview exact files
The app SHALL show the complete proposed files and validation result before publication.

#### Scenario: Draft is invalid
- **WHEN** provider output or OpenSpec validation fails
- **THEN** the draft remains inspectable and cannot be published as ready

### Requirement: Approve an append-only write
The app SHALL write only a new change directory after explicit approval of the exact draft revision and a fresh project fingerprint check.

#### Scenario: Project changed since review
- **WHEN** the registered project differs from the saved snapshot
- **THEN** publication stops without changing project files and asks for a fresh review

#### Scenario: Publication repeats
- **WHEN** the same approved draft is submitted again
- **THEN** the existing matching receipt is returned without overwriting or duplicating files

### Requirement: Keep ordinary review read-only
The app SHALL not write project files during capture, review, chat, assessment or plan generation.

#### Scenario: Plan created without approval
- **WHEN** generation completes
- **THEN** proposed files remain in private app storage and the target project is unchanged
