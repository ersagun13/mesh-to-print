# Reproducible validation

Measured 2026-10-18 on Python 3.14.7, macOS 26.6.2, arm64. These are observations on one machine, not performance promises.

## Checks executed

`python3 -m unittest discover -s tests -v`: 25 tests passed. Cases cover closed/open/reversed/duplicate/degenerate geometry, true nonmanifold edges, bowtie vertices, disconnected and inward nested shells, exact build-envelope boundary, inch/mm/explicit target scaling, binary/ASCII STL, negative OBJ indices, neutral3MF structure/re-read, transformed/instanced/mirrored GLB, malformed counts/ranges/indices/resources, nonfinite options, preserved source hashes, escaped HTML, existing-output refusal, full MSH1 layout, Host/Origin/token/path policy, isolated subprocess job success and clean worker failure.

`node --test`: 16 frontend tests passed. Source/candidate full preview files were also generated for the original vessel.

`python3 run.py serve --no-browser --workspace /tmp/meshprint-bind-check`: exit 2, operating-system EPERM on bind. No live HTTP/browser test is claimed. The browser code and actual engine subprocess jobs were tested separately.

## Original vessel repair

```sh
python3 run.py demo --out examples
python3 run.py repair examples/repairable-vessel.stl --out vessel-report --fill-holes-mm 5 --samples 128
```

| Measurement | Before | After |
| --- | ---: | ---: |
| Triangles | 9,217 | 9,216 |
| Boundary edges | 3 | 0 |
| Degenerate faces | 1 | 0 |
| Duplicate faces | 1 | 0 |
| Winding conflicts | 3 | 0 |
| Material volume | unavailable | 10,433.4189976 mm³, conditional |

One eligible hole was filled with one triangle. One reversed face was corrected. The inner cavity and all original components were retained. The measured pipeline time for this invocation was 0.493899 seconds. The README visual is derived from actual before/after MSH1 geometry.

## Heavy geometry

```sh
python3 run.py demo --out benchmark-inputs --large
python3 tools/benchmark.py benchmark-inputs/benchmark-101888.stl --out benchmark-100k --samples 64
python3 tools/benchmark.py benchmark-inputs/benchmark-500736.stl --out benchmark-500k --samples 64
```

| Input triangles | Input STL bytes | Wall seconds | Peak RSS bytes | Thickness | Boundary edges |
| ---: | ---: | ---: | ---: | --- | ---: |
| 101,888 | 5,094,484 | 4.166642 | 298,156,032 | 64 rays sampled | 0 |
| 500,736 | 25,036,884 | 17.488904 | 1,282,375,680 | not_assessed; triangle cap | 0 |
| 1,000,000 | 50,000,084 | 37.845357 | 2,299,133,952 | not_assessed; triangle cap | 0 |

Each run performed parsing, physical scaling, exact diagnostic topology, conditional volume, build/overhang checks, both geometry exports, emitted-byte re-read, full preview, escaped HTML/strict JSON and ZIP packaging. The 100k run also built the BVH and completed 64 normal rays. The larger runs explicitly skipped thickness rather than returning a fabricated zero.

The one-million-triangle fixture is generated exactly with `sphere(1000,501)` from `meshprint.fixtures`; write it with `write_stl`, then invoke the same benchmark script. Peak RSS uses `resource.getrusage(RUSAGE_SELF).ru_maxrss`, normalized to bytes. On platforms without that API, the script reports null rather than guessing.

The system `/usr/bin/time -l` helper was also attempted but its kernel sysctl query was denied after the child completed. The table uses the successful Python benchmark tool above.

## Not executed here

Cross-platform CI is configured but remote CI results are not claimed before execution. Python 3.10 compatibility is a declared CI target; local runtime was 3.14.7. Real slicer import, printer-specific project compatibility, G-code correctness and a successful physical print remain unverified.

## Review regressions

Unused position records are removed with provenance before physical scaling, keeping preview, STL and 3MF dimensions consistent. Nested or overlapping coplanar boundary regions are skipped during hole filling; disjoint eligible holes remain supported. Weld tolerances below 1e-9 mm are rejected. Regression tests cover these cases.
