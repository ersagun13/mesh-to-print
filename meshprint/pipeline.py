"""Shared CLI/server processing, escaped reports and verified geometry exports."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import struct
import time
import zipfile
from . import __version__
from .formats import Mesh, MeshError, MAX_BYTES, finite, integer, load_mesh, write_stl, write_3mf, read_3mf
from .geometry import MIN_WELD_TOLERANCE, bounds, clean_mesh, inspect_mesh, scale_mesh
APP = 'Mesh to Print'
DEFAULTS = {
    'mode': 'analyze',
    'units': None,
    'size': None,
    'bed': [256.0, 256.0, 256.0],
    'wall': 1.2,
    'overhang': 45.0,
    'samples': 256,
    'weld_tolerance': 1e-05,
    'fill_holes_mm': None
}
LIMITATIONS = [
    'Self-intersections, coplanar overlaps and whole-mesh minimum wall thickness are not certified.',
    'Overhangs are a chosen-orientation normal-angle heuristic; support structures and unsupported spans are not generated.',
    'Neutral 3MF contains geometry only: no printer/filament profiles, support layout or G-code.',
    'Actual slicer import and successful physical printing have not been verified.',
    'Diagnostic welding at 0.00001 mm can merge features below its tolerance; repair welding changes geometry only when explicitly selected.'
]


def validate_options(value=None):
    """Validate the entire shared option object; reject unknown and nonfinite inputs."""
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise MeshError('Options must be a JSON object.')
    unknown = set(value) - set(DEFAULTS)
    if unknown:
        raise MeshError('Unknown options: ' + ', '.join(sorted(unknown)))
    opt = {**DEFAULTS, **value}
    opt['bed'] = list(opt['bed']) if isinstance(opt['bed'], (list, tuple)) else opt['bed']
    if opt['mode'] not in ('analyze', 'repair'):
        raise MeshError('Mode must be analyze or repair.')
    if opt['units'] not in (None, 'mm', 'cm', 'm', 'in'):
        raise MeshError('Units must be mm, cm, m or in.')
    for key, maximum, nullable, zero in [
        ('size', 10000000.0, True, False),
        ('wall', 10000.0, False, False),
        ('overhang', 90, False, True),
        ('weld_tolerance', 1.0, False, False),
        ('fill_holes_mm', 10000.0, True, False)
    ]:
        val = opt[key]
        if nullable and val is None:
            continue
        val = finite(val, key, maximum)
        if val < 0 or (not zero and val == 0):
            raise MeshError(f'{key} must be positive.' if not zero else f'{key} must be nonnegative.')
        opt[key] = val
    if opt['weld_tolerance'] < MIN_WELD_TOLERANCE:
        raise MeshError('Weld tolerance must be at least 0.000000001 mm.')
    integer(opt['samples'], 'samples', 0, 4096)
    if not isinstance(opt['bed'], list) or len(opt['bed']) != 3:
        raise MeshError('Bed must contain three positive mm dimensions.')
    opt['bed'] = [finite(x, 'bed dimension', 10000000.0) for x in opt['bed']]
    if any((x <= 0 for x in opt['bed'])):
        raise MeshError('Bed dimensions must be positive.')
    if opt['mode'] != 'repair' and opt['fill_holes_mm'] is not None:
        raise MeshError('Hole filling requires explicit repair mode.')
    return opt


def preview_bytes(mesh):
    """Encode all geometry as MSH1, rotating print z-up into viewer y-up."""
    data = bytearray(struct.pack('<4sII', b'MSH1', len(mesh.vertices), len(mesh.triangles)))
    for x, y, z in mesh.vertices:
        data.extend(struct.pack('<3f', x, z, -y))
    for t in mesh.triangles:
        data.extend(struct.pack('<3I', *t))
    return bytes(data)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def html_report(report):
    """Escape every model-derived field, including JSON rendered as HTML text."""
    def escape(value):
        return html.escape(str(value), quote=True)

    findings = ''.join(
        '<li><strong>' + escape(finding['title']) + '</strong> — '
        + escape(finding['detail']) + '</li>'
        for finding in report['findings']
    )
    keys = ('summary', 'scale', 'topology', 'volume', 'thickness',
            'build_volume', 'overhang', 'results')
    measurements = json.dumps(
        {key: report[key] for key in keys}, indent=2,
        ensure_ascii=False, allow_nan=False,
    )
    limitations = ''.join('<li>' + escape(item) + '</li>'
                          for item in report['limitations'])
    document = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width">'
        '<title>Mesh to Print report</title><style>'
        'body{max-width:960px;margin:3rem auto;padding:0 1rem;'
        'font:16px/1.6 system-ui;color:#17362f;background:#f5f6ef}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:1rem}'
        'li{margin:.7rem 0}h1{line-height:1.15}</style>'
        '<h1>Mesh to Print</h1><p>Source: ' + escape(report['source']['name'])
        + '</p><p>No printability score or print guarantee. '
        'Review diagnostics and export in your slicer.</p>'
        '<h2>Findings</h2><ul>' + findings + '</ul>'
        '<h2>Measured geometry</h2><pre>' + escape(measurements) + '</pre>'
        '<h2>Limitations</h2><ul>' + limitations + '</ul></html>'
    )
    return document.encode('utf-8')


def measure_export(data, name, expected):
    """Re-read actual emitted geometry, comparing counts, bounds and corner precision."""
    mesh = read_3mf(data) if name.endswith('.3mf') else load_mesh(data, name)[0]
    lo, hi = bounds(mesh.vertices)
    if len(mesh.triangles) != len(expected.triangles):
        raise MeshError('Export round-trip triangle count mismatch.')
    # STL stores independent corners rather than shared vertices; compare corresponding corners.
    error = 0.0
    for actual, wanted in zip(mesh.triangles, expected.triangles):
        for ai, wi in zip(actual, wanted):
            error = max(
                error,
                max((abs(mesh.vertices[ai][k] - expected.vertices[wi][k]) for k in range(3)))
            )
    collapsed = sum((len({mesh.vertices[i] for i in t}) < 3 for t in mesh.triangles))
    return {
        'name': name,
        'vertices': len(mesh.vertices),
        'triangles': len(mesh.triangles),
        'bytes': len(data),
        'dimensions_mm': [hi[i] - lo[i] for i in range(3)],
        'maximum_coordinate_error_mm': error,
        'collapsed_triangles_on_roundtrip': collapsed,
        'verified_by': 'Re-read exported bytes with bounds and index validation.'
    }


def process(input_path, out_path, options=None, source_name=None):
    """Preserve source bytes and create a separate, never-overwritten output directory."""
    opt = validate_options(options)
    input_path = Path(input_path)
    out = Path(out_path)
    if out.exists():
        raise FileExistsError(f'Output directory already exists: {out}. Choose a new directory.')
    if not input_path.is_file() or input_path.stat().st_size > MAX_BYTES:
        raise MeshError('Input must be a regular file no larger than 64 MiB.')
    data = input_path.read_bytes()
    name = source_name or input_path.name
    if not isinstance(name, str) or not name or len(name) > 255:
        raise MeshError('Source display name must be 1–255 characters.')
    started = time.monotonic()
    mesh, meta = load_mesh(data, name)
    units = opt['units'] or meta['default_units']
    scaled, scale = scale_mesh(mesh, units, opt['size'])
    del mesh
    before = inspect_mesh(scaled, opt)
    candidate = compact_exact(scaled)
    operations = None
    if opt['mode'] == 'repair':
        candidate, operations = clean_mesh(scaled, opt['weld_tolerance'], opt['fill_holes_mm'])
    # Round-trip neutral 3MF is exact to 17 significant digits. The candidate report is measured from those bytes.
    mf = write_3mf(candidate)
    candidate = read_3mf(mf)
    after = inspect_mesh(candidate, opt) if opt['mode'] == 'repair' else before
    stem = 'cleaned' if opt['mode'] == 'repair' else 'normalized'
    stl = write_stl(candidate)
    results = [
        measure_export(stl, stem + '.stl', candidate),
        measure_export(mf, stem + '.3mf', candidate)
    ]
    report = {
        'schema_version': 1,
        'app': APP,
        'version': __version__,
        'source': {
            'name': name,
            'sha256': hashlib.sha256(data).hexdigest(),
            'format': meta['format'],
            'bytes': len(data)
        },
        **after,
        'scale': scale,
        'options': {**opt, 'units': units},
        'input_coordinates': meta,
        'results': results,
        'limitations': list(LIMITATIONS),
        'export_note': 'Exact duplicate position records are shared in neutral 3MF; triangle surface and winding are preserved.',
        'preview_note': 'Full geometry in float32; print +Z maps to viewer +Y as(x,z,-y). Preview shading is geometry inspection, not a physically accurate render.',
        'issue_preview': 'after' if opt['mode'] == 'repair' else 'before'
    }
    if scale['removed_unreferenced_position_records']:
        report['findings'].append({
            'id': 'unreferenced_positions', 'severity': 'info',
            'title': 'Unreferenced position records excluded',
            'detail': 'Positions unused by all triangles were removed before physical scaling, bounds, preview and export. Original source bytes are retained.',
            'count': scale['removed_unreferenced_position_records'],
        })
    if any((r['maximum_coordinate_error_mm'] > 1e-05 for r in results)):
        report['limitations'].append('Float32 STL/preview precision exceeds diagnostic weld tolerance. Prefer neutral 3MF or recenter geometry; see measured export error.')
    if any((r['collapsed_triangles_on_roundtrip'] for r in results)):
        report['findings'].append({
            'id': 'stl_precision',
            'severity': 'error',
            'title': 'STL precision collapsed triangle corners',
            'detail': 'Float32 export loses distinct positions. Prefer the neutral 3MF output and inspect measured round-trip results.'
        })
    if operations is not None:
        report['repair'] = {
            'operations': operations,
            'before': before,
            'after': after,
            'deltas': {
                'vertices': after['summary']['vertices'] - before['summary']['vertices'],
                'triangles': after['summary']['triangles'] - before['summary']['triangles'],
                'boundary_edges': after['topology']['boundary_edges'] - before['topology']['boundary_edges'],
                'winding_conflicts': after['topology']['winding_conflicts'] - before['topology']['winding_conflicts']
            }
        }
        report['limitations'].append('Explicit hole filling can close intentional openings; only eligible planar convex loops within the requested diameter are filled.')
    report['elapsed_seconds'] = round(time.monotonic() - started, 6)
    out.mkdir(parents=True, exist_ok=False)
    try:
        (out / ('original.' + meta['format'])).write_bytes(data)
        (out / (stem + '.stl')).write_bytes(stl)
        (out / (stem + '.3mf')).write_bytes(mf)
        (out / 'before.msh').write_bytes(preview_bytes(scaled))
        if operations is not None:
            (out / 'after.msh').write_bytes(preview_bytes(candidate))
        (out / 'report.json').write_bytes(json_bytes(report))
        (out / 'report.html').write_bytes(html_report(report))
        with zipfile.ZipFile(
            out / 'bundle.zip',
            'x',
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6
        ) as z:
            for path in sorted(out.iterdir()):
                if path.name != 'bundle.zip':
                    z.write(path, path.name)
    except Exception:
        shutil.rmtree(out)
        raise
    return report


def compact_exact(mesh):
    """Share identical positions without changing any coordinate or face order."""
    unique = {}
    vertices = []
    remap = []
    for position in mesh.vertices:
        if position not in unique:
            unique[position] = len(vertices)
            vertices.append(position)
        remap.append(unique[position])
    return Mesh(vertices, [tuple((remap[i] for i in tri)) for tri in mesh.triangles])
