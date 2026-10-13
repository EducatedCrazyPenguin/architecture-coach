## ADDED Requirements

### Requirement: N09 Evidence-based entry candidates
Reading boundaries SHALL qualify declared functions, captured script guards, route declarations, exports and JSX handler references. A main name alone SHALL NOT establish a CLI. The learner SHALL be able to choose a saved file.

#### Scenario: N09 Evidence-based entry candidates behavior
- **WHEN** A function is named main without a script guard
- **THEN** its entry mechanism remains unconfirmed

### Requirement: N10 Branch-aware Python reading
Python outlines SHALL follow uniquely resolved captured local declarations, identify inputs, decisions, calls, local/state assignments, returns and failures, and stop at ambiguous or dynamic targets.

#### Scenario: N10 Branch-aware Python reading behavior
- **WHEN** A branch raises or a block returns
- **THEN** alternatives are labelled and later statements are not placed on that terminated block path

#### Scenario: Dictionary entries retain reading order
- **WHEN** a captured Python dictionary contains calls in keys, values and unpacking
- **THEN** its reading outline pairs each key and value in source order, and unresolved targets remain labelled

#### Scenario: Unsupported iteration expressions
- **WHEN** a captured Python comprehension or generator would need repeated or deferred evaluation
- **THEN** call ordering is omitted with a limitation, while the saved expression remains inspectable

### Requirement: N11 Snapshot compiler outlines
JavaScript and TypeScript outlines SHALL use the pinned compiler and captured per-file configuration. External configuration, dynamic dispatch, shadowed targets, syntax failures and ambiguous bindings SHALL remain unresolved or qualified. Target dependencies SHALL NOT execute or install.

#### Scenario: N11 Snapshot compiler outlines behavior
- **WHEN** Captured nested workspace configuration resolves a local exported call
- **THEN** cited declarations are linked and unsupported configuration is disclosed

#### Scenario: Conditional calls retain their path
- **WHEN** Python or TypeScript uses a conditional expression or calls a local function from a branch
- **THEN** conditional calls and linked child steps retain that qualification instead of appearing unconditional

### Requirement: N12 Synchronized bounded steps
Steps SHALL highlight saved components and excerpts and distinguish declared facts from runtime inference and unexecuted assertions. Limits SHALL be twenty-four files, depth two, thirty steps and twelve outlines, prioritised around a chosen saved file.

#### Scenario: N12 Synchronized bounded steps behavior
- **WHEN** A learner follows a Python or TypeScript boundary
- **THEN** map and optional code follow the selected step without inventing a network runtime link

#### Scenario: Earlier derived steps cannot silently change subject
- **WHEN** a parser update changes outline order
- **THEN** old derived views remain stored, new views use a distinct version, and instructor selection must match the displayed version; stale context is rejected while drafts remain saved

Evidence: 2/3 — approved intent and current implementation guide these scenarios; verification is recorded separately and real learning effectiveness is not established.
