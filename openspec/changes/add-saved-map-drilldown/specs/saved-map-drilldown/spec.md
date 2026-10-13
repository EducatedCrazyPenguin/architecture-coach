## ADDED Requirements

### Requirement: N05 Separate source roles
Saved files SHALL be classified as application source, tests, tooling, supporting material or unknown. A filename alone SHALL NOT establish backend, database or frontend responsibility.

#### Scenario: N05 Separate source roles behavior
- **WHEN** README and db.py are captured
- **THEN** documentation is supporting material and db.py is not declared a database on its name alone

### Requirement: N06 Bounded internal graph
A component file view SHALL use saved imports, cap drawing at forty nodes and eighty edges, show omitted counts and permit narrower search or neighbourhood selection.

#### Scenario: N06 Bounded internal graph behavior
- **WHEN** A package has forty-five connected files
- **THEN** the overview stays bounded while hidden imports can be inspected without changing saved architecture

### Requirement: N07 Qualified dependency counts
Counts SHALL use the full applicable saved graph, distinguish internal and external imports, reject invalid line evidence and explain unknown or zero counts without implying runtime independence.

#### Scenario: N07 Qualified dependency counts behavior
- **WHEN** A group has internal imports and no external imports
- **THEN** its internal count is visible and its zero external count is explained

### Requirement: N08 Selection connects learning
Map nodes and import links SHALL support keyboard inspection, neighbour highlighting, search and fit. Instructor selections SHALL identify the exact saved component, connection or cited source.

#### Scenario: N08 Selection connects learning behavior
- **WHEN** A learner selects a component or opens import evidence
- **THEN** the selected responsibility and source are available to an unsent contextual instructor question

Evidence: 2/3 — approved intent and current implementation guide these scenarios; verification is recorded separately and real learning effectiveness is not established.
