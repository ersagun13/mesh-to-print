"""Physical-space topology diagnostics and deliberately conservative repairs."""
from collections import defaultdict, deque
import math
import time
from .formats import Mesh, MeshError, finite, validate_mesh
# mm; diagnostic welding never changes original output
DIAGNOSTIC_TOLERANCE = 1e-05
AREA_EPS = 1e-12
MIN_WELD_TOLERANCE = 1e-9


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a):
    return math.sqrt(dot(a, a))


def bounds(vertices):
    return (
        [min((p[i] for p in vertices)) for i in range(3)],
        [max((p[i] for p in vertices)) for i in range(3)]
    )


class DSU:

    def __init__(self, n):
        self.p = list(range(n))
        self.rank = [0] * n

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        a = self.find(a)
        b = self.find(b)
        if a == b:
            return
        if self.rank[a] < self.rank[b]:
            a, b = (b, a)
        self.p[b] = a
        if self.rank[a] == self.rank[b]:
            self.rank[a] += 1


def weld(mesh, tolerance):
    """Deterministic nontransitive nearest-representative Euclidean weld."""
    tolerance = finite(tolerance, 'Weld tolerance', 1.0)
    if tolerance < MIN_WELD_TOLERANCE:
        raise MeshError('Weld tolerance must be at least 0.000000001 mm.')
    buckets = defaultdict(list)
    exact = {}
    vertices = []
    mapping = []
    representatives = []
    offsets = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]
    tol2 = tolerance * tolerance
    for oi, p in enumerate(mesh.vertices):
        p = tuple(p)
        if p in exact:
            mapping.append(exact[p])
            continue
        key = tuple((math.floor(x / tolerance) for x in p))
        found = None
        # A crowded tolerance cell can otherwise make adversarial welding quadratic.
        for delta in offsets:
            cell = tuple((key[i] + delta[i] for i in range(3)))
            for idx in buckets.get(cell, ()):
                if dot(sub(p, vertices[idx]), sub(p, vertices[idx])) <= tol2:
                    if found is None or idx < found:
                        found = idx
        if found is None:
            found = len(vertices)
            vertices.append(p)
            representatives.append(oi)
            buckets[key].append(found)
            if len(buckets[key]) > 16:
                raise MeshError('Weld spatial density exceeds the bounded diagnostic limit.')
        exact[p] = found
        mapping.append(found)
    return (Mesh(vertices, [tuple((mapping[i] for i in t)) for t in mesh.triangles]), representatives)


def referenced_mesh(mesh):
    """Remove positions unused by every triangle before physical measurements.

    This changes only representation, not the triangle surface. The caller
    discloses removed-record counts while retaining original source bytes.
    """
    used = sorted({index for triangle in mesh.triangles for index in triangle})
    if len(used) == len(mesh.vertices):
        return mesh
    remap = {old: new for new, old in enumerate(used)}
    return Mesh([mesh.vertices[index] for index in used],
                [tuple(remap[index] for index in triangle) for triangle in mesh.triangles])


def scale_mesh(mesh, units, size):
    """Convert explicit input units or target longest dimension into millimeters."""
    source_position_records = len(mesh.vertices)
    mesh = referenced_mesh(mesh)
    factor = {'mm': 1.0, 'cm': 10.0, 'm': 1000.0, 'in': 25.4}[units]
    method = 'input_units'
    if size is not None:
        lo, hi = bounds(mesh.vertices)
        longest = max((hi[i] - lo[i] for i in range(3)))
        if longest <= 0:
            raise MeshError('Cannot set physical size for geometry with no extent.')
        factor = size / longest
        method = 'target_longest_dimension'
    points = [tuple((x * factor for x in p)) for p in mesh.vertices]
    if any((not math.isfinite(x) or abs(x) > 10000000.0 for p in points for x in p)):
        raise MeshError('Scaled positions exceed ±10,000,000 mm; recenter or choose a smaller size.')
    return (
        Mesh(points, list(mesh.triangles)),
        {
            'input_units': units,
            'method': method,
            'factor_to_mm': factor,
            'target_longest_dimension_mm': size,
            'source_position_records': source_position_records,
            'referenced_position_records': len(mesh.vertices),
            'removed_unreferenced_position_records': source_position_records - len(mesh.vertices)
        }
    )


