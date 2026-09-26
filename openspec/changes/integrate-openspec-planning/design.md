# Design

## Context

The app has immutable snapshots, validated citations, one worker, three AI providers, and a local FastAPI dashboard. Capture includes Markdown. Existing code preserves older review formats.

## Goals / Non-Goals

**Goals:** Plan generation tied to saved findings; exact draft preview; explicit append-only publication; source-backed requirement assessments; Windows validation.

**Non-goals:** Automatic refactoring, auto-archive, cross-repo stores, target custom schemas, and formal compliance claims.

## Decisions

1. Use the pinned OpenSpec CLI only in application-owned staging with isolated global configuration. Treat target specifications as untrusted captured data.
2. Store immutable draft revisions in SQLite with their source snapshot, finding, provider, files, validation and hash. Regeneration creates a new record.
3. Publish only a fresh `openspec/changes/<id>` directory after CSRF, revision-hash, source-fingerprint, Git-context and path checks. Rename staged files into place and reconcile an interrupted publication by content hash.
4. Parse standard local specification Markdown from saved blobs. Feed bounded relevant requirements into the existing critique pass; keep assessments distinct from architecture facts and confidence claims.
5. Preserve prior review readers; bump provenance versions for new output.

## Risks / Trade-offs

- Local models may fail structured output; keep an inspectable invalid draft and require repair before publication.
- Files can change after a saved review; stale drafts must not be written into a changed project.
- OpenSpec validates document structure, not code correctness; retain tests and review evidence as separate checks.
