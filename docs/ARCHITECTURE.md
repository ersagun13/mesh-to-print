# Architecture

## Processing boundary

`run.py` → `meshprint.cli` uses the same `pipeline.process` as the isolated local HTTP worker. There are no runtime package dependencies or native geometry calls.

| Module | Responsibility |
| --- | --- |
| `formats.py` | Byte/count limits, finite coordinate/index checks, STL/OBJ/GLB import, neutral Core 3MF and binary STL export |
| `geometry.py` | Physical scaling, bounded representative weld, edge incidence, vertex links, conditional volume, BVH rays, conservative repair |
| `pipeline.py` | Source hash/preservation, before/after reports, emitted-byte measurements, escaped HTML, full MSH1 previews and ZIP bundle |
| `server.py` | Loopback Host/Origin/token policy, generated paths, finite job queue, registered downloads and bounded subprocess workers |
| `fixtures.py` | Original cube/plate/hollow fluted vessel and exact-count sphere generators |
| `web/` | Dependency-free browser UI and geometry inspection viewer |

## Coordinates and scale

Internally, printing geometry is right-handed z-up in millimeters. GLB static scene transforms, parent matrices, multiple mesh instances and negative determinants are applied first. glTF y-up becomes print z-up through `(x,-z,y)`; mirrored world transforms reverse triangle winding. STL/OBJ coordinates retain their supplied axes.

Unit conversion records `scale.input_units`, `method`, `factor_to_mm` and optional target longest dimension. A target size overrides absolute-unit scaling. Previews rotate `(x,y,z)` into `(x,z,-y)` for the shared y-up viewer. No preview triangles are removed; issue indices refer exactly to the named before/after preview.

## Geometry invariants

Diagnostics build a separately welded geometric mesh at a disclosed 0.00001 mm Euclidean representative tolerance. That does not alter the source file. Degenerate faces are excluded from incidence; duplicate faces remain and are separately reported. Vertex links distinguish a bowtie from a true edge-connected neighborhood.

Volume uses the divergence theorem around a shell-local origin and `math.fsum`. It is conditional on absent self-intersections/coplanar overlap. Open, duplicated, nonmanifold or inconsistent topology has unavailable volume. Multiple shells are aggregated only when AABBs are disjoint, with at most 128 shell-pair candidates; overlapping/nested boxes and greater shell counts remain unavailable.

Thickness uses triangle-centroid inward-normal rays, a median BVH and deterministic evenly indexed samples. At most 512 rays, 150,000 triangles, 100,000 BVH node visits per ray and a 15 second sampling budget are allowed. The clock budget is checked between rays and includes BVH construction. Valid-hit ratio is not surface coverage. Reports explicitly distinguish sampled, indeterminate and not_assessed.

Repair uses the explicit weld tolerance and exact candidate adjacency for local orientation. It minimizes flipped faces within each orientable neighborhood rather than making every shell outward. Optional bounded planar convex hole closure reverses adjacent boundary winding, rejects flat sheets and keeps original components. No topology certification is implied.

## Request and worker policy

Only 127.0.0.1 is bound. Host must exactly match the printed origin; present Origin headers must match. POST requires matching Origin, a fresh process token, JSON Content-Type and a bounded Content-Length. No CORS headers are sent. Duplicate security headers, path traversal, arbitrary paths and external model resource reads are rejected.

Uploaded names are display metadata only and must be basenames. Generated random job identifiers own all stored paths. Downloads require registration in a completed job. HTML escapes all model-derived text; JSON forbids NaN/Infinity. No upload filename enters a shell command; worker arguments are passed as an array.

The queue and session history are finite. Disk reservations conservatively account for pending jobs before another upload is accepted. Worker subprocesses have a 300 second deadline; shutdown terminates active work. Linux adds 4 GiB address-space and POSIX adds CPU/file limits. macOS/Windows do not have an enforced process memory cap; geometry/request/queue limits remain explicit. Workspace cleanup requires the app marker and a stopped server and only removes generated job directories.

## Export verification

Binary STL is float32 and can lose precision far from the origin. Neutral 3MF uses 17 significant digits and exact duplicate-position sharing. Each export is re-read; reports measure actual vertices, triangles, bounds, maximum corner-coordinate error and collapsed triangle corners. The after report is measured from re-read neutral3MF. Precision loss is disclosed and a collapsed STL emits an error finding.

Neutral 3MF includes `[Content_Types].xml`, `_rels/.rels`, a millimeter Core model, resource object id 1 and a matching build item. No slicer-specific metadata is invented. The bounded3MF reader is a verifier for this emitted subset, not an advertised general3MF importer.