def analyze_topology(mesh, tolerance=DIAGNOSTIC_TOLERANCE):
    """Measure geometric edge incidence and vertex links after disclosed diagnostic welding."""
    if tolerance == 0:
        diag, reps = (mesh, list(range(len(mesh.vertices))))
    else:
        diag, reps = weld(mesh, tolerance)
    v = diag.vertices
    f = diag.triangles
    edges = defaultdict(list)
    valid = []
    degenerate = []
    duplicate = []
    seen = {}
    incident = defaultdict(list)
    for fi, t in enumerate(f):
        a, b, c = [v[i] for i in t]
        if len(set(t)) < 3 or norm(cross(sub(b, a), sub(c, a))) <= AREA_EPS:
            degenerate.append(fi)
            continue
        valid.append(fi)
        key = tuple(sorted(t))
        if key in seen:
            duplicate.append(fi)
        else:
            seen[key] = fi
        for i in range(3):
            x, y = (t[i], t[(i + 1) % 3])
            edges[min(x, y), max(x, y)].append((fi, 1 if x < y else -1))
            incident[t[i]].append((fi, t[(i + 1) % 3], t[(i + 2) % 3]))
    edsu = DSU(len(f))
    vdsu = DSU(len(v))
    boundary = []
    nonmanifold = []
    conflicts = []
    adj = defaultdict(list)
    for e, entries in edges.items():
        for fi, _ in entries[1:]:
            edsu.union(entries[0][0], fi)
        vdsu.union(*e)
        if len(entries) == 1:
            boundary.append(e)
        elif len(entries) > 2:
            nonmanifold.append(e)
        if len(entries) == 2:
            (a, sa), (b, sb) = entries
            adj[a].append((b, sa == sb))
            adj[b].append((a, sa == sb))
            if sa == sb:
                conflicts.append(e)
    bad_vertices = []
    for vi, entries in incident.items():
        neigh = {}
        degrees = defaultdict(int)
        for _, a, b in entries:
            if a not in neigh:
                neigh[a] = len(neigh)
            if b not in neigh:
                neigh[b] = len(neigh)
            degrees[a] += 1
            degrees[b] += 1
        link = DSU(len(neigh))
        for _, a, b in entries:
            link.union(neigh[a], neigh[b])
        components = len({link.find(i) for i in range(len(neigh))})
        if components != 1 or any((n > 2 for n in degrees.values())) or sum((n == 1 for n in degrees.values())) not in (
            0,
            2
        ):
            bad_vertices.append(vi)
    groups = defaultdict(list)
    for fi in valid:
        groups[edsu.find(fi)].append(fi)
    topology = {
        'diagnostic_weld_tolerance_mm': tolerance,
        'diagnostic_vertices': len(v),
        'source_vertices': len(mesh.vertices),
        'unused_vertices': len(v) - len(incident),
        'boundary_edges': len(boundary),
        'nonmanifold_edges': len(nonmanifold),
        'winding_conflicts': len(conflicts),
        'degenerate_faces': len(degenerate),
        'duplicate_faces': len(duplicate),
        'nonmanifold_vertices': len(bad_vertices),
        'edge_components': len(groups),
        'vertex_components': len({vdsu.find(i) for i in incident}),
        'method': 'Euclidean representative welding for diagnostics; edge incidence and vertex-link graph checks. Degenerate faces excluded from incidence; duplicate faces retained.'
    }
    return {
        'mesh': diag,
        'representatives': reps,
        'topology': topology,
        'groups': list(groups.values()),
        'boundary': boundary,
        'nonmanifold': nonmanifold,
        'conflicts': conflicts,
        'degenerate': degenerate,
        'duplicate': duplicate,
        'bad_vertices': bad_vertices,
        'adjacency': adj
    }


