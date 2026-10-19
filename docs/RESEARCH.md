# Research and engineering decisions

Research checked on 2026-10-18 (Europe/Istanbul). These notes distinguish feasible checks from whole-print guarantees.

## Existing tools and sources
- [Blender3D Print Toolbox](https://extensions.blender.org/add-ons/print3d-toolbox/) already offers common mesh/print checks. We do not claim to invent manifold checks, mesh cleanup or STL export.
- [Prusa model repair guidance](https://help.prusa3d.com/article/corrupted-3d-models-for-printing_2205) explains automatic repair and multiple alternatives. A repair operation is not a guarantee that every model defect was resolved.
- [3MF Core specification](https://github.com/3MFConsortium/spec_core) defines the ZIP/XML model package, units, resources and build items. Our 3MF is neutral geometry, not a complete Bambu/Prusa slicer project or a machine profile.
- [Bambu Studio](https://github.com/bambulab/BambuStudio) and [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer) are the downstream slicers. Actual import is claimed only if executed; structured ZIP/XML checks alone are not slicer execution.
- [BMesh topology/operator documentation](https://docs.blender.org/api/current/bmesh.ops.html) and [BVH documentation](https://docs.blender.org/api/current/mathutils.bvhtree.html) informed the algorithmic distinctions. v1 uses a first-party stdlib implementation rather than launching Blender.

## Why the checks are separate
Edge incidence, duplicate/degenerate triangles, adjacency winding conflicts and configured axis-aligned envelope fit have explicit deterministic definitions. A normal-ray thickness sample is only an observed distance at selected points, not the global minimum wall thickness. Overhang angles depend on orientation and do not model bridging, cooling or actual support strategy. Intersecting or nested shells complicate volume and thickness interpretation; incomplete evidence must remain unavailable/indeterminate.

## Repair decisions
Welding changes geometric topology under a disclosed physical tolerance. Consistent local winding does not decide the intended material/void meaning of nested shells. Small planar hole closure must be explicit and size-limited because an opening may be intentional. Parts are never silently removed. Voxel reconstruction and universal self-intersection certification are not claimed.

## Runtime and privacy
Installed Blender5.2.2 crashes before its Python startup in this host's command-line context; v1 therefore works without Blender or paid AI APIs. Processing is local. Model references must not trigger arbitrary filesystem reads or network fetches. The server is loopback-only, and job requests require a session token and origin/host policy. No telemetry, CDN or background upload is included.
