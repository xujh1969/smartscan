"""Quadrilateral geometry for scanned photos.

Coordinates use image space (x right, y down). A quad is stored in clockwise
order starting at the top-most vertex (ties broken by the smallest x).
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = tuple[float, float]
Quad = Sequence[Point]


def order_quad(points: Iterable[Point]) -> list[Point]:
    pts = list(points)
    if len(pts) != 4:
        raise ValueError("a quad must have exactly 4 points")
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    ordered = sorted(pts, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    start = min(range(4), key=lambda i: (ordered[i][1], ordered[i][0]))
    return ordered[start:] + ordered[:start]


def quad_bbox(quad: Quad) -> tuple[float, float, float, float]:
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def is_rectangle(quad: Quad) -> bool:
    """Recognize four right angles, including rotated rectangles."""
    pts = order_quad(quad)
    edges = [(pts[(i + 1) % 4][0] - pts[i][0], pts[(i + 1) % 4][1] - pts[i][1])
             for i in range(4)]
    # OpenCV returns float32 corners; their rounding grows with image coordinates.
    roundoff = max(abs(value) for point in pts for value in point) * 2 ** -21
    return all(abs(a[0] * b[0] + a[1] * b[1]) <=
               1e-6 * math.hypot(*a) * math.hypot(*b) + roundoff * (math.hypot(*a) + math.hypot(*b))
               for a, b in zip(edges, edges[1:] + edges[:1]))


def tilt_angle(quad: Quad) -> float:
    """Small deskew angle, preserving portrait/landscape orientation."""
    pts = order_quad(quad)
    edges = [
        (pts[(i + 1) % 4][0] - pts[i][0], pts[(i + 1) % 4][1] - pts[i][1])
        for i in range(4)
    ]
    dx, dy = max(edges, key=lambda e: e[0] * e[0] + e[1] * e[1])
    angle = math.degrees(math.atan2(dy, dx))
    while angle > 45.0:
        angle -= 90.0
    while angle <= -45.0:
        angle += 90.0
    return angle


def rotate_points(
    points: Iterable[Point], angle_deg: float, center: Point
) -> list[Point]:
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    cx, cy = center
    out = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        out.append((dx * cos_a - dy * sin_a + cx, dx * sin_a + dy * cos_a + cy))
    return out


def _cross(a: Point, b: Point, p: Point) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _inside_convex_quad(p: Point, quad: list[Point], tol: float = 1e-6) -> bool:
    signs = [_cross(quad[i], quad[(i + 1) % 4], p) for i in range(4)]
    return all(s >= -tol for s in signs) or all(s <= tol for s in signs)


def largest_inscribed_rect(
    quad: Quad, tilt_deg: float, shape: tuple[float, float]
) -> tuple[int, int, int, int]:
    """Largest axis-aligned rectangle fully inside a (possibly tilted) quad.

    `shape` is (width, height) of the containing image. The result is clipped to
    it. Used to guarantee we never cut into photo content by more than the
    unavoidable corner triangles.
    """
    pts = order_quad(quad)
    x0, y0, x1, y1 = quad_bbox(pts)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    max_w, max_h = x1 - x0, y1 - y0
    img_w, img_h = float(shape[0]), float(shape[1])

    scale = 1.0
    while scale > 0.05:
        w, h = max_w * scale, max_h * scale
        corners = [
            (cx - w / 2, cy - h / 2),
            (cx + w / 2, cy - h / 2),
            (cx + w / 2, cy + h / 2),
            (cx - w / 2, cy + h / 2),
        ]
        if all(_inside_convex_quad(p, pts) for p in corners):
            rx0 = max(0.0, min(img_w, corners[0][0]))
            ry0 = max(0.0, min(img_h, corners[0][1]))
            rx1 = max(0.0, min(img_w, corners[2][0]))
            ry1 = max(0.0, min(img_h, corners[2][1]))
            if rx1 > rx0 and ry1 > ry0:
                return (
                    int(math.floor(rx0)),
                    int(math.floor(ry0)),
                    int(math.ceil(rx1)),
                    int(math.ceil(ry1)),
                )
        scale -= 0.02
    return 0, 0, 0, 0


def shrink_quad(quad: Quad, pixels: float) -> list[Point]:
    """Move each vertex towards the centroid; used to take the inner edge of a
    shadow line instead of its outer edge."""
    pts = order_quad(quad)
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    out = []
    for x, y in pts:
        dx, dy = cx - x, cy - y
        length = math.hypot(dx, dy) or 1.0
        out.append((x + dx / length * pixels, y + dy / length * pixels))
    return out
