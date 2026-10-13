## ADDED Requirements

### Requirement: N01 Saved review entry
Project cards with a saved review SHALL open its complete workspace and identify project, saved date, selected instructor provider and asynchronous current-source status.

#### Scenario: N01 Saved review entry behavior
- **WHEN** A project already has a review
- **THEN** the full review opens with its identity, without starting inference or recapturing source

### Requirement: N02 Shared learning navigation
Every review learning view SHALL expose Overview, Map, Follow a feature, Learn, Quiz, Changes and Ask instructor. A narrow instructor drawer SHALL support Escape, keyboard focus containment and return focus.

#### Scenario: N02 Shared learning navigation behavior
- **WHEN** A learner navigates from the map on a narrow screen
- **THEN** quiz and instructor remain reachable and unsent questions survive navigation

### Requirement: N03 Application expanded map
Expand diagram SHALL open an application workspace. Original standalone artifact URLs and bytes SHALL remain unchanged and available as named exports.

#### Scenario: N03 Application expanded map behavior
- **WHEN** A learner expands an old saved diagram
- **THEN** Back to review, Practise and Ask about this map remain available

### Requirement: N04 Useful unavailable states
Missing questions, limited analysis, unavailable providers and missing rendered artifacts SHALL have useful explanations and deliberate next actions. Reading SHALL not initiate inference.

#### Scenario: N04 Useful unavailable states behavior
- **WHEN** A legacy review has no quiz or diagram
- **THEN** saved material remains readable and the user is directed to source, settings or an explicit new review

Evidence: 2/3 — approved intent and current implementation guide these scenarios; verification is recorded separately and real learning effectiveness is not established.
