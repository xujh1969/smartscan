"""Batch orchestration: idempotent runs, error isolation, cancellation, atomic saves."""

from __future__ import annotations

import datetime
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

from .detection import detect_quads, estimate_background, resolve_occlusion
from .metadata import build_text_chunk, read_metadata, write_png
from .models import BatchConfig, BatchResult, Flags, OrientationState, PhotoQuad, SplitResult
from .naming import content_hash, find_existing, next_name, reserve_name
from .orientation import should_auto_rotate, vote
from .rotation import apply_state
from .split import deskew_and_crop

Progress = Callable[[int, int, str], None]
Cancel = Callable[[], bool]
_DISK_FACTOR = 3


def log_file_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "SmartScan" / "logs" / "smartscan.log"


def _append_log(message: str) -> None:
    path = log_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass


def estimate_disk_need(config: BatchConfig) -> int:
    return sum(
        path.stat().st_size for path in config.source_files if path.exists()
    ) * _DISK_FACTOR


def _load_existing(output_dir: Path) -> list[dict]:
    metas: list[dict] = []
    for png in sorted(output_dir.glob("*.png")):
        try:
            meta = read_metadata(png)
        except Exception:
            continue
        if meta.get("source") and meta.get("digest"):
            metas.append(
                {"path": str(png), "source": meta["source"], "digest": meta["digest"]}
            )
    return metas


def _read_source(path: Path) -> tuple[np.ndarray, tuple[float, float], bytes | None]:
    with Image.open(path) as image:
        dpi = image.info.get("dpi") or (300.0, 300.0)
        icc = image.info.get("icc_profile")
        array = np.asarray(image)
        mode = image.mode
    if array.dtype != np.uint8 or mode not in ("L", "RGB", "RGBA"):
        raise ValueError("仅支持 8bit/通道输入；更高位深请人工处理以免降低清晰度")
    if array.ndim == 2:
        import cv2

        array = cv2.cvtColor(array, cv2.COLOR_GRAY2RGB)
    elif array.shape[2] == 4:
        array = array[:, :, :3]
    return array, (float(dpi[0]), float(dpi[1])), icc


def _auto_orientation(crop: np.ndarray) -> tuple[np.ndarray, int, str, list[str]]:
    angle = should_auto_rotate(vote(crop))
    if not angle:
        return crop, 0, OrientationState.UNKNOWN, []
    state = 90 if angle == 90 else 270
    return (
        apply_state(crop, state),
        state,
        OrientationState.AUTO,
        [Flags.AUTO_ROTATED],
    )


def _save_photo(
    output_dir: Path,
    index: int,
    digest: str,
    source_key: str,
    crop: np.ndarray,
    quad: PhotoQuad,
    rotation: int,
    orientation: str,
    extra_flags: list[str],
    dpi: tuple[float, float],
    icc: bytes | None,
) -> SplitResult:
    target = reserve_name(output_dir, next_name(index, digest))
    text = build_text_chunk(
        source=source_key,
        digest=digest,
        quad=quad.ordered(),
        tilt_deg=quad.tilt_deg,
        rotation=rotation,
        orientation=orientation,
        flags=quad.flags() + extra_flags,
        confidence=quad.confidence,
    )
    write_png(target, Image.fromarray(crop), dpi=dpi, icc=icc, text=text)
    return SplitResult(
        path=target,
        source=source_key,
        digest=digest,
        rotation=rotation,
        orientation=orientation,
        tilt_deg=quad.tilt_deg,
        confidence=quad.confidence,
        flags=quad.flags() + extra_flags,
    )


def run(
    config: BatchConfig,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> BatchResult:
    raw_report = progress or (lambda *_: None)

    def report(done: int, total: int, stage: str) -> None:
        raw_report(done, total, stage)
        _append_log(f"{done}/{total} {stage}")

    should_cancel = cancel or (lambda: False)
    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    if estimate_disk_need(config) > shutil.disk_usage(str(output_dir)).free:
        raise OSError("输出目录磁盘空间不足，已停止处理")

    existing = _load_existing(output_dir)
    result = BatchResult()
    total = len(config.source_files)
    index = 0
    _append_log(f"batch start: {total} files -> {output_dir}")

    for position, source in enumerate(config.source_files, start=1):
        if should_cancel():
            break
        try:
            digest = content_hash(source)
            source_key = str(source.resolve())
            if find_existing(existing, source_key, digest):
                report(position, total, "skipped")
                continue

            image, dpi, icc = _read_source(source)
            background = estimate_background(image)
            quads = resolve_occlusion(
                detect_quads(image, background, min_area_ratio=config.min_area_ratio)
            )
            if not quads:
                result.review.append(source)
                report(position, total, "review")
                continue

            over_tilt = False
            for quad in quads:
                if abs(quad.tilt_deg) > config.max_tilt_deg:
                    quad.confidence = min(quad.confidence, 0.5)
                    over_tilt = True
            if over_tilt and source not in result.review:
                result.review.append(source)

            for quad in quads:
                crop = deskew_and_crop(
                    image,
                    quad,
                    background,
                    visible_mask=quad.visible_mask,
                    fill_mode=config.fill_mode,
                )
                oriented, rotation, orientation, extra_flags = _auto_orientation(crop)
                index += 1
                result.ok.append(
                    _save_photo(
                        output_dir,
                        index,
                        digest,
                        source_key,
                        oriented,
                        quad,
                        rotation,
                        orientation,
                        extra_flags,
                        dpi,
                        icc,
                    )
                )
            report(position, total, "done")
        except Exception as exc:
            result.failed.append((source, str(exc)))
            report(position, total, "failed")
    return result
