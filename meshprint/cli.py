"""CLI and subprocess worker entry points sharing the same processing engine."""
import argparse
import json
from pathlib import Path
import sys
from .fixtures import demo_meshes, sphere
from .formats import MeshError, write_stl
from .pipeline import json_bytes, process


def bed_value(text):
    try:
        values = [float(x) for x in text.split(',')]
        if len(values) != 3:
            raise ValueError()
        return values
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Bed must be X,Y,Z in mm.') from exc


def processing_arguments(parser):
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--units', choices=('mm', 'cm', 'm', 'in'), default=None,
                        help='Default: GLB meters; STL/OBJ millimeters.')
    parser.add_argument('--size', type=float, help='Target longest dimension in mm.')
    parser.add_argument('--bed', type=bed_value, default=[256., 256., 256.])
    parser.add_argument('--wall', type=float, default=1.2)
    parser.add_argument('--overhang', type=float, default=45.)
    parser.add_argument('--samples', type=int, default=256)
    parser.add_argument('--weld-tolerance', type=float, default=0.00001)
    parser.add_argument('--fill-holes-mm', type=float, default=None,
                        help='Repair only: opt in to bounded planar convex hole closure. May close intentional openings.')


def worker(source, out, request):
    """Apply POSIX limits before reading upload bytes; the parent enforces timeout."""
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (290, 295))
            resource.setrlimit(resource.RLIMIT_FSIZE, (512 * 1024 ** 2, 512 * 1024 ** 2))
            # macOS does not consistently implement RLIMIT_AS; Linux enforces it.
            if sys.platform.startswith('linux'):
                resource.setrlimit(resource.RLIMIT_AS, (4 * 1024 ** 3, 4 * 1024 ** 3))
        except ImportError:
            pass  # Windows still has count, upload, queue and subprocess time bounds.
        payload = json.loads(request.read_text())
        process(source, out, payload['options'], source_name=payload['filename'])
        return 0
    except Exception as exc:
        message = str(exc) or 'Worker resource limit reached. Try fewer triangles.'
        (source.parent / 'worker-error.json').write_bytes(json_bytes({'error': message[:2000]}))
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local physical-size-aware mesh diagnostics and conservative opt-in repairs.')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('analyze', 'repair'):
        processing_arguments(sub.add_parser(command))
    demo = sub.add_parser('demo', help='Generate original fixtures, including a 101,888 triangle sphere.')
    demo.add_argument('--out', required=True, type=Path)
    demo.add_argument('--large', action='store_true', help='Also generate a 500,736 triangle benchmark sphere.')
    server = sub.add_parser('serve', help='Open the loopback-only browser workspace.')
    server.add_argument('--port', type=int, default=0)
    server.add_argument('--no-browser', action='store_true')
    server.add_argument('--workspace', type=Path, default=Path('meshprint-workspace'))
    cleanup = sub.add_parser('cleanup', help='Remove generated jobs from a stopped marked workspace.')
    cleanup.add_argument('--workspace', required=True, type=Path)
    internal = sub.add_parser('_worker', help=argparse.SUPPRESS)
    internal.add_argument('source', type=Path)
    internal.add_argument('out', type=Path)
    internal.add_argument('request', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command in ('analyze', 'repair'):
            options = {key: getattr(args, key) for key in ('units', 'size', 'bed', 'wall', 'overhang', 'samples', 'weld_tolerance', 'fill_holes_mm')}
            options['mode'] = args.command
            report = process(args.input, args.out, options)
            print(json.dumps({'output': str(args.out.absolute()), 'triangles': report['summary']['triangles'],
                              'volume_mm3': report['volume']['volume_mm3'],
                              'volume_status': report['volume']['status'],
                              'boundary_edges': report['topology']['boundary_edges'],
                              'elapsed_seconds': report['elapsed_seconds']}, allow_nan=False))
        elif args.command == 'demo':
            if args.out.exists():
                raise MeshError('Demo output already exists. Choose a new directory.')
            args.out.mkdir(parents=True)
            meshes = demo_meshes()
            meshes['benchmark-101888.stl'] = sphere()
            if args.large:
                meshes['benchmark-500736.stl'] = sphere(512, 490)
            manifest = []
            for name, mesh in meshes.items():
                data = write_stl(mesh)
                (args.out / name).write_bytes(data)
                manifest.append({'name': name, 'triangles': len(mesh.triangles), 'bytes': len(data)})
            (args.out / 'fixtures.json').write_bytes(json_bytes(manifest))
            print(json.dumps(manifest))
        elif args.command == 'serve':
            from .server import serve
            if not 0 <= args.port <= 65535:
                raise MeshError('Port must be 0–65535.')
            serve(args.port, args.no_browser, args.workspace)
        elif args.command == 'cleanup':
            from .server import cleanup_workspace
            print(json.dumps({'removed_jobs': cleanup_workspace(args.workspace)}))
        elif args.command == '_worker':
            return worker(args.source, args.out, args.request)
        return 0
    except (MeshError, OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
