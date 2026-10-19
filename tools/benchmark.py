#!/usr/bin/env python3
"""Reproducible actual processing time and process peak RSS, not estimates."""
import argparse
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from meshprint.pipeline import process


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--samples', type=int, default=64)
    args = parser.parse_args()
    start = time.perf_counter()
    report = process(args.input, args.out, {'samples': args.samples})
    peak = None
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != 'darwin':
            peak *= 1024
    except ImportError:
        pass
    print(json.dumps({'python': platform.python_version(), 'platform': platform.platform(),
                      'triangles': report['summary']['triangles'],
                      'elapsed_seconds': round(time.perf_counter() - start, 6),
                      'peak_rss_bytes': peak,
                      'thickness_status': report['thickness']['status'],
                      'thickness_attempted': report['thickness']['attempted'],
                      'volume_mm3': report['volume']['volume_mm3'],
                      'boundary_edges': report['topology']['boundary_edges']}))


if __name__ == '__main__':
    main()
