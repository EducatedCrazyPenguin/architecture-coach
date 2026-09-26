# Spec Delta

## Purpose

Help a learner compare documented requirements with the source saved in the same architecture review without claiming formal verification.

## ADDED Requirements

### Requirement: Index captured OpenSpec documents
The app SHALL distinguish current specifications, active proposed changes, and archived history within the captured snapshot.

#### Scenario: Standard OpenSpec project
- **WHEN** a review captures local `openspec/specs/` and `openspec/changes/` documents
- **THEN** the saved review shows their roles and links to captured source lines

### Requirement: Assess selected requirements
The app SHALL assess at most twenty relevant current requirements against saved code, report coverage, and label each assessment supported, possible gap, or uncertain.

#### Scenario: Source does not establish a requirement
- **WHEN** the available saved code cannot establish fulfillment
- **THEN** the assessment is uncertain or a possible gap, and never a compliance pass

### Requirement: Preserve architecture truth
The app SHALL keep written requirements and proposed work separate from observed components and confirmed dependencies.

#### Scenario: Specification wording changes
- **WHEN** only a specification or task list changes
- **THEN** the app does not report a fabricated runtime component or dependency change
