import base64
import hashlib
import json
import math
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
try:
    from meshprint.formats import Mesh, MeshError, load_mesh, write_stl, write_3mf, read_3mf
    from meshprint.geometry import inspect_mesh, clean_mesh, scale_mesh
    from meshprint.pipeline import process, validate_options
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

def cube(size=20, offset=(0, 0, 0)):
    v = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    f = [
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7)
    ]
    return Mesh([tuple((p[i] * size + offset[i] for i in range(3))) for p in v], f)

def glb(positions, indices, nodes=None, extras=None):
    raw = b''.join((struct.pack('<3f', *p) for p in positions))
    off = len(raw)
    raw += b''.join((struct.pack('<I', i) for t in indices for i in t))
    model = {
        'asset': {'version': '2.0'},
        'buffers': [{'byteLength': len(raw)}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': off},
            {'buffer': 0, 'byteOffset': off, 'byteLength': len(raw) - off}
        ],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': len(positions), 'type': 'VEC3'},
            {'bufferView': 1, 'componentType': 5125, 'count': len(indices) * 3, 'type': 'SCALAR'}
        ],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'nodes': nodes or [{'mesh': 0}],
        'scenes': [{'nodes': list(range(len(nodes or [1])))}],
        'scene': 0
    }
    if extras:
        extras(model)
    js = json.dumps(model).encode()
    js += b' ' * (-len(js) % 4)
    raw += b'\x00' * (-len(raw) % 4)
    body = struct.pack('<I4s', len(js), b'JSON') + js + struct.pack('<I4s', len(raw), b'BIN\x00') + raw
    return struct.pack('<4sII', b'glTF', 2, 12 + len(body)) + body

