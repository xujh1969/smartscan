"""Paper-boundary detection with conservative geometric fallback and review flags."""

from __future__ import annotations

import cv2
import numpy as np

from .boundaries import paper_regions, trim_to_solid_body
from .geometry import order_quad, quad_bbox, shrink_quad, tilt_angle
from .models import Flags, PhotoQuad

Background = tuple[int, int, int]
DETECTOR_VERSION = "paper-boundaries-1"
_KERNEL = np.ones((3, 3), dtype=np.uint8)
_MIN_FILL_FOR_COMPLETE = 0.92
_MIN_FOREGROUND_AREA = 100
_MIN_CELL_SIDE = 20
_MIN_CELL_FILL = 0.35
_PEAK_RATIO = 0.7
_PEAK_FLOOR = 24.0
_PEAK_MERGE_GAP = 12


def estimate_background(image: np.ndarray) -> Background:
    arr = np.asarray(image)
    height, width = arr.shape[:2]
    k = max(2, min(height, width) // 20)
    patches = [arr[:k, :k], arr[:k, -k:], arr[-k:, :k], arr[-k:, -k:]]
    # A print can occupy three corners. Mixing all four patches then estimates
    # the print colour rather than the light scanner lid. Prefer the lightest
    # corner's median, which is robust to dust and thin scanner rails.
    medians = [np.median(p.reshape(-1, arr.shape[2] if arr.ndim == 3 else 1), axis=0)
               for p in patches]
    median = max(medians, key=lambda value: float(np.mean(value)))
    if arr.ndim == 2:
        value = int(median[0])
        return (value, value, value)
    return tuple(int(v) for v in median[:3])


def find_photo_cluster(
    image: np.ndarray, background: Background, tolerance: int = 18
) -> np.ndarray:
    """Binary mask of everything that is not scanner background."""
    arr = np.asarray(image)
    bg = np.asarray(background[:3], dtype=np.int16)
    if arr.ndim == 2:
        difference = np.abs(arr.astype(np.int16) - int(bg[0]))
    else:
        difference = np.max(np.abs(arr[..., :3].astype(np.int16) - bg), axis=2)
    mask = (difference > tolerance).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _KERNEL, iterations=1)
    # Closing here bridges the narrow gutters between independent prints.
    return mask


