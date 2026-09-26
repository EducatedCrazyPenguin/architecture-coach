# Proposal

## Why

Architecture Coach identifies improvements but stops at a copied task. The learner needs a reviewable plan grounded in saved evidence, and a safe way to place that plan in a project's OpenSpec folder. Existing specifications should also inform lessons without being mistaken for observed behavior.

## What Changes

- Adopt pinned OpenSpec for meaningful Architecture Coach changes and Windows validation.
- Generate, validate, preview, revise, download, and explicitly publish finding-based plans.
- Index captured specifications and assess selected requirements against the saved source.

## Capabilities

### New Capabilities

- `improvement-planning`: Saved findings produce reviewable OpenSpec plans and approved repository writes.
- `specification-awareness`: Reviews explain documented requirements and source-backed possible gaps.

### Modified Capabilities

None. Existing release and audit documents remain historical evidence.

## Impact

The worker gains a plan operation; SQLite gains versioned plans and spec assessment artifacts. The review UI gains plan and requirements views. The pinned Node toolchain gains OpenSpec CLI. Only an explicit approval may write a new OpenSpec change folder inside a registered project.