def volume_report(state):
    """Return a conditional divergence-theorem volume only for eligible shell topology."""
    top = state['topology']
    m = state['mesh']
    volumes = []
    boxes = []
    face_sign = {}
    assumptions = [
        'Closed consistently wound two-manifold shells after diagnostic welding.',
        'Triangle self-intersections and coplanar overlaps are not tested; volume is conditional on their absence.',
        'Multiple shells are aggregated only when their axis-aligned bounding boxes are disjoint.'
    ]
    invalid = any((top[k] for k in (
        'boundary_edges',
        'nonmanifold_edges',
        'winding_conflicts',
        'degenerate_faces',
        'duplicate_faces',
        'nonmanifold_vertices'
    )))
    if invalid or not state['groups']:
        return (
            {
                'status': 'unavailable',
                'volume_mm3': None,
                'signed_volume_mm3': None,
                'reason': 'Topology is open, degenerate, duplicated or inconsistent.',
                'assumptions': assumptions
            },
            face_sign
        )
    for group in state['groups']:
        origin = m.vertices[m.triangles[group[0]][0]]
        values = []
        indices = set()
        for fi in group:
            tri = m.triangles[fi]
            indices.update(tri)
            a, b, c = [sub(m.vertices[i], origin) for i in tri]
            values.append(dot(a, cross(b, c)) / 6)
        signed = math.fsum(values)
        volumes.append(signed)
        boxes.append(bounds([m.vertices[i] for i in indices]))
        for fi in group:
            face_sign[fi] = 1 if signed >= 0 else -1
    if any((abs(x) <= 1e-15 for x in volumes)):
        return (
            {
                'status': 'unavailable',
                'volume_mm3': None,
                'signed_volume_mm3': None,
                'reason': 'At least one closed shell has effectively zero signed volume.',
                'shell_signed_volumes_mm3': volumes,
                'assumptions': assumptions
            },
            face_sign
        )
    # Avoid O(number_of_shells²): reject uncertain aggregation after a modest exact cap.
    if len(boxes) > 128:
        return (
            {
                'status': 'unavailable',
                'volume_mm3': None,
                'signed_volume_mm3': None,
                'reason': 'More than 128 shells: overlap/nesting aggregation not assessed.',
                'shell_count': len(boxes),
                'assumptions': assumptions
            },
            face_sign
        )
    for i, (lo, hi) in enumerate(boxes):
        for lo2, hi2 in boxes[:i]:
            if not any((hi[j] < lo2[j] - DIAGNOSTIC_TOLERANCE or hi2[j] < lo[j] - DIAGNOSTIC_TOLERANCE for j in range(3))):
                return (
                    {
                        'status': 'unavailable',
                        'volume_mm3': None,
                        'signed_volume_mm3': None,
                        'reason': 'Shell bounding boxes overlap or nest. Material volume requires a robust containment/intersection test.',
                        'shell_signed_volumes_mm3': volumes,
                        'assumptions': assumptions
                    },
                    face_sign
                )
    return (
        {
            'status': 'conditional',
            'volume_mm3': math.fsum((abs(x) for x in volumes)),
            'signed_volume_mm3': math.fsum(volumes),
            'shell_signed_volumes_mm3': volumes,
            'inward_shells': sum((x < 0 for x in volumes)),
            'assumptions': assumptions
        },
        face_sign
    )


class RayBudget(Exception):
    pass


