"""Bounded geometry-only file readers and neutral deterministic writers."""
from dataclasses import dataclass
from io import BytesIO
import json
import math
import struct
import zipfile
import xml.etree.ElementTree as ET
MAX_BYTES = 64 * 1024 * 1024
MAX_TRIANGLES = 1000000
MAX_VERTICES = 3000000
MAX_COORD = 1000000000.0
NS = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'


class MeshError(ValueError):
    """An actionable input, geometry or resource-limit error."""

@dataclass
class Mesh:
    vertices: list
    triangles: list


def integer(value, label, minimum=0, maximum=2 ** 31 - 1):
    if isinstance(value, bool) or not isinstance(value, int) or (not minimum <= value <= maximum):
        raise MeshError(f'{label} must be an integer between {minimum} and {maximum}.')
    return value


def finite(value, label, bound=MAX_COORD):
    """Validate numeric range before conversion, including arbitrarily large integers."""
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not numeric or abs(value) > bound or not math.isfinite(value):
        raise MeshError(f'{label} must be finite and within ±{bound:g}.')
    return float(value)



def validate_mesh(mesh):
    if not mesh.vertices or not mesh.triangles:
        raise MeshError('The file has no triangle geometry.')
    if len(mesh.vertices) > MAX_VERTICES or len(mesh.triangles) > MAX_TRIANGLES:
        raise MeshError(f'Geometry limit exceeded: {MAX_VERTICES:,} vertices / {MAX_TRIANGLES:,} triangles.')
    for p in mesh.vertices:
        if len(p) != 3:
            raise MeshError('Positions must contain three coordinates.')
        for x in p:
            finite(x, 'Coordinate')
    for t in mesh.triangles:
        if len(t) != 3:
            raise MeshError('Only triangles are supported.')
        for i in t:
            integer(i, 'Triangle index', 0, len(mesh.vertices) - 1)
    return mesh


