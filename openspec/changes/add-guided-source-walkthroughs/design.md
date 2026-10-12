## Decisions
Derive bounded models from saved blobs, not current files; persist them once per review and format version in owned SQLite records. Bound source parsing, steps and displayed excerpts. A step sequence is reading order, never an observed runtime order. Calls and branch outcomes remain inferred; dynamic resolution stays unknown. Render a separate learning graph with the established SVG renderer so existing Archify artifacts remain unchanged. Parent-to-iframe selection accepts only known component IDs and the parent window as sender.

## Verification
Synthetic branch/call/return fixtures, absent source, invalid syntax, unsupported languages, escaped output, graph selection and keyboard checks. Real rendering gate remains pending unless explicitly authorized.

Evidence: 2/3 — static design, runtime and comprehension checks pending.