class BVH:
    """Median-split AABB tree with an explicit per-query visit bound."""

    def __init__(self, mesh):
        self.mesh = mesh
        self.boxes = []
        self.centers = []
        for tri in mesh.triangles:
            lo, hi = bounds([mesh.vertices[i] for i in tri])
            self.boxes.append((lo, hi))
            self.centers.append(tuple(((lo[i] + hi[i]) / 2 for i in range(3))))
        self.root = self.build(list(range(len(mesh.triangles))))

    def build(self, ids):
        lo = tuple((min((self.boxes[i][0][k] for i in ids)) for k in range(3)))
        hi = tuple((max((self.boxes[i][1][k] for i in ids)) for k in range(3)))
        if len(ids) <= 8:
            return (lo, hi, ids, None, None)
        axis = max(range(3), key=lambda a: hi[a] - lo[a])
        ids.sort(key=lambda i: self.centers[i][axis])
        mid = len(ids) // 2
        return (lo, hi, None, self.build(ids[:mid]), self.build(ids[mid:]))

    @staticmethod
    def hitbox(lo, hi, origin, direction, maximum):
        low = 0.0
        high = maximum
        for k in range(3):
            if abs(direction[k]) < 1e-15:
                if origin[k] < lo[k] - 1e-10 or origin[k] > hi[k] + 1e-10:
                    return False
            else:
                a = (lo[k] - origin[k]) / direction[k]
                b = (hi[k] - origin[k]) / direction[k]
                low = max(low, min(a, b))
                high = min(high, max(a, b))
                if high < low:
                    return False
        return True

    def cast(self, origin, direction, skip):
        stack = [self.root]
        best = float('inf')
        tests = 0
        while stack:
            tests += 1
            if tests > 100000:
                raise RayBudget()
            lo, hi, ids, left, right = stack.pop()
            if not self.hitbox(lo, hi, origin, direction, best):
                continue
            if ids is None:
                stack.extend((left, right))
                continue
            for fi in ids:
                if fi == skip:
                    continue
                a, b, c = [self.mesh.vertices[i] for i in self.mesh.triangles[fi]]
                e1 = sub(b, a)
                e2 = sub(c, a)
                h = cross(direction, e2)
                det = dot(e1, h)
                if abs(det) < 1e-14:
                    continue
                inv = 1 / det
                s = sub(origin, a)
                u = dot(s, h) * inv
                if u < -1e-09 or u > 1 + 1e-09:
                    continue
                q = cross(s, e1)
                w = dot(direction, q) * inv
                if w < -1e-09 or u + w > 1 + 1e-09:
                    continue
                distance = dot(e2, q) * inv
                if 1e-10 < distance < best:
                    best = distance
        return best if math.isfinite(best) else None


def thickness_report(state, volume, face_sign, options):
    """Measure bounded normal-ray samples; never imply a certified minimum wall."""
    limit = 512
    requested = options['samples']
    m = state['mesh']
    r = {
        'status': 'not_assessed',
        'method': 'Deterministic evenly indexed triangle-centroid inward-normal rays with median BVH acceleration.',
        'requested_samples': requested,
        'attempted': 0,
        'valid_hits': 0,
        'minimum_observed_mm': None,
        'coverage_ratio': None,
        'threshold_mm': options['wall'],
        'sample_cap': limit,
        'limitations': [
            'Observed inward-normal distances are samples, not a certified whole-mesh minimum wall thickness.',
            'Samples are evenly spaced by triangle index, not area-weighted; thin features between samples can be missed.',
            'Coverage ratio means valid hits / attempted rays, not percentage of surface covered.',
            'Self-intersections and material nesting are not certified.'
        ]
    }
    if requested == 0:
        r['reason'] = 'Sampling disabled by user.'
        return r
    if volume['status'] != 'conditional':
        r['reason'] = 'Requires closed consistent nondegenerate nonoverlapping-shell geometry.'
        return r
    if len(m.triangles) > 150000:
        r['reason'] = 'Thickness BVH triangle cap is 150,000; analysis remains available.'
        return r
    count = min(requested, limit, len(m.triangles))
    start = time.monotonic()
    tree = BVH(m)
    values = []
    truncated = False
    lo, hi = bounds(m.vertices)
    eps = max(max((hi[i] - lo[i] for i in range(3))) * 1e-09, 1e-09)
    for k in range(count):
        if time.monotonic() - start > 15:
            truncated = True
            break
        fi = k * len(m.triangles) // count
        tri = m.triangles[fi]
        a, b, c = [m.vertices[i] for i in tri]
        n = cross(sub(b, a), sub(c, a))
        length = norm(n)
        if length <= AREA_EPS:
            continue
        inward = tuple((-x / length * face_sign[fi] for x in n))
        center = tuple(((a[i] + b[i] + c[i]) / 3 for i in range(3)))
        origin = tuple((center[i] + inward[i] * eps for i in range(3)))
        r['attempted'] += 1
        try:
            hit = tree.cast(origin, inward, fi)
        except RayBudget:
            truncated = True
            break
        if hit is not None:
            values.append(hit + eps)
    r.update(
        status='sampled' if values else 'indeterminate',
        valid_hits=len(values),
        minimum_observed_mm=min(values) if values else None,
        coverage_ratio=len(values) / r['attempted'] if r['attempted'] else None,
        below_threshold_samples=sum((x < options['wall'] for x in values)),
        truncated=truncated,
        elapsed_seconds=round(time.monotonic() - start, 6)
    )
    if truncated:
        r['limitations'].append('Time or BVH traversal budget reached; only completed rays are reported.')
    if requested > limit:
        r['limitations'].append('Requested sample count capped at 512 rays.')
    return r


