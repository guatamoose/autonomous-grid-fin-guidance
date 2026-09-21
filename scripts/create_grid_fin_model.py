"""Create a schematic, neutral-position OBJ of the user's four-fin layout.

The geometry is for orientation only. It is not dimensioned for fabrication.
Coordinates: +Z points toward the camera/nose; +X is right and +Y is up
when viewed from the tail looking toward the landing pad.
"""

from math import cos, pi, sin
from pathlib import Path


OUT = Path(__file__).resolve().parents[1] / "outputs"
OUT.mkdir(exist_ok=True)
obj_lines = ["# Schematic grid-fin rocket: +Z nose, +X right, +Y top", "mtllib grid-fin-model.mtl"]
vertices = []


def vertex(point):
    vertices.append(point)
    obj_lines.append("v {:.5f} {:.5f} {:.5f}".format(*point))
    return len(vertices)


def group(name, material):
    obj_lines.extend((f"o {name}", f"usemtl {material}"))


def box(x0, y0, z0, x1, y1, z1):
    v = [vertex(p) for p in (
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    )]
    for face in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        obj_lines.append("f " + " ".join(str(v[i]) for i in face))


def cylinder(radius, z0, z1, segments=32):
    bottom = [vertex((radius * cos(2*pi*i/segments), radius * sin(2*pi*i/segments), z0)) for i in range(segments)]
    top = [vertex((radius * cos(2*pi*i/segments), radius * sin(2*pi*i/segments), z1)) for i in range(segments)]
    for i in range(segments):
        j = (i + 1) % segments
        obj_lines.append(f"f {bottom[i]} {bottom[j]} {top[j]} {top[i]}")
    obj_lines.append("f " + " ".join(map(str, reversed(bottom))))
    obj_lines.append("f " + " ".join(map(str, top)))


def cone(radius, z0, z1, segments=32):
    ring = [vertex((radius * cos(2*pi*i/segments), radius * sin(2*pi*i/segments), z0)) for i in range(segments)]
    tip = vertex((0, 0, z1))
    for i in range(segments):
        obj_lines.append(f"f {ring[i]} {ring[(i+1)%segments]} {tip}")


group("Rocket_body", "body")
cylinder(28, -95, 78)
group("Nose", "nose")
cone(28, 78, 112)
group("Camera_on_top_of_nose", "camera")
box(-10, 19, 78, 10, 31, 98)
box(-5, 31, 89, 5, 35, 97)


def grid_fin(name, material, x0, y0, x1, y1):
    group(name, material)
    z0, z1 = -86, -78
    bar = 3
    # Outer frame.
    box(x0, y0, z0, x1, y0+bar, z1)
    box(x0, y1-bar, z0, x1, y1, z1)
    box(x0, y0+bar, z0, x0+bar, y1-bar, z1)
    box(x1-bar, y0+bar, z0, x1, y1-bar, z1)
    # Interior lattice, with visible open cells.
    for i in range(1, 5):
        x = x0 + (x1-x0)*i/5
        box(x-bar/2, y0+bar, z0, x+bar/2, y1-bar, z1)
    for i in range(1, 5):
        y = y0 + (y1-y0)*i/5
        box(x0+bar, y-bar/2, z0, x1-bar, y+bar/2, z1)


grid_fin("S8_TOP", "top_bottom", -23, 30, 23, 82)
grid_fin("S9_BOTTOM", "top_bottom", -23, -82, 23, -30)
grid_fin("S7_RIGHT", "left_right", 30, -23, 82, 23)
grid_fin("S10_LEFT", "left_right", -82, -23, -30, 23)

(OUT / "grid-fin-model.obj").write_text("\n".join(obj_lines) + "\n", encoding="ascii")
(OUT / "grid-fin-model.mtl").write_text(
    "newmtl body\nKd 0.15 0.18 0.24\n"
    "newmtl nose\nKd 0.25 0.28 0.35\n"
    "newmtl camera\nKd 0.12 0.65 0.55\n"
    "newmtl top_bottom\nKd 0.20 0.55 0.90\n"
    "newmtl left_right\nKd 0.95 0.55 0.18\n",
    encoding="ascii",
)
print(f"Created {OUT / 'grid-fin-model.obj'} with {len(vertices)} vertices")
