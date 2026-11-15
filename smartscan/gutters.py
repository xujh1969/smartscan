"""Gutter-based splitting for tightly tiled album pages.

The paper-ridge detector looks for *light, narrow ridges* (Hough lines on a
top-hat image). Real album pages break that assumption: prints almost fill the
sheet, gutters are only a few pixels wide, and the scanner lid casts a gradient
that darkens them below an absolute brightness threshold.

The robust signal is not the ridge's brightness but the fraction of pixels
that are close to the *estimated background colour*. A true gutter is a long,
straight run of those pixels; a horizon, a shirt or a building inside one
print is not. For every rectangle we compute 1-D column/row projections of
that mask, subtract a wide baseline (a 1-D top-hat), and take the strongest
central peak. Cuts are chosen best-first across the whole page, so one wrong
early cut cannot cascade into a dozen fragments.

This module needs only NumPy/OpenCV, runs on the CPU without a model download,
and leaves every existing detection path untouched.
"""

from __future__ import annotations

import cv2
import numpy as np

from .models import PhotoQuad

Background = tuple[int, int, int]

WORK_MAX = 900
BG_TOLERANCE = 28
MARGIN = 0.11
MIN_RIDGE = 0.08
MIN_PEAK_LEVEL = 0.10
MIN_SIDE_RATIO = 0.09
MAX_BOXES = 8
BLANK_FOREGROUND = 0.22
BLANK_DETAIL = 45.0
EDGE_BAND_LIMIT = 0.12
MAX_GUTTER_WIDTH_RATIO = 0.022
STRIP_ASPECT = 3.0
STRIP_AREA_RATIO = 0.10


def _prepare(image: np.ndarray, background: Background):
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2RGB)
    height, width = arr.shape[:2]
    scale = min(1.0, WORK_MAX / max(height, width))
    small = cv2.resize(arr[..., :3], (max(1, round(width * scale)),
                                      max(1, round(height * scale))),
                       interpolation=cv2.INTER_AREA)
    bg = np.asarray(background[:3], dtype=np.float32)
    delta = np.max(np.abs(small.astype(np.float32) - bg), axis=2)
    near = (delta < BG_TOLERANCE).astype(np.float32)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    return near, gray, scale


def _ridge(near: np.ndarray, rect: tuple[int, int, int, int],
           vertical: bool):
    x0, y0, x1, y1 = rect
    sub = near[y0:y1, x0:x1]
    projection = sub.mean(axis=0 if vertical else 1).astype(np.float32)
    length = len(projection)
    kernel = max(9, round(min(sub.shape) * 0.035) | 1)
    if vertical:
        baseline = cv2.blur(projection.reshape(1, -1), (kernel, 1)).ravel()
    else:
        baseline = cv2.blur(projection.reshape(-1, 1), (1, kernel)).ravel()
    ridge = projection - baseline
    lo = max(1, int(length * MARGIN))
    hi = int(length * (1 - MARGIN))
    if hi <= lo:
        return None
    index = lo + int(np.argmax(ridge[lo:hi]))
    peak = float(projection[index])
    # A real gutter is only a few pixels wide. A wide pale band (a white
    # shirt, a snowfield, a bright horizon inside one print) is not a seam.
    half = max(0.5, 0.6 * peak)
    start, stop = index, index
    while start > 0 and projection[start - 1] > half:
        start -= 1
    while stop < length - 1 and projection[stop + 1] > half:
        stop += 1
    max_width = max(8, round(min(near.shape) * MAX_GUTTER_WIDTH_RATIO))
    if stop - start + 1 > max_width:
        return None
    return (float(ridge[index]), peak,
            index + (x0 if vertical else y0))


def _best_seam(near, rect, cache: dict):
    if rect in cache:
        return cache[rect]
    best = None
    for vertical in (True, False):
        result = _ridge(near, rect, vertical)
        if result is None or result[1] < MIN_PEAK_LEVEL:
            continue
        candidate = (result[0], vertical, int(result[2]))
        if best is None or candidate[0] > best[0]:
            best = candidate
    cache[rect] = best
    return best


def _trim_edges(profile, minimum: int) -> tuple[int, int]:
    length = len(profile)
    limit = max(1, int(length * EDGE_BAND_LIMIT))
    start, stop = 0, length
    while start < limit and profile[start] > 0.80 and stop - start > minimum:
        start += 1
    while (stop > length - limit and profile[stop - 1] > 0.80
           and stop - start > minimum):
        stop -= 1
    return start, stop


def gutter_quads(image: np.ndarray, background: Background,
                 min_ridge: float = MIN_RIDGE) -> list[PhotoQuad]:
    """Return axis-aligned quads for prints separated by pale gutters.

    Page-margin cells, blank sheets and wide thin strips are discarded. The
    result is empty when there is no reliable gutter evidence at all.
    """
    near, gray, scale = _prepare(image, background)
    height, width = near.shape
    min_side = int(MIN_SIDE_RATIO * min(height, width))
    cache: dict = {}

    def leaf(rect):
        seam = _best_seam(near, rect, cache)
        return {"rect": rect, "seam": seam,
                "score": seam[0] if seam else -1.0}

    leaves = [leaf((0, 0, width, height))]
    while len(leaves) < MAX_BOXES:
        best = max(leaves, key=lambda item: item["score"])
        if best["score"] < min_ridge:
            break
        _, vertical, position = best["seam"]
        x0, y0, x1, y1 = best["rect"]
        if vertical:
            first, second = (x0, y0, position, y1), (position, y0, x1, y1)
        else:
            first, second = (x0, y0, x1, position), (x0, position, x1, y1)
        if any(c - a < min_side or d - b < min_side
               for a, b, c, d in (first, second)):
            best["score"] = -1.0
            continue
        leaves.remove(best)
        leaves.append(leaf(first))
        leaves.append(leaf(second))

    inverse = 1.0 / scale
    quads: list[PhotoQuad] = []
    for item in leaves:
        x0, y0, x1, y1 = item["rect"]
        sub = near[y0:y1, x0:x1]
        foreground = 1.0 - float(sub.mean())
        detail = float(cv2.Laplacian(gray[y0:y1, x0:x1], cv2.CV_32F).var())
        # A page margin is both pale AND flat; a faded snow/sky print is pale
        # but still textured, so colour alone would wrongly discard it.
        if foreground < BLANK_FOREGROUND and detail < BLANK_DETAIL:
            continue
        column = sub.mean(axis=0)
        row = sub.mean(axis=1)
        xa, xb = _trim_edges(column, min_side)
        ya, yb = _trim_edges(row, min_side)
        left, top = (x0 + xa) * inverse, (y0 + ya) * inverse
        right, bottom = (x0 + xb) * inverse, (y0 + yb) * inverse
        box_width, box_height = right - left, bottom - top
        if (box_width > STRIP_ASPECT * box_height
                and box_width * box_height
                < STRIP_AREA_RATIO * height * width * inverse * inverse):
            continue
        quads.append(PhotoQuad(
            points=[(left, top), (right, top), (right, bottom), (left, bottom)],
            confidence=0.8,
            status="ok",
        ))
    return sorted(quads, key=lambda quad: (quad.bbox()[1], quad.bbox()[0]))
