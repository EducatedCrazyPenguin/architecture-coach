## ADDED Requirements

### Requirement: Qualified saved feature outlines
The application SHALL expose a versioned bounded feature outline with saved citations, inputs, outputs and branch/failure annotations. It SHALL distinguish syntactic observations from inferred runtime behavior.

#### Scenario: Dynamic behavior
- **WHEN** call resolution or execution order cannot be established statically
- **THEN** the walkthrough labels it inferred or unknown rather than verified runtime behavior

#### Scenario: Unsupported parser
- **WHEN** the captured language has no supported feature parser
- **THEN** a limited state retains the ordinary architecture review

### Requirement: Synchronized reading
The application SHALL highlight the current component and show its saved source with keyboard-accessible previous/next navigation.

#### Scenario: Historical source
- **WHEN** current files change or disappear
- **THEN** walkthrough steps still use their original captured source

### Requirement: Test evidence is not execution evidence
Captured test assertions SHALL be identified as inspected source, never passing tests.

#### Scenario: Test association
- **WHEN** a captured assertion refers to a selected feature
- **THEN** its saved location is shown with execution explicitly unverified
