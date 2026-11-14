"""Local paper gutters partition a scan without extending scene edges into a grid."""

from __future__ import annotations

import cv2
import numpy as np

from .geometry import order_quad, tilt_angle
from .models import Flags, PhotoQuad


def trim_to_solid_body(
    cell: np.ndarray, sparse: float = 0.25, min_span_ratio: float = 0.15
) -> tuple[np.ndarray, tuple[int, int]]:
    """Trim only LONG, nearly-empty head/tail bands (scanner edge lines).

    A tilted photo also has a few sparse rows at its corners; those are short
    and must be kept or the tilt is lost. Only a long band with <25% foreground
    is a connected thin line rather than photo content.
    """
    height, width = cell.shape[:2]
    row_fill = np.count_nonzero(cell, axis=1) / max(1, width)
    column_fill = np.count_nonzero(cell, axis=0) / max(1, height)

    def bounds(fill: np.ndarray, length: int) -> tuple[int, int]:
        low = fill < sparse
        head = 0
        while head < length and low[head]:
            head += 1
        tail = length
        while tail > head and low[tail - 1]:
            tail -= 1
        minimum = max(1, int(min_span_ratio * length))
        start = head if head >= minimum else 0
        end = tail if length - tail >= minimum else length
        return start, end

    y0, y1 = bounds(row_fill, height)
    x0, x1 = bounds(column_fill, width)
    return np.ascontiguousarray(cell[y0:y1, x0:x1]), (x0, y0)


def paper_regions(image: np.ndarray, background: tuple[int, int, int]) -> list[PhotoQuad]:
    """Return print outlines separated by finite, pale paper ridges.

    A brightness step (a horizon) and a dark line (a building) are insufficient:
    a gutter must be a narrow light ridge with darker pixels on both sides.
    Detection uses a bounded working image; export coordinates remain native.
    """
    height, width = image.shape[:2]
    scale = min(1.0, 1000 / min(height, width), 1400 / max(height, width))
    work = cv2.resize(image, (round(width * scale), round(height * scale)),
                      interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(work, cv2.COLOR_RGB2GRAY) if work.ndim == 3 else work
    h, w = gray.shape
    short = min(h, w)
    span = max(7, round(short * 0.031)) | 1
    walls = np.zeros_like(gray)
    for vertical in (False, True):
        kernel = np.ones((1, span) if vertical else (span, 1), dtype=np.uint8)
        ridge = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)
        evidence = ((ridge > 5) & (gray > max(220, np.mean(background) - 30))).astype(np.uint8) * 255
        lines = cv2.HoughLinesP(evidence, 1, np.pi / 720, threshold=25,
                                minLineLength=max(25, short * 0.07), maxLineGap=20)
        if lines is None:
            continue
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            dx, dy = float(x2 - x1), float(y2 - y1)
            if (vertical and abs(dx) > abs(dy) * 0.08
                    or not vertical and abs(dy) > abs(dx) * 0.08):
                continue
            length = np.hypot(dx, dy)
            ex, ey = dx / length * 8, dy / length * 8
            cv2.line(walls, (round(x1 - ex), round(y1 - ey)),
                     (round(x2 + ex), round(y2 + ey)), 255, 5)

    mask = (gray < min(235, np.mean(background) - 13)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    # Remove scanner rails before filling contours, otherwise a rail can enclose
    # blank paper and turn it into apparent photo content.
    body = np.zeros_like(mask)
    for contour in contours:
        if cv2.contourArea(contour) < h * w * 0.003:
            continue
        x, y, cw, ch = cv2.boundingRect(contour)
        trimmed, (ox, oy) = trim_to_solid_body(mask[y:y + ch, x:x + cw], min_span_ratio=0.03)
        pieces, _ = cv2.findContours(trimmed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for piece in pieces:
            cv2.drawContours(body, [piece + np.array([[[x + ox, y + oy]]])],
                             -1, 255, cv2.FILLED)
    body[walls > 0] = 0
    contours, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    quads = []
    for contour in contours:
        area = cv2.contourArea(contour)
        rect = cv2.minAreaRect(contour)
        rw, rh = rect[1]
        if (area < h * w * 0.003 or min(rw, rh) < max(15, short * 0.04)
                or max(rw, rh) > min(rw, rh) * 3):
            continue
        fill = area / max(1, rw * rh)
        points = order_quad([tuple(map(float, p / scale)) for p in cv2.boxPoints(rect)])
        uncertain = fill < 0.90 or max(rw, rh) > min(rw, rh) * 1.9 or rw * rh > h * w * 0.55
        quads.append(PhotoQuad(points=points, tilt_deg=tilt_angle(points),
                               fill_ratio=fill, confidence=min(fill, 0.5) if uncertain else fill,
                               status=Flags.UNCERTAIN if uncertain else "ok"))
    # A closed paper-like feature inside a print (a shirt or window) can leave
    # an island. It is not another photograph when a larger outline encloses it.
    kept = []
    for quad in sorted(quads, key=lambda q: cv2.contourArea(np.asarray(q.points, np.float32)), reverse=True):
        polygon = np.asarray(quad.points, np.float32)
        area = cv2.contourArea(polygon)
        if any(cv2.intersectConvexConvex(polygon, np.asarray(other.points, np.float32))[0]
               > area * 0.85 for other in kept):
            continue
        kept.append(quad)
    return kept
