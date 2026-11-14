"""PNG metadata (tEXt / pHYs / iCCP) and atomic writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, PngImagePlugin

FORMAT_VERSION = "1"


def build_text_chunk(
    *,
    source: str,
    digest: str,
    quad: list[tuple[float, float]],
    tilt_deg: float,
    rotation: int,
    orientation: str,
    flags: list[str],
    confidence: float,
) -> dict[str, str]:
    return {
        "format_version": FORMAT_VERSION,
        "source": str(source),
        "digest": str(digest),
        "quad": json.dumps([[round(float(x), 2), round(float(y), 2)] for x, y in quad]),
        "tilt_deg": f"{float(tilt_deg):.3f}",
        "rotation": str(int(rotation)),
        "orientation": str(orientation),
        "flags": ",".join(flags),
        "confidence": f"{float(confidence):.3f}",
    }


def write_png(
    path: str | Path,
    image: Image.Image,
    dpi: tuple[float, float] = (300.0, 300.0),
    icc: bytes | None = None,
    text: Mapping[str, str] | None = None,
) -> Path:
    """Save PNG with metadata via a temp file + os.replace (no half-written PNG)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pnginfo = PngImagePlugin.PngInfo()
    for key, value in (text or {}).items():
        pnginfo.add_text(str(key), str(value))

    temp = target.with_name(target.name + ".tmp")
    options: dict[str, Any] = {"format": "PNG", "pnginfo": pnginfo, "dpi": dpi}
    if icc:
        options["icc_profile"] = icc
    try:
        image.save(temp, **options)
        import time

        for attempt in range(3):
            try:
                os.replace(temp, target)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temp.exists():
            temp.unlink()
    return target


def read_metadata(path: str | Path) -> dict[str, str]:
    with Image.open(path) as image:
        data = {
            str(key): str(value)
            for key, value in dict(image.info).items()
            if isinstance(value, (str, int, float))
        }
        chunks = getattr(image, "text", None) or {}
        data.update({str(key): str(value) for key, value in dict(chunks).items()})
    return data
