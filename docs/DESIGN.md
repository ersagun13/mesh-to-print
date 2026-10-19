# Mesh to Print — product design

## Intent
Help a person understand and improve a mesh before opening it in their slicer. Local physical-size-aware diagnostics, conservative opt-in repairs, before/after measurements and neutral STL/3MF exports. No blanket printable/safe guarantee.

## Scope
STL binary/ASCII, single-file geometry OBJ, embedded uncompressed static GLB. Pure stdlib Python; no Blender startup dependency. Reject nonfinite coordinates, malformed counts/indices, resource paths/network references, unsupported scene features and over-limit inputs. GLB world transforms/instances and y-up convention honored; printing converts to z-up with explicit documented mapping. STL/OBJ units are user-selected mm/cm/m/in; glTF meters defaults explicit. Optional target longest dimension mm overrides absolute units with provenance.

## Checks
Build a diagnostic welded geometric mesh under a disclosed small mm tolerance (distinguish this from changing source output). Exact edge incidence counts: boundaries, >2 incident faces; adjacent winding conflicts; degenerates; duplicate faces; nonmanifold/bowtie vertices; vertex-connected and edge-connected components distinguished. Bounds and build-envelope fit in mm, bed contact. Signed volume unavailable for open/inconsistent meshes; nested/crossing shells prevent unqualified volume claims. Self-intersection detection not assessed unless robust triangle/coplanar predicates exist. Disconnected components are findings, not automatically trash.

Deterministic inward-normal thickness sampling is optional and limited to eligible closed consistent meshes; report attempted rays, valid hits, observed minimum, threshold, coverage and limitations. Use acceleration for bounded samples, time/triangle cap; return not_assessed/indeterminate for invalid geometry or unsupported complexity. It is not a certified whole-mesh minimum. Overhang is a chosen-orientation angle heuristic, excludes bed-contact faces and does not decide support necessity. No raw single 0–100 printable score.

## Repair
Default analyze-only. Explicit clean mode welds selected near duplicates, removes degenerate/duplicate faces and consistently orients local face neighborhoods; report changes. Never indiscriminately fill holes, delete components, make all nested shells outward or thicken parts. Optional small planar hole fill must require explicit max-hole size and disclose closed loops; omit if robust implementation unavailable. Voxel remeshing deferred unless independent robust backend implemented and tested. Always retain before report, modified file separately and after report; repairs can leave issues unresolved.

## CLI
`python3 run.py demo --out DIR` original closed/open/thin fixtures. `python3 run.py analyze INPUT --out DIR [--units mm] [--size MM] [--bed 256,256,256] [--wall 1.2] [--overhang 45] [--samples 256]`. `python3 run.py repair INPUT --out DIR` with same size controls plus explicit weld tolerance. Existing out dir/source never overwritten. `serve` shared contract. UI options `{mode:analyze|repair,units:mm|cm|m|in,size:null,bed:[256,256,256],wall:1.2,overhang:45,samples:256,weld_tolerance:0.00001}`. Finite positive bounds and realistic sample limits are enforced.

## Report and outputs
Shared report plus `scale:{input_units,method,factor_to_mm}`, `topology`, `thickness:{status,method,attempted,valid_hits,minimum_observed_mm,coverage_ratio,limitations}`, `build_volume`, `repair:{operations,before,after,deltas}`. Export deterministic binary STL in mm and neutral standard 3MF Core ZIP/XML with unit millimeter, root relationship and valid resource IDs. 3MF carries geometry only, no Bambu/Prusa project settings, support layout, filament profiles or G-code. `issue_faces` and `issue_edges` may be capped with truncation metadata for UI overlays. All HTML text escaped; JSON strict. Package original/report/output previews and artifacts in bundle.

## Acceptance
20mm cube exact 8000mm3 only under valid volume assumptions; missing face boundaries and null thickness/volume; reversed face corrected; duplicate vertices/triangles; true nonmanifold edge; bowtie vertex; disconnected/nested shells retained; flat open plane never marked printable; exact bed boundary and overflow; units inch/mm and explicit size; negative and instanced GLB transforms; NaN/infinite/extreme counts; malformed STL/ZIP; 3MF schema structure/geometry roundtrip; source hash unchanged and existing output refusal; CSRF/Host/path tests. Meaningful runtime benchmark at >=100k triangles with capped thickness sampling. Real slicer import remains unverified unless actual slicer run performed.
