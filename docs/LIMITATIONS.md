# Limits and unsupported claims

- This is a geometry preparation aid. It cannot guarantee that a part prints, supports itself, carries loads or meets a material/process specification.
- Self-intersections and coplanar overlap are not assessed. Closed two-manifold topology alone does not prove a valid embedded solid. Reported volume is conditional on that additional assumption.
- Nested/touching/intersecting shell AABBs make aggregated material volume unavailable. This intentionally includes some geometrically disjoint but overlapping-box arrangements.
- Diagnostic welding uses0.00001mm. Tiny gaps/features below that tolerance can be merged in diagnostic topology; source output is not silently repaired.
- Thickness is sampled normal-ray distance, not medial-axis thickness or a certified minimum. Sampling is by face index rather than surface area, can miss local defects and is skipped above150,000triangles. At most512rays are attempted even if more were requested.
- Overhangs use the selected+Z orientation and downward normals relative to horizontal. Bed-contact faces are excluded. Winding affects normals; invalid winding makes the heuristic indeterminate. No bridge/span analysis or support generation exists.
- Build-envelope fit uses axis-aligned dimensions and permits translation to the bed origin. It does not search rotations or validate bed collisions/toolhead clearance.
- Cleaning does not make every component outward, delete components, fill arbitrary holes, remesh voxels or thicken walls. Optional hole closure can change design intent and accepts only planar strictly convex simple loops of at most256vertices within the selected diameter. Flat sheets, nonplanar/branched/uncertain boundaries and excessive complexity remain unresolved.
- STL/OBJ do not encode reliable physical units. The default/override is recorded. GLB meters are the default; any explicit override is visible in report scale provenance.
- glTF animation, skins, sparse accessors, morph targets, compression/extensions and external buffers/images are unsupported. Geometry-only OBJ requires triangles and forbids external material/resource files. Geometry does not retain textures or material properties.
- STL and MSH1 positions use float32. Far-from-origin or tiny geometry can lose precision. Export errors/collapsed corners are measured; neutral3MF is preferable when precision matters.
- Maximum input:64MiB,1,000,000triangles,3,000,000position records,±1e9source coordinates and±1e7mm scaled coordinates. Extremely fragmented scenes can still reach worker memory/time limits and fail with no success report.
- GLB metadata is capped at8MiB,4096nodes/meshes/scenes,64hierarchy levels and10,000views/accessors. Instantiated totals count against the geometry limits. Cyclic/multiply-parented active scene graphs and singular transforms are rejected.
- Neutral3MF is verified internally by ZIP/XML structure and geometry re-read. Actual import in Bambu Studio, OrcaSlicer, PrusaSlicer, Cura or a physical print has not been run in this environment.
- This session's operating-system sandbox denied local TCP binding. API policy/path tests and real subprocess job success/failure passed; a live browser-to-HTTP round trip is not claimed.
- Browser shading is an untextured geometry inspection view, not a physically accurate render or slicer toolpath preview. All geometry is included; high triangle counts can be slow on low-memory browsers.
- Local server authentication protects against ordinary cross-origin browser requests and DNS rebinding, not malicious software already running under the same user account.
