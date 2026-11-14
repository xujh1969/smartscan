"""Lossless 90-degree rotations driven by an absolute state (0/90/180/270).

The base image is always the first split result; a rotation is applied to the
base in a single transform, so repeated clicks never accumulate re-encoding.
"""

from __future__ import annotations

import numpy as np


def rotate_90(image: np.ndarray, clockwise: bool = True) -> np.ndarray:
    arr = np.asarray(image)
    return np.rot90(arr, k=-1 if clockwise else 1).copy()


def state_after(state: int, step: int) -> int:
    """step=+1 clockwise, step=-1 counter-clockwise."""
    return (int(state) + int(step) * 90) % 360


def apply_state(base: np.ndarray, state: int) -> np.ndarray:
    """Apply the target state to the base image in ONE lossless transform."""
    arr = np.asarray(base)
    quarter_turns = (int(state) // 90) % 4
    return np.rot90(arr, k=-quarter_turns).copy()


def rotate_and_save(
    path, base: np.ndarray, step: int, current_state: int = 0
) -> int:
    """Rotate from the BASE image (never from the previously saved file) and
    atomically persist the PNG together with its updated metadata."""
    from pathlib import Path

    from PIL import Image

    from .metadata import read_metadata, write_png

    target = Path(path)
    new_state = state_after(current_state, step)
    oriented = apply_state(np.asarray(base), new_state)

    with Image.open(target) as image:
        dpi = image.info.get("dpi") or (300.0, 300.0)
        icc = image.info.get("icc_profile")

    meta = read_metadata(target)
    keys = (
        "format_version",
        "source",
        "digest",
        "quad",
        "tilt_deg",
        "rotation",
        "orientation",
        "flags",
        "confidence",
    )
    text = {key: str(meta.get(key, "")) for key in keys}
    flags = [
        flag
        for flag in str(meta.get("flags", "")).split(",")
        if flag and flag != "auto"
    ]
    text.update(
        {
            "rotation": str(new_state),
            "orientation": "manual",
            "flags": ",".join(flags),
        }
    )
    write_png(target, Image.fromarray(oriented), dpi=dpi, icc=icc, text=text)
    return new_state