def inspect_mesh(mesh, options):
    """Combine topology, conditional volume and chosen-orientation physical diagnostics."""
    validate_mesh(mesh)
    lo, hi = bounds(mesh.vertices)
    dims = [hi[i] - lo[i] for i in range(3)]
    state = analyze_topology(mesh)
    top = state['topology']
    volume, signs = volume_report(state)
    bed = options['bed']
    fits = all((dims[i] <= bed[i] + 1e-08 for i in range(3)))
    build = {
        'bed_mm': bed,
        'dimensions_mm': dims,
        'fits': fits,
        'method': 'Axis-aligned dimensions in chosen orientation; translation to bed origin permitted; no rotation search.',
        'minimum_z_mm': lo[2],
        'translation_to_bed_mm': [-lo[0], -lo[1], -lo[2]],
        'bed_contact_faces': 0
    }
    over = []
    area = 0.0
    total = 0.0
    angle = options['overhang']
    threshold = math.sin(math.radians(angle))
    bed_eps = max(1e-05, max(dims) * 1e-07)
    for fi, t in enumerate(mesh.triangles):
        a, b, c = [mesh.vertices[i] for i in t]
        normal = cross(sub(b, a), sub(c, a))
        length = norm(normal)
        if length <= AREA_EPS:
            continue
        total += length / 2
        if all((abs(mesh.vertices[i][2] - lo[2]) <= bed_eps for i in t)):
            build['bed_contact_faces'] += 1
            continue
        if -normal[2] / length > threshold + 1e-12:
            over.append(fi)
            area += length / 2
    overhang = {
        'status': 'heuristic' if not top['winding_conflicts'] else 'indeterminate',
        'angle_from_horizontal_degrees': angle,
        'faces': len(over),
        'area_mm2': area,
        'surface_area_mm2': total,
        'bed_contact_excluded': True,
        'method': 'Chosen +Z orientation. Downward faces closer to horizontal than threshold are flagged. Winding controls normal direction; no support/contact planning.'
    }
    thickness = thickness_report(state, volume, signs, options)
    findings = []

    def add(id, severity, title, detail, count=None):
        f = {'id': id, 'severity': severity, 'title': title, 'detail': detail}
        if count is not None:
            f['count'] = count
        findings.append(f)
    for key, title in [
        ('boundary_edges', 'Open boundary edges'),
        ('nonmanifold_edges', 'Nonmanifold edges'),
        ('winding_conflicts', 'Adjacent face winding conflicts'),
        ('degenerate_faces', 'Degenerate triangles'),
        ('duplicate_faces', 'Duplicate triangles'),
        ('nonmanifold_vertices', 'Nonmanifold or bowtie vertices')
    ]:
        if top[key]:
            add(
                key,
                'error',
                title,
                'Measured on a diagnostic weld at 0.00001 mm; original geometry is unchanged.',
                top[key]
            )
    if top['edge_components'] > 1:
        add(
            'components',
            'warning',
            'Multiple edge-connected components',
            'Components are retained. Separate parts or nested cavities may be intentional.',
            top['edge_components']
        )
    if not fits:
        add(
            'bed_fit',
            'error',
            'Build envelope exceeded',
            'Chosen orientation exceeds at least one build-envelope dimension.'
        )
    if volume.get('inward_shells'):
        add(
            'inward_shells',
            'warning',
            'Inward-wound closed shells',
            'Global shell orientation is retained; check intended material/cavity orientation.',
            volume['inward_shells']
        )
    if volume['status'] == 'unavailable':
        add('volume_unavailable', 'warning', 'Material volume unavailable', volume['reason'])
    if thickness['minimum_observed_mm'] is not None and thickness['minimum_observed_mm'] < options['wall']:
        add(
            'thin_samples',
            'warning',
            'Sampled distance below wall threshold',
            'Observed normal-ray distances require review in a slicer; sampling is not a certification.',
            thickness.get('below_threshold_samples', 0)
        )
    if over:
        add(
            'overhang',
            'warning',
            'Orientation may need supports',
            'Downward normal angle heuristic excludes bed-contact faces; unsupported span and slicer support decisions are not evaluated.',
            len(over)
        )
    add(
        'self_intersection',
        'info',
        'Self-intersections not assessed',
        'No robust triangle/coplanar intersection predicates are implemented.'
    )
    add(
        'minimum_wall',
        'info',
        'Whole-mesh minimum wall not certified',
        'Only eligible closed geometry is sampled; minimum wall and print success remain unknown.'
    )
    problem_faces = set(state['degenerate'] + state['duplicate'] + over)
    issue_edges = state['boundary'] + state['nonmanifold'] + state['conflicts']
    representatives = state['representatives']
    return {
        'summary': {
            'vertices': len(mesh.vertices),
            'triangles': len(mesh.triangles),
            'dimensions': dims,
            'units': 'mm'
        },
        'bounds': {'minimum': lo, 'maximum': hi},
        'topology': top,
        'volume': volume,
        'thickness': thickness,
        'build_volume': build,
        'overhang': overhang,
        'self_intersection': {'status': 'not_assessed'},
        'minimum_wall_certification': {'status': 'unknown'},
        'findings': findings,
        'issue_faces': sorted(problem_faces)[:5000],
        'issue_edges': [[representatives[a], representatives[b]] for a, b in issue_edges[:5000]],
        'issue_truncation': {
            'faces': max(0, len(problem_faces) - 5000),
            'edges': max(0, len(issue_edges) - 5000)
        }
    }