class EngineTests(unittest.TestCase):

    def setUp(self):
        self.assertTrue(AVAILABLE, 'meshprint engine is not implemented')

    def inspect(self, mesh, **kw):
        return inspect_mesh(mesh, validate_options(kw))

    def test_closed_cube_volume_and_thickness(self):
        r = self.inspect(cube())
        self.assertEqual(r['volume']['volume_mm3'], 8000)
        self.assertEqual(r['topology']['boundary_edges'], 0)
        self.assertAlmostEqual(r['thickness']['minimum_observed_mm'], 20)
        self.assertEqual(r['self_intersection']['status'], 'not_assessed')
        self.assertNotIn('score', r)

    def test_open_cube_has_no_volume_or_thickness(self):
        m = cube()
        m.triangles.pop()
        r = self.inspect(m)
        self.assertEqual(r['topology']['boundary_edges'], 3)
        self.assertIsNone(r['volume']['volume_mm3'])
        self.assertIsNone(r['thickness']['minimum_observed_mm'])

    def test_reversed_face_repair_and_source_unchanged(self):
        m = cube()
        m.triangles[0] = tuple(reversed(m.triangles[0]))
        original = list(m.triangles)
        self.assertGreater(self.inspect(m)['topology']['winding_conflicts'], 0)
        fixed, changes = clean_mesh(m, 1e-05)
        self.assertEqual(self.inspect(fixed)['topology']['winding_conflicts'], 0)
        self.assertEqual(m.triangles, original)
        self.assertEqual(changes['flipped_faces'], 1)

    def test_degenerate_duplicate_removed(self):
        m = cube()
        m.triangles += [(0, 0, 1), m.triangles[0]]
        r = self.inspect(m)
        self.assertEqual(r['topology']['degenerate_faces'], 1)
        self.assertEqual(r['topology']['duplicate_faces'], 1)
        fixed, ch = clean_mesh(m, 1e-05)
        self.assertEqual(len(fixed.triangles), 12)

    def test_nonmanifold_edge_and_bowtie_vertex(self):
        m = Mesh(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)],
            [(0, 1, 2), (1, 0, 3), (0, 1, 4)]
        )
        self.assertEqual(self.inspect(m)['topology']['nonmanifold_edges'], 1)
        b = Mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)], [(0, 1, 2), (0, 3, 4)])
        t = self.inspect(b)['topology']
        self.assertEqual(t['vertex_components'], 1)
        self.assertEqual(t['edge_components'], 2)
        self.assertGreater(t['nonmanifold_vertices'], 0)

    def test_nested_shells_preserved_and_volume_qualified(self):
        a = cube()
        b = cube(10, (5, 5, 5))
        m = Mesh(
            a.vertices + b.vertices,
            a.triangles + [tuple((i + 8 for i in reversed(t))) for t in b.triangles]
        )
        r = self.inspect(m)
        self.assertIsNone(r['volume']['volume_mm3'])
        self.assertEqual(r['topology']['edge_components'], 2)
        fixed, ch = clean_mesh(m, 1e-05)
        self.assertEqual(fixed.triangles, m.triangles)
        self.assertEqual(ch['removed_components'], 0)

    def test_disjoint_shell_volume_and_exact_bed_boundary(self):
        a = cube()
        b = cube(20, (30, 0, 0))
        m = Mesh(a.vertices + b.vertices, a.triangles + [tuple((i + 8 for i in t)) for t in b.triangles])
        self.assertEqual(self.inspect(m)['volume']['volume_mm3'], 16000)
        self.assertTrue(self.inspect(cube(256))['build_volume']['fits'])
        self.assertFalse(self.inspect(cube(256.01))['build_volume']['fits'])

    def test_hole_filling_is_explicit_bounded_and_rejects_flat_sheet(self):
        m = cube()
        m.triangles.pop()
        fixed, ch = clean_mesh(m, 1e-05)
        self.assertEqual(self.inspect(fixed)['topology']['boundary_edges'], 3)
        fixed, ch = clean_mesh(m, 1e-05, 28)
        self.assertEqual(self.inspect(fixed)['topology']['boundary_edges'], 3)
        fixed, ch = clean_mesh(m, 1e-05, 29)
        self.assertEqual(self.inspect(fixed)['volume']['volume_mm3'], 8000)
        self.assertEqual(ch['filled_holes'], 1)
        plane = Mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 1, 2), (0, 2, 3)])
        fixed, ch = clean_mesh(plane, 1e-05, 10)
        self.assertEqual(ch['filled_holes'], 0)
        self.assertIsNone(self.inspect(fixed)['volume']['volume_mm3'])

    def test_nonplanar_boundary_is_not_filled(self):
        m = cube()
        del m.triangles[2:4]
        m.vertices[4] = (0, 0, 21)
        fixed, changes = clean_mesh(m, 1e-05, 100)
        self.assertEqual(changes['filled_holes'], 0)
        self.assertEqual(self.inspect(fixed)['topology']['boundary_edges'], 4)

    def test_nested_coplanar_tube_rims_are_not_capped_as_overlapping_disks(self):
        n = 8
        vertices = [
            (radius * math.cos(2 * math.pi * j / n),
             radius * math.sin(2 * math.pi * j / n), z)
            for z in (0, 3) for radius in (2, 1) for j in range(n)
        ]
        faces = []
        for j in range(n):
            k = (j + 1) % n
            faces.extend(((j, k, 2*n+k), (j, 2*n+k, 2*n+j),
                          (n+j, 3*n+k, n+k), (n+j, 3*n+j, 3*n+k),
                          (j, n+k, k), (j, n+j, n+k)))
        mesh = Mesh(vertices, faces)
        for maximum in (4.1, 2.1):
            with self.subTest(maximum=maximum):
                fixed, changes = clean_mesh(mesh, 1e-5, maximum)
                self.assertEqual(changes['filled_holes'], 0)
                self.assertEqual(len(fixed.triangles), len(faces))
                self.assertEqual(self.inspect(fixed)['topology']['boundary_edges'], 16)
                self.assertIsNone(self.inspect(fixed)['volume']['volume_mm3'])

    def test_disjoint_coplanar_holes_can_still_be_filled(self):
        first = cube()
        second = cube(offset=(40, 0, 0))
        first.triangles.pop()
        second.triangles.pop()
        mesh = Mesh(first.vertices + second.vertices,
                    first.triangles + [tuple(index+8 for index in tri)
                                       for tri in second.triangles])
        fixed, changes = clean_mesh(mesh, 1e-5, 29)
        self.assertEqual(changes['filled_holes'], 2)
        self.assertEqual(self.inspect(fixed)['topology']['boundary_edges'], 0)
        self.assertEqual(self.inspect(fixed)['volume']['volume_mm3'], 16000)

    def test_subnormal_weld_tolerance_is_cleanly_rejected(self):
        with self.assertRaises(MeshError):
            validate_options({'mode': 'repair', 'weld_tolerance': 5e-324})
        with self.assertRaises(MeshError):
            clean_mesh(cube(), 5e-324)

    def test_unused_obj_positions_do_not_change_physical_extent(self):
        mesh = cube()
        records = ['v %g %g %g' % point for point in mesh.vertices]
        records.append('v 1000 0 0')
        records += ['f %d %d %d' % tuple(i+1 for i in tri) for tri in mesh.triangles]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'unused.obj'
            source.write_text('\n'.join(records) + '\n')
            for options, dimensions in [({'samples': 0}, [20, 20, 20]),
                                        ({'size': 100, 'samples': 0}, [100, 100, 100])]:
                destination = Path(temporary) / ('scaled' if 'size' in options else 'unscaled')
                report = process(source, destination, options)
                self.assertEqual(report['summary']['dimensions'], dimensions)
                self.assertTrue(report['build_volume']['fits'])
                self.assertEqual(report['scale']['removed_unreferenced_position_records'], 1)
                for result in report['results']:
                    self.assertEqual(result['dimensions_mm'], dimensions)
                _, preview_vertices, _ = struct.unpack_from('<4sII', (destination/'before.msh').read_bytes())
                self.assertEqual(preview_vertices, 8)
                self.assertIn(b'v 1000 0 0', (destination/'original.obj').read_bytes())

    def test_units_and_explicit_size(self):
        m, scale = scale_mesh(cube(1), 'in', None)
        self.assertEqual(self.inspect(m)['summary']['dimensions'], [25.4] * 3)
        m, scale = scale_mesh(cube(1), 'in', 20)
        self.assertEqual(self.inspect(m)['volume']['volume_mm3'], 8000)
        self.assertEqual(scale['method'], 'target_longest_dimension')

    def test_stl_obj_and_3mf_roundtrip(self):
        m = cube()
        binary = write_stl(m)
        self.assertEqual(len(binary), 684)
        self.assertEqual(self.inspect(load_mesh(binary, 'cube.stl')[0])['volume']['volume_mm3'], 8000)
        archive = write_3mf(m)
        again = read_3mf(archive)
        self.assertEqual(again.triangles, m.triangles)
        self.assertEqual(again.vertices, m.vertices)
        with zipfile.ZipFile(__import__('io').BytesIO(archive)) as z:
            self.assertIn('_rels/.rels', z.namelist())
        obj = b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1\n'
        self.assertEqual(len(load_mesh(obj, 'x.obj')[0].triangles), 1)
        ascii_stl = b'solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n'
        self.assertEqual(len(load_mesh(ascii_stl, 'x.stl')[0].triangles), 1)

    def test_glb_transforms_instances_mirror_and_axis(self):
        data = glb(
            [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            [(0, 1, 2)],
            [
                {'mesh': 0, 'scale': [-1, 2, 1], 'translation': [2, 3, 4]},
                {'mesh': 0, 'translation': [5, 0, 0]}
            ]
        )
        m, meta = load_mesh(data, 'x.glb')
        self.assertEqual(len(m.triangles), 2)
        self.assertEqual(m.vertices[0], (2, -4, 3))
        self.assertEqual(m.triangles[0], (0, 2, 1))
        self.assertEqual(meta['default_units'], 'm')

    def test_malformed_resources_and_limits(self):
        for data, name in [
            (b'solid bad', 'x.stl'),
            (struct.pack('<80sI', b'x', 4294967295), 'x.stl'),
            (b'v nan 0 0\nf 1 1 1', 'x.obj'),
            (b'v 0 0 0\nf 1 2 3', 'x.obj'),
            (b'v 0 0 0\nmtllib ../secret', 'x.obj'),
            (b'PK\x03\x04', 'x.3mf')
        ]:
            with self.subTest(name=name, data=data[:20]), self.assertRaises(MeshError):
                load_mesh(data, name)
        corruptions = [
            lambda d: d['buffers'][0].update(uri='https://example.org/x.bin'),
            lambda d: d['accessors'][0].update(count=2147483647),
            lambda d: d['nodes'][0].update(children=[0]),
            lambda d: d.update(animations=[{}]),
            lambda d: d['accessors'][0].update(sparse={}),
            lambda d: d['meshes'][0]['primitives'][0].update(mode=5)
        ]
        for change in corruptions:
            with self.subTest(change=change), self.assertRaises(MeshError):
                load_mesh(glb([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)], extras=change), 'x.glb')
        for opt in [
            {'size': float('nan')}, {'size': 10 ** 400},
            {'samples': 10000000},
            {'bed': [1, 2]},
            {'unknown': 1},
            {'mode': 'voxel'}
        ]:
            with self.assertRaises((MeshError, ValueError)):
                validate_options(opt)

    def test_glb_parent_matrix_and_embedded_accessor_ranges(self):
        points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        faces = [(0, 1, 2)]

        def hierarchy(d):
            d['nodes'] = [
                {'translation': [1, 2, 3], 'children': [1]},
                {'mesh': 0, 'matrix': [2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0, 0, 0, 0, 1]}
            ]
            d['scenes'] = [{'nodes': [0]}]
        mesh, meta = load_mesh(glb(points, faces, extras=hierarchy), 'nested.glb')
        self.assertEqual(mesh.vertices, [(1, -3, 2), (3, -3, 2), (1, -3, 5)])
        bad = [
            lambda d: d.update(asset=[]),
            lambda d: d['bufferViews'][0].update(byteLength=1),
            lambda d: d['accessors'][0].update(byteOffset=2),
            lambda d: d['nodes'][0].update(scale=[0, 1, 1]),
            lambda d: d.update(images=[{'uri': 'file:///secret.png'}])
        ]
        for change in bad:
            with self.assertRaises(MeshError):
                load_mesh(glb(points, faces, extras=change), 'bad.glb')
        with self.assertRaises(MeshError):
            load_mesh(glb(points, [(0, 1, 99)]), 'bad.glb')

    def test_globally_reversed_shell_and_sampling_disabled(self):
        m = cube()
        m.triangles = [tuple(reversed(t)) for t in m.triangles]
        report = self.inspect(m, samples=0)
        self.assertEqual(report['volume']['signed_volume_mm3'], -8000)
        self.assertEqual(report['volume']['volume_mm3'], 8000)
        self.assertIsNone(report['thickness']['minimum_observed_mm'])
        fixed, changes = clean_mesh(m, 1e-05)
        self.assertEqual(fixed.triangles, m.triangles)

    def test_preview_binary_matches_full_geometry_and_axis(self):
        from meshprint.pipeline import preview_bytes
        m = cube()
        data = preview_bytes(m)
        magic, nv, nt = struct.unpack_from('<4sII', data)
        self.assertEqual((magic, nv, nt), (b'MSH1', 8, 12))
        self.assertEqual(len(data), 12 + 8 * 12 + 12 * 12)
        self.assertEqual(struct.unpack_from('<3f', data, 12 + 4 * 12), (0, 20, 0))
        self.assertEqual(struct.unpack_from('<3I', data, 12 + 8 * 12), m.triangles[0])

    def test_pipeline_measures_artifacts_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / '<cube>.stl'
            src.write_bytes(write_stl(cube()))
            before = hashlib.sha256(src.read_bytes()).hexdigest()
            out = Path(tmp) / 'out'
            report = process(src, out, {'mode': 'repair', 'samples': 16})
            self.assertEqual(before, hashlib.sha256(src.read_bytes()).hexdigest())
            self.assertEqual(report['source']['sha256'], before)
            self.assertEqual(report['results'][0]['triangles'], 12)
            self.assertIn('repair', report)
            self.assertTrue((out / 'bundle.zip').is_file())
            self.assertIn('&lt;cube&gt;', (out / 'report.html').read_text())
            self.assertNotIn('<cube>', (out / 'report.html').read_text())
            self.assertEqual((out / 'before.msh').read_bytes()[:4], b'MSH1')
            with self.assertRaises((MeshError, FileExistsError)):
                process(src, out, {})
if __name__ == '__main__':
    unittest.main()
