# Verification

L07–L09: wrong-to-correct attempts remain append-only, exact duplicate request keys reuse the same attempt and conflicting keys return 409. Equal timestamps retain insertion order. Existing latest answers, chats and lesson progress survive backed-up transactional migrations. Fixed clocks check offline due recall and no same-day streak boost. First-attempt results, legacy unknown history, originating dates, newer-review warnings and escaped private notes are shown. Owned records cascade on project/review deletion without deleting target files.

**Evidence: 2/3 — synthetic saved-source behavior and headless flows are verified; real-provider teaching quality and learner comprehension remain unverified.**

See the [shared release checkpoint](../verify-repository-learning-journey/verification.md) for full automated gates, installed-source evidence, commit scope and pending acceptance. This change is not a claim of a fully verified daily-use release.