def clean_mesh(mesh, tolerance, fill_holes_mm=None):
    """Apply only selected weld, duplicate removal, local winding and optional hole fill."""
    validate_mesh(mesh)
    candidate, _ = weld(mesh, tolerance)
    v = candidate.vertices
    f = []
    seen = set()
    deg = 0
    dup = 0
    for t in candidate.triangles:
        a, b, c = [v[i] for i in t]
        if len(set(t)) < 3 or norm(cross(sub(b, a), sub(c, a))) <= AREA_EPS:
            deg += 1
            continue
        key = tuple(sorted(t))
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        f.append(t)
    if not f:
        raise MeshError('Cleaning would remove every triangle; no candidate was exported.')
    candidate = Mesh(v, f)
    state = analyze_topology(candidate, tolerance=0)
    adj = state['adjacency']
    assigned = {}
    flips = set()
    for start in range(len(f)):
        if start in assigned:
            continue
        assigned[start] = False
        queue = deque([start])
        group = []
        while queue:
            cur = queue.popleft()
            group.append(cur)
            for other, different in adj.get(cur, ()):
                if other not in assigned:
                    assigned[other] = assigned[cur] ^ different
                    queue.append(other)
        # Preserve dominant existing orientation, including intentional inward nested shells.
        invert = sum((assigned[i] for i in group)) > len(group) / 2
        flips.update((i for i in group if assigned[i] ^ invert))
    f = [(t[0], t[2], t[1]) if i in flips else t for i, t in enumerate(f)]
    holes = 0
    hole_faces = 0
    hole_skipped = 0
    if fill_holes_mm is not None:
        f, holes, hole_faces, hole_skipped = fill_planar_holes(v, f, fill_holes_mm)
    used = sorted({i for t in f for i in t})
    mapping = {old: new for new, old in enumerate(used)}
    result = Mesh([v[i] for i in used], [tuple((mapping[i] for i in t)) for t in f])
    changes = {
        'mode': 'explicit_clean',
        'weld_tolerance_mm': tolerance,
        'welded_vertices': len(mesh.vertices) - len(v),
        'removed_unused_vertices': len(v) - len(used),
        'removed_degenerate_faces': deg,
        'removed_duplicate_faces': dup,
        'flipped_faces': len(flips),
        'removed_components': 0,
        'filled_holes': holes,
        'added_hole_faces': hole_faces,
        'skipped_boundary_loops': hole_skipped,
        'maximum_hole_diameter_mm': fill_holes_mm,
        'hole_fill_region_policy': 'Coplanar regions with overlapping projected bounds remain open, including nested rims. More than 128 planar regions or uncertain boundary connectivity disables closure.',
        'shell_policy': 'Local consistency with minimal flips; no global outward enforcement, component deletion or thickening; hole filling only when explicitly selected.'
    }
    return (result, changes)


