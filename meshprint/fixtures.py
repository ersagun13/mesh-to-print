"""Original procedural fixtures; no downloaded geometry or attribution needed."""
import math
from .formats import Mesh


def cube(size=20.0, offset=(0, 0, 0)):
    vertices = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
             (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
             (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return Mesh([tuple(p[i] * size + offset[i] for i in range(3)) for p in vertices], faces)


def sphere(longitudes=256, latitudes=200, radius=30.0):
    """Indexed closed UV sphere, avoiding duplicate pole and seam vertices."""
    vertices = [(0.0, 0.0, radius)]
    for latitude in range(1, latitudes):
        theta = math.pi * latitude / latitudes
        for longitude in range(longitudes):
            phi = 2 * math.pi * longitude / longitudes
            vertices.append((radius * math.sin(theta) * math.cos(phi),
                             radius * math.sin(theta) * math.sin(phi),
                             radius * math.cos(theta)))
    bottom = len(vertices)
    vertices.append((0.0, 0.0, -radius))
    faces = []
    for j in range(longitudes):
        k = (j + 1) % longitudes
        faces.append((0, 1 + j, 1 + k))
    for ring in range(latitudes - 2):
        a = 1 + ring * longitudes
        b = a + longitudes
        for j in range(longitudes):
            k = (j + 1) % longitudes
            faces.extend(((a + j, b + j, b + k), (a + j, b + k, a + k)))
    last = 1 + (latitudes - 2) * longitudes
    for j in range(longitudes):
        faces.append((last + j, bottom, last + (j + 1) % longitudes))
    return Mesh(vertices, faces)


def vessel(segments=96, rings=24):
    """A hollow six-flute vessel with connected2mm walls and a3mm solid base."""
    vertices = []
    for inner in (False, True):
        for ring in range(rings):
            z = (3 if inner else 0) + (37 if inner else 40) * ring / (rings - 1)
            for j in range(segments):
                angle = 2 * math.pi * j / segments
                radius = 16 + 3 * math.sin(math.pi * z / 40) + 0.8 * math.cos(6 * angle)
                if inner:
                    radius -= 2
                vertices.append((radius * math.cos(angle), radius * math.sin(angle), z))
    faces = []
    for inner in (False, True):
        offset = rings * segments if inner else 0
        for ring in range(rings - 1):
            for j in range(segments):
                a = offset + ring * segments + j
                b = offset + ring * segments + (j + 1) % segments
                c, d = a + segments, b + segments
                pair = [(a, b, d), (a, d, c)]
                faces.extend(tuple(reversed(t)) if inner else t for t in pair)
    outer_top = (rings - 1) * segments
    inner_bottom = rings * segments
    inner_top = (2 * rings - 1) * segments
    for j in range(segments):
        k = (j + 1) % segments
        faces.extend(((outer_top + j, outer_top + k, inner_top + k),
                      (outer_top + j, inner_top + k, inner_top + j)))
    bottom_center = len(vertices)
    inner_center = bottom_center + 1
    vertices.extend(((0, 0, 0), (0, 0, 3)))
    for j in range(segments):
        k = (j + 1) % segments
        faces.extend(((bottom_center, k, j), (inner_center, inner_bottom + j, inner_bottom + k)))
    return Mesh(vertices, faces)


def demo_meshes():
    closed = cube()
    opened = cube()
    opened.triangles.pop()
    thin = cube()
    thin.vertices = [(x, y, z * 0.025) for x, y, z in thin.vertices]
    damaged = vessel()
    # A small missing triangle, one reversed face, a duplicate and a degenerate.
    damaged.triangles.pop(400)
    damaged.triangles[800] = tuple(reversed(damaged.triangles[800]))
    damaged.triangles.extend((damaged.triangles[0], (0, 0, 1)))
    return {'closed-cube.stl': closed, 'open-cube.stl': opened,
            'thin-plate.stl': thin, 'repairable-vessel.stl': damaged}
