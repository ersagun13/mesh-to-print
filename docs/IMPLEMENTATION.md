# mesh-to-print Implementation Plan

> For agentic workers: use isolated vertical implementation, meaningful test-first checks and independent final review.

**Goal:** Deliver the approved local print mesh product with CLI, browser interface, measured outputs and reproducible examples.
**Architecture:** Python standard-library engine and loopback-only server; dependency-free WebGL inspection interface. Game simplification uses vendored pinned meshoptimizer C++ compiled locally. Printing geometry checks and conservative repair are first-party Python.
**Spec:** docs/DESIGN.md and docs/LOCAL_APP_CONTRACT.md.

## Global constraints
- Preserve original input; never overwrite an existing output directory.
- No paid APIs, telemetry, external CDNs or arbitrary resource fetches.
- Explicitly reject unsupported/malformed geometry; no fabricated pass or unavailable zero measurements.
- Report actual output geometry/size; benchmark facts must be reproducible.
- Source and web writers stage only their owned paths.

## Review focus
1. Untrusted glTF offsets/counts, cyclic scene nodes and external URLs fail before allocations/native calls.
2. Negative/nonuniform transforms, mirrored winding and unit conversions preserve intended dimensions.
3. Invalid origin/token/Host, filename traversal and oversized uploads never access arbitrary files.
4. Missing native capability and partial jobs produce actionable failures, no fake success.
5. Meshes with boundaries, nested/disconnected shells, seam-heavy attrs or tiny features never get unsupported quality claims.

## Task 1 — processing engine, CLI and server
Owner: backend vertical. All files except web/, third_party/ and tools/build_native.py.
- [ ] Write failing format and geometry tests for a cube, malformed accessors, transforms and unsupported inputs.
- [ ] Implement bounded parsers and writers; round-trip exact topology and dimensions.
- [ ] Write failing pipeline tests for product-specific checks and opt-in changes.
- [ ] Implement inspect/process functions, reports, preview binary and artifact bundles according to spec.
- [ ] Write failing request-policy and path-validation tests, implement loopback-only bounded job server.
- [ ] Add original procedural fixtures, CLI quickstart, limitations, architecture and CI.
- [ ] Run complete engine suite and real generated-fixture CLI run; commit only owned files.

## Task 2 — browser workspace
Owner: UI vertical, only web/. Consumes the exact shared server and report contracts.
- [ ] Write failing node tests for options, report formatting and preview binary validation.
- [ ] Build original responsive interface: upload/drop, settings, status/errors, paired preview, issue/report summary, artifact downloads.
- [ ] Build dependency-free orbitable WebGL geometry viewer, synchronized cameras and print issue overlay.
- [ ] Implement demo load, abort-safe polling, keyboard/accessibility states and honest inspection shading labels.
- [ ] Run node tests and syntax checks; commit only web/.

## Task 3 — native engine and integration
Owner: root integrator, game-only third_party/, native build tooling and dependency provenance.
- [ ] Vendor pinned MIT upstream sources with sha256 manifest.
- [ ] Compile the exact native source subset, load by ctypes and test real geometry reduction.
- [ ] Connect declared library discovery/build paths; verify no stale binaries are committed.

## Task 4 — final integration and release
Owner: root with independent reviewers.
- [ ] Check source/UI API contracts and complete end-to-end fixture generation and processing.
- [ ] Review each repository for correctness, format validity, resource bounds and honest claims.
- [ ] Fix findings, re-run covering tests and full required gates.
- [ ] Produce actual demo reports/metrics and clean repository commits.
- [ ] Create public repositories, publish and verify remote SHA/tree matches local delivery.

## Interface preflight
| Producer | Consumer | Check |
|---|---|---|
| Backend job API | UI | Shared docs fixes endpoint/status/options/report/preview names. |
| Root native build | Game engine | native/ discovery + MESHOPT_LIBRARY or explicit CLI path. |
| Engine exports | Reviewer/Unity/slicer | Validate bytes/indices/dimensions; runtime checks only claimed when executed. |

## Execution authorization
User requested both repositories be researched, created and implemented, with parallel agents permitted. Continue implementation autonomously within these scopes; disclose material limitations and verify before publication.
