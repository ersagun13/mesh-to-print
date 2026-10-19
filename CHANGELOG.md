# Changelog

## 0.1.0 — 2026-10-18

- Add bounded STL/triangulated OBJ/static embedded GLB import with world transforms and explicit physical scale.
- Add exact topology diagnostics, conditional volume, BVH-accelerated sampled thickness and chosen-orientation build/overhang checks.
- Add opt-in conservative welding, duplicate/degenerate removal, local winding and bounded planar convex hole closure.
- Add measured millimeter STL and neutral Core3MF exports, full before/after previews, escaped HTML/strict JSON and ZIP bundles.
- Add loopback browser workspace with Host/Origin/token policy, generated artifact paths and isolated bounded workers.
- Add original procedural fixtures,21 Python tests,16 browser logic tests and actual100k/500k/1mtriangle benchmarks.

Known limitations: self-intersections and whole-mesh minimum wall are not certified; no voxel remeshing, arbitrary hole reconstruction, support generation, G-code or slicer-specific project settings. Actual slicer import and physical printing remain unverified.
