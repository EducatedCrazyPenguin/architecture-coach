## ADDED Requirements

### Requirement: N21 Saved short session
A suggested purpose, feature, lesson, two-question, optional explanation and next-step session SHALL save position and unfinished drafts per immutable review without timers or locked progression.

#### Scenario: N21 Saved short session behavior
- **WHEN** The owned server exits and restarts
- **THEN** the same review restores its draft, question position and next step

### Requirement: N22 Offline next steps
My learning SHALL recommend unfinished work first, then due recall, then an unpractised evidenced concept, with an explanation. Mistakes and uncertainty SHALL be revisitable through existing history.

#### Scenario: N22 Offline next steps behavior
- **WHEN** No provider is available
- **THEN** the recommendations still work and explain why each item is suggested

### Requirement: N23 Source-linked glossary
A small glossary SHALL distinguish general definitions from examples tied to a named saved review. Missing examples SHALL be explicit. Advanced topics SHALL NOT be assumed present.

#### Scenario: N23 Source-linked glossary behavior
- **WHEN** A saved review has a validation example but no queue evidence
- **THEN** the example cites the snapshot and queues are not described as implemented

### Requirement: N24 Improvement loop
Prediction and tradeoffs SHALL connect to existing approved plans and later comparisons. Saved planning files SHALL NOT mean implementation, and source changes SHALL NOT mean tests passed. Sound decisions SHALL remain visible.

#### Scenario: N24 Improvement loop behavior
- **WHEN** A plan is saved then a later review is compared
- **THEN** implementation and user-reported test evidence remain separate from planning and observed source changes

Evidence: 2/3 — approved intent and current implementation guide these scenarios; verification is recorded separately and real learning effectiveness is not established.
