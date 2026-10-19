# Shared local application contract

Python 3.10+, standard library only at runtime. No account, paid API, external CDN, telemetry or network model fetch. A local browser interface and CLI use the same processing functions. Originals are never overwritten. Input geometry must be finite, triangle-index bounds checked, malformed/unsupported data rejected before native calls. No external resource reads or network fetches from uploaded model references.

## Server API
- `python3 run.py serve [--port N] [--no-browser]` binds only 127.0.0.1, default ephemeral port. Print actual URL. Use a fresh per-process token, strict Host/Origin checks and no CORS. Jobs run one at a time in bounded subprocesses; no shell commands. Retain files only under the selected local workspace; offer explicit CLI cleanup, never delete original inputs.
- GET `/api/config`: `{app,version,token,max_upload_bytes,profiles,native}`. Upload maximum 64 MiB file bytes; cap request length for base64 overhead.
- POST `/api/jobs` JSON `{filename,content_base64,options}` with header `X-Local-Token`; return HTTP 202 `{job_id,status}`. filenames are display metadata; store under generated names. Unknown keys and invalid finite parameters return clean 400 errors.
- GET `/api/jobs/{id}`: `{job_id,status,progress,message,error,report,artifacts,previews}`. Status queued/running/completed/failed. Progress is a finite fraction from 0 to 1, not a percentage. `artifacts` array entries `{name,url,label}`. `previews` object `{before:url,after:url}` (after may be absent for inspect-only). Error is a plain user-readable string or null.
- GET `/api/jobs/{id}/files/{basename}` serves only registered artifacts in that job, no traversal or arbitrary paths. HTML reports escape all model-derived names; JSON never emits NaN/Infinity.
- GET `/api/demo` returns `{filename,content_base64,options}` for an original bundled fixture, no job side effect. UI can load and submit it normally.
- UI assets in `web/`: `index.html`, `app.js`, `styles.css`, `viewer.js`, `lib.js`, `tests/*.test.mjs`. Backend owns everything except web/. No external frontend dependencies. UI code must show error states, leave input settings editable and offer artifacts after completion.

## Geometry preview binary
`MSH1` ASCII magic (4 bytes), little-endian uint32 vertex count (4), uint32 triangle count (4), then vertex_count*3 float32 XYZ positions followed by triangle_count*3 uint32 indices. All world coordinates, y-up. Entire file exact expected length, finite positions and valid indices required. UI displays flat geometry inspection shading, explicitly not a physically accurate textured render. Source/candidate comparison uses shared orbit controls and scale. Backend can cap preview complexity but must visibly report any subset/decimation via report.preview_note.

## Shared report shape
`schema_version:1`, `app`, `source:{name,sha256,format,bytes}`, `summary:{vertices,triangles,dimensions:[x,y,z],units}`, `findings:[{id,severity,title,detail,count?,method?}]`, `results:[{name,triangles,vertices,bytes,url?,...}]`, `limitations:[string]`, `preview_note`. Other product-specific keys are permitted. UI only assumes this shared shape plus each product spec. Every output is measured by re-reading exported data. Artifacts include report.json, escaped report.html and a ZIP bundle. Build process enforces input/output count and face limits, bounded resources and actionable failure on native/runtime absence.