def load_mesh(data, filename):
    """Read supported geometry with bounded resources and no external reads."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise MeshError('Input must be nonempty and at most 64 MiB.')
    ext = filename.rsplit('.', 1)[-1].lower()
    try:
        if ext == 'stl':
            m = read_stl(data)
        elif ext == 'obj':
            m = read_obj(data)
        elif ext == 'glb':
            m = read_glb(data)
        else:
            raise MeshError('Supported inputs are STL, triangulated OBJ, and embedded static GLB.')
    except (
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
        struct.error,
        OverflowError,
        RecursionError
    ) as e:
        raise MeshError('Malformed geometry structure, indices, or resource ranges.') from e
    validate_mesh(m)
    return (
        m,
        {
            'format': ext,
            'default_units': 'm' if ext == 'glb' else 'mm',
            'coordinate_system': 'z-up',
            'input_axis_mapping': '(x,-z,y)' if ext == 'glb' else 'unchanged'
        }
    )


def read_stl(data):
    if len(data) >= 84:
        n = struct.unpack_from('<I', data, 80)[0]
        if 84 + 50 * n == len(data):
            if n > MAX_TRIANGLES:
                raise MeshError('STL triangle limit exceeded.')
            v = []
            t = []
            for i in range(n):
                values = struct.unpack_from('<12fH', data, 84 + 50 * i)
                k = len(v)
                v.extend((tuple(values[j:j + 3]) for j in (3, 6, 9)))
                t.append((k, k + 1, k + 2))
            return Mesh(v, t)
    try:
        lines = data.decode('ascii').splitlines()
    except UnicodeDecodeError as e:
        raise MeshError('Malformed binary STL byte count or non-ASCII STL.') from e
    lines = [s.strip() for s in lines if s.strip()]
    if (len(lines) < 2 or lines[0].split()[0].lower() != 'solid'
            or lines[-1].split()[0].lower() != 'endsolid'):
        raise MeshError('Malformed STL: expected matching ASCII solid or exact binary triangle count.')
    v = []
    t = []
    i = 1
    while i < len(lines) - 1:
        if len(t) >= MAX_TRIANGLES:
            raise MeshError('STL triangle limit exceeded.')
        if i + 6 >= len(lines) or len(lines[i].split()) != 5 or lines[i].split()[:2] != [
            'facet',
            'normal'
        ] or (lines[i + 1] != 'outer loop') or (lines[i + 5] != 'endloop') or (lines[i + 6] != 'endfacet'):
            raise MeshError('Malformed ASCII STL facet.')
        try:
            for line in lines[i + 2:i + 5]:
                parts = line.split()
                if len(parts) != 4 or parts[0] != 'vertex':
                    raise ValueError()
                v.append(tuple((float(x) for x in parts[1:])))
        except ValueError as e:
            raise MeshError('Malformed ASCII STL vertex.') from e
        k = len(v) - 3
        t.append((k, k + 1, k + 2))
        i += 7
    return Mesh(v, t)


def read_obj(data):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as e:
        raise MeshError('OBJ must be UTF-8 text.') from e
    v = []
    t = []
    for number, line in enumerate(text.splitlines(), 1):
        parts = line.partition('#')[0].split()
        if not parts:
            continue
        key = parts[0]
        try:
            if key == 'v':
                if len(parts) != 4:
                    raise MeshError('OBJ vertices must be XYZ without projective coordinates or vertex colors.')
                v.append(tuple((float(x) for x in parts[1:])))
                if len(v) > MAX_VERTICES:
                    raise MeshError('OBJ vertex limit exceeded.')
            elif key == 'f':
                if len(parts) != 4:
                    raise MeshError('OBJ faces must be triangles; triangulate polygons before export.')
                indices = []
                for ref in parts[1:]:
                    bits = ref.split('/')
                    if len(bits) > 3 or not bits[0]:
                        raise MeshError('Malformed OBJ face reference.')
                    idx = int(bits[0])
                    idx = idx - 1 if idx > 0 else len(v) + idx
                    integer(idx, 'OBJ vertex index', 0, len(v) - 1)
                    indices.append(idx)
                t.append(tuple(indices))
                if len(t) > MAX_TRIANGLES:
                    raise MeshError('OBJ triangle limit exceeded.')
            elif key in ('vn', 'vt', 'o', 'g', 's', 'usemtl'):
                continue
            elif key in ('mtllib', 'maplib', 'call', 'csh'):
                raise MeshError('OBJ external files and commands are not supported; export geometry only.')
            else:
                raise MeshError(f'Unsupported OBJ record {key!r}.')
        except (ValueError, OverflowError) as e:
            raise MeshError(f'OBJ line {number}: {e}') from e
    return Mesh(v, t)


def matmul(a, b):
    return [sum((a[r * 4 + k] * b[k * 4 + c] for k in range(4))) for r in range(4) for c in range(4)]
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def node_matrix(n):
    if 'matrix' in n:
        if any((k in n for k in ('translation', 'rotation', 'scale'))):
            raise MeshError('GLB node mixes matrix and TRS.')
        a = n['matrix']
        if not isinstance(a, list) or len(a) != 16:
            raise MeshError('GLB matrix must contain 16 numbers.')
        a = [finite(x, 'GLB matrix') for x in a]
        m = [a[c * 4 + r] for r in range(4) for c in range(4)]
        if any((abs(m[i] - v) > 1e-08 for i, v in ((12, 0), (13, 0), (14, 0), (15, 1)))):
            raise MeshError('GLB node matrix must be affine.')
        return m
    arrays = []
    for key, default in [('translation', [0, 0, 0]), ('rotation', [0, 0, 0, 1]), ('scale', [1, 1, 1])]:
        value = n.get(key, default)
        if not isinstance(value, list) or len(value) != len(default):
            raise MeshError(f'Invalid GLB node {key}.')
        arrays.append([finite(x, f'GLB {key}') for x in value])
    p, q, s = arrays
    x, y, z, w = q
    if abs(sum((i * i for i in q)) - 1) > 1e-05:
        raise MeshError('GLB quaternion must be normalized.')
    r = [
        1 - 2 * (y * y + z * z),
        2 * (x * y - z * w),
        2 * (x * z + y * w),
        p[0],
        2 * (x * y + z * w),
        1 - 2 * (x * x + z * z),
        2 * (y * z - x * w),
        p[1],
        2 * (x * z - y * w),
        2 * (y * z + x * w),
        1 - 2 * (x * x + y * y),
        p[2],
        0,
        0,
        0,
        1
    ]
    for row in range(3):
        for col in range(3):
            r[row * 4 + col] *= s[col]
    return r


def determinant(m):
    return m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8]) + m[2] * (m[4] * m[9] - m[5] * m[8])


def read_glb(data):
    """Apply a bounded static GLB scene graph with affine world transforms."""
    if len(data) < 20 or data[:4] != b'glTF':
        raise MeshError('Malformed GLB header.')
    version, total = struct.unpack_from('<II', data, 4)
    if version != 2 or total != len(data):
        raise MeshError('Only exact-length GLB 2.0 is supported.')
    chunks = []
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise MeshError('Truncated GLB chunk header.')
        length, kind = struct.unpack_from('<I4s', data, offset)
        offset += 8
        if length % 4 or offset + length > len(data):
            raise MeshError('Malformed GLB chunk range.')
        chunks.append((kind, data[offset:offset + length]))
        offset += length
    if not chunks or chunks[0][0] != b'JSON' or len(chunks) > 2 or (len(chunks) == 2 and chunks[1][0] != b'BIN\x00'):
        raise MeshError('GLB requires one JSON chunk and optional embedded BIN chunk.')
    if len(chunks[0][1]) > 8 * 1024 * 1024:
        raise MeshError('GLB JSON chunk exceeds 8 MiB metadata limit.')

    def reject_constant(s):
        raise MeshError('GLB JSON contains nonfinite numbers.')

    def unique_pairs(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise MeshError('GLB JSON contains duplicate keys.')
            d[k] = v
        return d
    try:
        d = json.loads(chunks[0][1], parse_constant=reject_constant, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeDecodeError, RecursionError) as e:
        raise MeshError(f'Invalid GLB JSON: {e}') from e
    if not isinstance(d, dict) or d.get('asset', {}).get('version') != '2.0':
        raise MeshError('GLB asset version must be 2.0.')
    for key in ('animations', 'skins', 'extensionsRequired', 'extensionsUsed'):
        if d.get(key):
            raise MeshError(f'GLB {key} are unsupported; export an uncompressed static mesh.')
    buffers = d.get('buffers', [])
    raw = chunks[1][1] if len(chunks) == 2 else b''
    if len(buffers) != 1 or 'uri' in buffers[0]:
        raise MeshError('GLB must use a single embedded buffer; external references are forbidden.')
    declared = integer(buffers[0].get('byteLength'), 'GLB buffer byteLength', 0, MAX_BYTES)
    if not declared <= len(raw) <= declared + 3:
        raise MeshError('GLB embedded buffer length mismatch.')
    for im in d.get('images', []):
        if 'uri' in im:
            raise MeshError('GLB image URIs are forbidden; embed images in bufferViews.')
    views = d.get('bufferViews', [])
    accessors = d.get('accessors', [])
    if len(views) > 10000 or len(accessors) > 10000:
        raise MeshError('GLB accessor resource limit exceeded.')
    for view in views:
        if not isinstance(view, dict) or view.get('buffer', 0) != 0 or view.get('extensions'):
            raise MeshError('Unsupported GLB bufferView.')
        start = integer(view.get('byteOffset', 0), 'GLB byteOffset', 0, declared)
        length = integer(view.get('byteLength'), 'GLB byteLength', 0, declared)
        if start + length > declared:
            raise MeshError('GLB bufferView exceeds buffer.')
        if 'byteStride' in view:
            stride = integer(view['byteStride'], 'GLB stride', 4, 252)
            if stride % 4:
                raise MeshError('GLB bufferView byteStride must be a multiple of four.')
    layouts = {}
    types = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
    components = {
        5120: ('b', 1),
        5121: ('B', 1),
        5122: ('h', 2),
        5123: ('H', 2),
        5125: ('I', 4),
        5126: ('f', 4)
    }
    for ai, a in enumerate(accessors):
        if not isinstance(a, dict) or 'sparse' in a or a.get('extensions'):
            raise MeshError('Sparse or extended GLB accessors are unsupported.')
        vi = integer(a.get('bufferView'), 'GLB accessor bufferView', 0, len(views) - 1)
        view = views[vi]
        if a.get('componentType') not in components or a.get('type') not in types:
            raise MeshError('Unsupported GLB accessor representation.')
        fmt, width = components[a['componentType']]
        components_n = types[a['type']]
        element = components_n * width
        count = integer(a.get('count'), 'GLB accessor count', 1, MAX_VERTICES * 3)
        stride = view.get('byteStride', element)
        start = integer(a.get('byteOffset', 0), 'GLB accessor offset', 0, declared)
        if stride < element or stride % width or start % width or (view.get(
            'byteOffset',
            0
        ) + start) % width or (start + (count - 1) * stride + element > view['byteLength']):
            raise MeshError('GLB accessor range/stride/alignment is invalid.')
        layouts[ai] = (a, view.get('byteOffset', 0) + start, stride, '<' + fmt * components_n, count)

    def read_accessor(ai, typ, component):
        integer(ai, 'GLB accessor index', 0, len(accessors) - 1)
        a, start, stride, fmt, count = layouts[ai]
        if a['type'] != typ or a['componentType'] not in component or a.get('normalized', False):
            raise MeshError('Unsupported GLB position/index accessor type.')
        return [struct.unpack_from(fmt, raw, start + i * stride) for i in range(count)]
    meshes = d.get('meshes', [])
    nodes = d.get('nodes', [])
    scenes = d.get('scenes', [])
    if not nodes or len(nodes) > 4096 or len(meshes) > 4096 or (len(scenes) > 4096):
        raise MeshError('GLB scene resource limit exceeded or scene missing.')
    if not scenes:
        raise MeshError('GLB requires an explicit scene.')
    si = integer(d.get('scene', 0), 'GLB scene', 0, len(scenes) - 1)
    roots = scenes[si].get('nodes', [])
    if not isinstance(roots, list) or len(roots) > 4096:
        raise MeshError('Invalid GLB scene roots.')
    for n in nodes:
        if not isinstance(n, dict) or any((k in n for k in ('skin', 'weights'))) or n.get('extensions'):
            raise MeshError('Only static unextended GLB nodes are supported.')
        children = n.get('children', [])
        if not isinstance(children, list) or len(children) > 4096:
            raise MeshError('Invalid GLB node children.')
        for child in children:
            integer(child, 'GLB child node', 0, len(nodes) - 1)
    v = []
    t = []
    visited = set()
    stack = [(i, IDENTITY, 0, frozenset()) for i in reversed(roots)]
    while stack:
        ni, parent, depth, ancestors = stack.pop()
        integer(ni, 'GLB root node', 0, len(nodes) - 1)
        if ni in ancestors or ni in visited or depth > 64:
            raise MeshError('GLB cyclic/multiply-parented node graph or depth limit exceeded.')
        visited.add(ni)
        n = nodes[ni]
        world = matmul(parent, node_matrix(n))
        det = determinant(world)
        if not math.isfinite(det) or abs(det) < 1e-18:
            raise MeshError('GLB node transform is singular or extreme.')
        if 'mesh' in n:
            mi = integer(n['mesh'], 'GLB mesh index', 0, len(meshes) - 1)
            mesh = meshes[mi]
            if mesh.get('weights'):
                raise MeshError('GLB morph targets are unsupported.')
            primitives = mesh.get('primitives', [])
            if not isinstance(primitives, list) or len(primitives) > 4096:
                raise MeshError('GLB primitive limit exceeded.')
            for p in primitives:
                if p.get('mode', 4) != 4 or p.get('targets') or p.get('extensions'):
                    raise MeshError('Only uncompressed static GLB TRIANGLES are supported.')
                attrs = p.get('attributes', {})
                if not isinstance(attrs, dict) or 'POSITION' not in attrs or any((k.startswith((
                    'JOINTS',
                    'WEIGHTS'
                )) for k in attrs)):
                    raise MeshError('GLB primitive needs static POSITION geometry.')
                for ai in attrs.values():
                    integer(ai, 'GLB attribute accessor', 0, len(accessors) - 1)
                pa = accessors[attrs['POSITION']]
                if pa.get('count', 0) + len(v) > MAX_VERTICES:
                    raise MeshError('GLB instanced vertex limit exceeded.')
                pos = read_accessor(attrs['POSITION'], 'VEC3', {5126})
                if 'indices' in p:
                    ia = integer(p['indices'], 'GLB index accessor', 0, len(accessors) - 1)
                    if accessors[ia]['count'] // 3 + len(t) > MAX_TRIANGLES:
                        raise MeshError('GLB triangle limit exceeded.')
                    ix = [a[0] for a in read_accessor(ia, 'SCALAR', {5121, 5123, 5125})]
                else:
                    ix = list(range(len(pos)))
                if len(ix) % 3 or len(t) + len(ix) // 3 > MAX_TRIANGLES:
                    raise MeshError('GLB triangle index count is invalid or over limit.')
                start = len(v)
                for point in pos:
                    point = tuple((finite(c, 'GLB coordinate') for c in point))
                    q = tuple((sum((world[r * 4 + k] * point[k] for k in range(3))) + world[r * 4 + 3] for r in range(3)))
                    v.append((q[0], -q[2], q[1]))
                for k in range(0, len(ix), 3):
                    tri = ix[k:k + 3]
                    for x in tri:
                        integer(x, 'GLB triangle index', 0, len(pos) - 1)
                    if det < 0:
                        tri[1], tri[2] = (tri[2], tri[1])
                    t.append(tuple((start + x for x in tri)))
        ancestors = ancestors | {ni}
        for child in reversed(n.get('children', [])):
            stack.append((child, world, depth + 1, ancestors))
    return Mesh(v, t)


def write_stl(mesh):
    """Emit binary millimeter geometry with computed facet normals."""
    validate_mesh(mesh)
    from .geometry import cross, sub, norm
    data = bytearray(b'Mesh to Print 0.1.0; millimeters; geometry only'.ljust(80, b'\x00'))
    data.extend(struct.pack('<I', len(mesh.triangles)))
    for t in mesh.triangles:
        a, b, c = [mesh.vertices[i] for i in t]
        n = cross(sub(b, a), sub(c, a))
        length = norm(n)
        n = tuple((x / length for x in n)) if length else (0, 0, 0)
        try:
            data.extend(struct.pack('<12fH', *n + a + b + c, 0))
        except (OverflowError, struct.error) as e:
            raise MeshError('Geometry exceeds float32 STL range.') from e
    return bytes(data)


def zip_bytes(files):
    out = BytesIO()
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 33188 << 16
            z.writestr(info, content)
    return out.getvalue()


def write_3mf(mesh):
    """Emit a deterministic neutral millimeter Core geometry package."""
    validate_mesh(mesh)
    verts = ''.join(('<vertex x="%.17g" y="%.17g" z="%.17g"/>' % p for p in mesh.vertices))
    tris = ''.join(('<triangle v1="%d" v2="%d" v3="%d"/>' % t for t in mesh.triangles))
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<model unit="millimeter" xml:lang="en-US" xmlns="{NS}">'
        '<resources><object id="1" type="model"><mesh>'
        f'<vertices>{verts}</vertices><triangles>{tris}</triangles>'
        '</mesh></object></resources><build><item objectid="1"/></build></model>'
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" '
        'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        '</Relationships>'
    )
    return zip_bytes({'[Content_Types].xml': types, '_rels/.rels': rels, '3D/3dmodel.model': model})


def read_3mf(data):
    """Bounded round-trip verifier for this program's neutral Core geometry subset."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            infos = z.infolist()
            expected = {'[Content_Types].xml', '_rels/.rels', '3D/3dmodel.model'}
            if len(infos) != 3 or {i.filename for i in infos} != expected or sum((i.file_size for i in infos)) > 512 * 1024 * 1024:
                raise MeshError('Unsupported or over-limit 3MF archive.')
            text = z.read('3D/3dmodel.model')
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError) as e:
        raise MeshError('Invalid 3MF archive.') from e
    if b'<!' in text:
        raise MeshError('3MF DTDs/entities are forbidden.')
    try:
        root = ET.fromstring(text)
        prefix = '{' + NS + '}'
        if root.tag != prefix + 'model' or root.get('unit') != 'millimeter':
            raise MeshError('Unexpected 3MF model unit.')
        objs = root.findall(prefix + 'resources/' + prefix + 'object')
        items = root.findall(prefix + 'build/' + prefix + 'item')
        if len(objs) != 1 or objs[0].get('id') != '1' or len(items) != 1 or (items[0].attrib != {'objectid': '1'}):
            raise MeshError('Unsupported 3MF object/build structure.')
        verts = objs[0].findall(prefix + 'mesh/' + prefix + 'vertices/' + prefix + 'vertex')
        tris = objs[0].findall(prefix + 'mesh/' + prefix + 'triangles/' + prefix + 'triangle')
        if len(verts) > MAX_VERTICES or len(tris) > MAX_TRIANGLES:
            raise MeshError('3MF geometry limit exceeded.')
        v = [tuple((float(p.attrib[k]) for k in ('x', 'y', 'z'))) for p in verts]
        t = [tuple((int(p.attrib[k]) for k in ('v1', 'v2', 'v3'))) for p in tris]
        return validate_mesh(Mesh(v, t))
    except (ET.ParseError, KeyError, ValueError, OverflowError) as e:
        raise MeshError(f'Invalid 3MF geometry: {e}') from e