def fill_planar_holes(vertices, faces, maximum):
    """Fill only bounded simple strictly convex planar loops; never a flat sheet."""
    edges = {}
    components = DSU(len(vertices))
    for tri in faces:
        for i in range(3):
            a, b = (tri[i], tri[(i + 1) % 3])
            key = (min(a, b), max(a, b))
            components.union(a, b)
            if key in edges:
                edges[key] = (edges[key][0] + 1, a, b)
            else:
                edges[key] = (1, a, b)
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for count, a, b in edges.values():
        if count == 1:
            outgoing[a].append(b)
            incoming[b].append(a)
    # Bound work for fragmented adversarial geometry.
    if len(outgoing) > 100000:
        return (faces, 0, 0, len(outgoing))
    by_component = defaultdict(list)
    for i in range(len(vertices)):
        by_component[components.find(i)].append(i)
    seen = set()
    new = []
    filled = 0
    skipped = 0
    regions = []
    uncertain_boundary = False
    for start in list(outgoing):
        if start in seen:
            continue
        loop = []
        current = start
        for _ in range(257):
            if current in seen or len(outgoing.get(current, ())) != 1 or len(incoming.get(
                current,
                ()
            )) != 1:
                break
            loop.append(current)
            seen.add(current)
            current = outgoing[current][0]
            if current == start:
                break
        if current != start or not 3 <= len(loop) <= 256:
            skipped += 1
            uncertain_boundary = True
            continue
        p = [vertices[i] for i in loop]
        diameter = max((norm(sub(a, b)) for a in p for b in p))
        normal = cross(sub(p[1], p[0]), sub(p[2], p[0]))
        length = norm(normal)
        if length <= AREA_EPS:
            skipped += 1
            uncertain_boundary = True
            continue
        normal = tuple((x / length for x in normal))
        tolerance = max(1e-06, diameter * 1e-07)
        if any((abs(dot(sub(point, p[0]), normal)) > tolerance for point in p)):
            skipped += 1
            continue
        region = {'loop': loop, 'points': p, 'normal': normal,
                  'tolerance': tolerance, 'fillable': False}
        regions.append(region)
        if diameter > maximum + 1e-09:
            skipped += 1
            continue
        component = by_component[components.find(start)]
        stride = max(1, len(component) // 1024)
        witnesses = component[::stride][:1024]
        if not any((abs(dot(sub(vertices[i], p[0]), normal)) > tolerance for i in witnesses)):
            skipped += 1
            continue
        # Strict convexity, plus an explicit bounded non-adjacent segment test.
        axis = max(range(3), key=lambda k: abs(normal[k]))
        axes = [k for k in range(3) if k != axis]
        q = [(point[axes[0]], point[axes[1]]) for point in p]

        def turn(a, b, c):
            return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        turns = [turn(q[i - 1], q[i], q[(i + 1) % len(q)]) for i in range(len(q))]
        if not (all((t > 1e-12 for t in turns)) or all((t < -1e-12 for t in turns))):
            skipped += 1
            continue
        crossing = False
        for i in range(len(q)):
            for j in range(i + 2, len(q)):
                if i == 0 and j == len(q) - 1:
                    continue
                a, b, c, d = (q[i], q[(i + 1) % len(q)], q[j], q[(j + 1) % len(q)])
                if turn(a, b, c) * turn(a, b, d) <= 0 and turn(c, d, a) * turn(c, d, b) <= 0:
                    crossing = True
                    break
            if crossing:
                break
        if crossing:
            skipped += 1
            continue
        region['fillable'] = True

    # Do not create independent disks for annular or overlapping loop regions.
    # Regions too large to fill still participate, preventing an eligible inner
    # rim from being capped inside a larger untouched outer boundary.
    blocked = interacting_planar_regions(regions)
    if uncertain_boundary:
        blocked.update(range(len(regions)))
    for index, region in enumerate(regions):
        if not region['fillable']:
            continue
        if index in blocked:
            skipped += 1
            continue
        # Existing directed boundary order is reversed for opposite edge winding.
        loop = list(reversed(region['loop']))
        triangles = [(loop[0], loop[i], loop[i + 1]) for i in range(1, len(loop) - 1)]
        if len(faces) + len(new) + len(triangles) > 1000000:
            skipped += 1
            continue
        new.extend(triangles)
        filled += 1
    return (faces + new, filled, len(new), skipped)


def interacting_planar_regions(regions):
    """Conservatively block overlapping coplanar boundary regions.

    Projected AABB overlap is sufficient for rejection, including nested loops.
    It may reject disjoint polygons whose boxes overlap; uncertain caps remain
    open. Pair work is bounded at 128 regions rather than growing quadratically.
    """
    if len(regions) > 128:
        return set(range(len(regions)))
    blocked = set()
    for index, first in enumerate(regions):
        normal = first['normal']
        origin = first['points'][0]
        axis = max(range(3), key=lambda item: abs(normal[item]))
        axes = [item for item in range(3) if item != axis]
        first_min = [min(point[item] for point in first['points']) for item in axes]
        first_max = [max(point[item] for point in first['points']) for item in axes]
        for other_index in range(index):
            other = regions[other_index]
            tolerance = max(first['tolerance'], other['tolerance'])
            if any(abs(dot(sub(point, origin), normal)) > tolerance
                   for point in other['points']):
                continue
            if any(abs(dot(sub(point, other['points'][0]), other['normal'])) > tolerance
                   for point in first['points']):
                continue
            other_min = [min(point[item] for point in other['points']) for item in axes]
            other_max = [max(point[item] for point in other['points']) for item in axes]
            separated = any(first_max[item] < other_min[item] - tolerance
                            or other_max[item] < first_min[item] - tolerance
                            for item in range(2))
            if not separated:
                blocked.update((index, other_index))
    return blocked