def _edge_scores(
    gray: np.ndarray, component: np.ndarray, bbox: tuple[int, int, int, int]
) -> tuple[np.ndarray, np.ndarray]:
    """Score rows/columns by their longest CONTINUOUS straight edge.

    Counting edge pixels is wrong: many short texture edges aligned by chance
    can outscore a real seam. Hough segments distinguish a spanning seam from
    scattered photo content.
    """
    x, y, width, height = bbox
    sub_gray = gray[y : y + height, x : x + width]
    sub_mask = component[y : y + height, x : x + width]
    edges = cv2.Canny(sub_gray, 40, 120)
    edges = cv2.bitwise_and(edges, sub_mask)
    rows = np.zeros(height, dtype=np.float32)
    columns = np.zeros(width, dtype=np.float32)

    min_line = max(20, min(width, height) // 6)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=18,
        minLineLength=min_line,
        maxLineGap=12,
    )
    if lines is None:
        return rows, columns

    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        dx, dy = abs(int(x2) - int(x1)), abs(int(y2) - int(y1))
        if dy <= max(3, dx // 20):
            cy = (int(y1) + int(y2)) // 2
            low, high = max(0, cy - 2), min(height, cy + 3)
            rows[low:high] = np.maximum(rows[low:high], float(dx))
        if dx <= max(3, dy // 20):
            cx = (int(x1) + int(x2)) // 2
            low, high = max(0, cx - 2), min(width, cx + 3)
            columns[low:high] = np.maximum(columns[low:high], float(dy))
    return rows, columns


def _boundaries(scores: np.ndarray, length: int) -> list[int]:
    """Keep only long, spanning edges; short internal texture edges are cut."""
    if scores.size == 0 or length <= 0:
        return [0, max(0, length)]
    peak = float(scores.max())
    if peak < 8.0:
        return [0, length]
    threshold = max(peak * _PEAK_RATIO, _PEAK_FLOOR)
    hits = np.flatnonzero(scores >= threshold)

    groups: list[list[int]] = []
    for index in hits:
        value = int(index)
        if groups and value - groups[-1][-1] <= _PEAK_MERGE_GAP:
            groups[-1].append(value)
        else:
            groups.append([value])
    centers = [max(group, key=lambda i: scores[i]) for group in groups]

    def score_at(index: int) -> float:
        return float(scores[index]) if 0 <= index < len(scores) else 0.0

    bounds = sorted(set([0] + [int(c) for c in centers] + [length]))
    merged: list[int] = []
    for bound in bounds:
        if merged and bound - merged[-1] < max(_PEAK_MERGE_GAP, length * 0.03):
            previous = merged[-1]
            merged[-1] = bound if score_at(bound) > score_at(previous) else previous
        else:
            merged.append(bound)
    return [min(max(0, value), length) for value in merged]



def _fit_quad(
    cell: np.ndarray, offset: tuple[int, int], shape: tuple[int, int]
) -> PhotoQuad | None:
    body, (dx, dy) = trim_to_solid_body(cell, min_span_ratio=0.03)
    contours, _ = cv2.findContours(
        body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    area = float(cv2.contourArea(contour))
    if area < 10:
        return None

    ox, oy = offset[0] + dx, offset[1] + dy
    global_contour = contour + np.array([[[ox, oy]]], dtype=contour.dtype)
    rect = cv2.minAreaRect(global_contour)
    box = cv2.boxPoints(rect)
    ordered = order_quad([(float(p[0]), float(p[1])) for p in box])
    inner = shrink_quad(ordered, 1.0)
    fill_ratio = min(
        1.0, area / max(1.0, float(rect[1][0] * rect[1][1]))
    )

    visible = np.zeros(shape, dtype=np.uint8)
    # The foreground mask is only a locator. Its holes include legitimate pale
    # image content, so retain the complete external contour when exporting.
    cv2.drawContours(visible, [global_contour], -1, 255, cv2.FILLED)
    return PhotoQuad(
        points=inner,
        tilt_deg=tilt_angle(inner),
        confidence=fill_ratio,
        status="ok",
        fill_ratio=fill_ratio,
        visible_mask=visible,
    )


def _split_component(
    gray: np.ndarray,
    component: np.ndarray,
    bbox: tuple[int, int, int, int],
    min_area_ratio: float,
) -> list[PhotoQuad]:
    x, y, width, height = bbox
    whole = _fit_quad(component[y:y + height, x:x + width], (x, y), component.shape)
    if whole is not None:
        sides = np.linalg.norm(np.roll(np.asarray(whole.points), -1, axis=0)
                               - np.asarray(whole.points), axis=1)
        if whole.fill_ratio > 0.96 and max(sides) / max(1.0, min(sides)) < 1.9:
            # A long scene edge cannot, on its own, split an intact print.
            if max(sides) * min(sides) > component.size * 0.55:
                whole.status = Flags.UNCERTAIN
                whole.confidence = min(whole.confidence, 0.5)
            return [whole]
    rows, columns = _edge_scores(gray, component, bbox)
    row_bounds = _boundaries(rows, height)
    column_bounds = _boundaries(columns, width)
    candidates: list[tuple[float, PhotoQuad]] = []

    for row in range(len(row_bounds) - 1):
        for column in range(len(column_bounds) - 1):
            top, bottom = row_bounds[row], row_bounds[row + 1]
            left, right = column_bounds[column], column_bounds[column + 1]
            if bottom - top < _MIN_CELL_SIDE or right - left < _MIN_CELL_SIDE:
                continue
            cell = component[y + top : y + bottom, x + left : x + right]
            if float((cell > 0).mean()) < _MIN_CELL_FILL:
                continue
            quad = _fit_quad(cell, (x + left, y + top), component.shape[:2])
            if quad is None:
                continue
            x0, y0, x1, y1 = quad.bbox()
            candidates.append(((x1 - x0) * (y1 - y0), quad))

    if not candidates:
        return []
    largest = max(area for area, _ in candidates)
    return [
        quad
        for area, quad in candidates
        if area >= max(100.0, min_area_ratio * largest)
    ]


def detect_quads(
    image: np.ndarray,
    background: Background,
    min_area_ratio: float = 0.01,
) -> list[PhotoQuad]:
    physical = paper_regions(np.asarray(image), background)
    if len(physical) > 1 or physical and physical[0].status == "ok":
        arr = np.asarray(image)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if arr.ndim == 3 else arr
        separated = []
        cluster = None
        for quad in physical:
            points = np.asarray(quad.points)
            sides = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
            if quad.status != "ok" and quad.fill_ratio > 0.99 and max(sides) > 1.9 * min(sides):
                if cluster is None:
                    cluster = find_photo_cluster(image, background)
                x0, y0, x1, y1 = quad.bbox()
                x, y = max(0, int(x0)), max(0, int(y0))
                right, bottom = min(arr.shape[1], int(x1) + 1), min(arr.shape[0], int(y1) + 1)
                children = _split_component(gray, cluster, (x, y, right - x, bottom - y), min_area_ratio)
                if len(children) > 1:
                    for child in children:
                        child.status = Flags.UNCERTAIN
                        child.confidence = min(child.confidence, 0.5)
                    separated.extend(children)
                    continue
            separated.append(quad)
        largest = max(cv2.contourArea(np.asarray(q.points, np.float32)) for q in separated)
        physical = [q for q in separated
                    if cv2.contourArea(np.asarray(q.points, np.float32)) >= min_area_ratio * largest]
        return sorted(physical, key=lambda q: (q.bbox()[1], q.bbox()[0]))
    cluster = find_photo_cluster(image, background)
    if not np.any(cluster):
        return []
    arr = np.asarray(image)
    gray = (
        cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        if arr.ndim == 3
        else arr.astype(np.uint8)
    )

    count, labels, stats, _ = cv2.connectedComponentsWithStats(cluster)
    quads: list[PhotoQuad] = []
    for index in range(1, count):
        x, y, width, height, area = (int(stats[index, k]) for k in range(5))
        if area < max(_MIN_FOREGROUND_AREA, cluster.size * 0.001):
            continue
        component = (labels == index).astype(np.uint8) * 255
        quads.extend(
            _split_component(gray, component, (x, y, width, height), min_area_ratio)
        )
    if len(quads) > 1:
        # Straight-line fallback lacks paper evidence. Retain the candidates,
        # but never silently present these ambiguous cuts as high confidence.
        for quad in quads:
            quad.confidence = min(quad.confidence, 0.55)
    return sorted(
        quads, key=lambda q: (quad_bbox(q.points)[1], quad_bbox(q.points)[0])
    )


def resolve_occlusion(quads: list[PhotoQuad]) -> list[PhotoQuad]:
    """Upper photo stays `ok`; the covered one becomes `incomplete`.

    If no photo looks complete, the T-junction evidence was too weak: mark all
    of them `uncertain` rather than guessing which one is on top.
    """
    if not quads:
        return quads
    for quad in quads:
        if quad.fill_ratio < _MIN_FILL_FOR_COMPLETE:
            quad.status = Flags.INCOMPLETE
            quad.confidence = min(quad.confidence, 0.65)

    # A covered photo leaves a step-shaped offcut next to the covering one:
    # overlapping x-ranges, overlapping y-ranges, but noticeably different
    # heights. Upright stacks and side-by-side grids do not show this pattern.
    for position, first in enumerate(quads):
        ax0, ay0, ax1, ay1 = first.bbox()
        first_height = ay1 - ay0
        for second in quads[position + 1 :]:
            bx0, by0, bx1, by1 = second.bbox()
            second_height = by1 - by0
            x_overlap = min(ax1, bx1) - max(ax0, bx0)
            y_overlap = min(ay1, by1) - max(ay0, by0)
            narrowest = min(ax1 - ax0, bx1 - bx0)
            if (
                x_overlap <= -0.1 * narrowest
                or y_overlap <= 0.5 * min(first_height, second_height)
            ):
                continue
            if min(first_height, second_height) >= 0.8 * max(
                first_height, second_height
            ):
                continue
            covered = first if first_height < second_height else second
            covered.status = Flags.INCOMPLETE
            covered.confidence = min(covered.confidence, 0.65)

    if all(quad.status != "ok" for quad in quads):
        for quad in quads:
            quad.status = Flags.UNCERTAIN
            quad.confidence = min(quad.confidence, 0.5)
    return quads
