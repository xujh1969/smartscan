"""真实扫描样本验收工具（开发用，不是程序的交互界面）。

只读原始扫描件，把拆分结果写到 verify_output/，生成索引图 verify_index.png
与报告 verify_output_report.json，便于人工核对召回、裁切与朝向。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from smartscan.metadata import read_metadata  # noqa: E402
from smartscan.models import BatchConfig  # noqa: E402
from smartscan.pipeline import run  # noqa: E402

SAMPLE_DIR = ROOT / "扫描"
OUTPUT_DIR = ROOT / "verify_output" / "photos"
REPORT_PATH = ROOT / "verify_output_report.json"
INDEX_PATH = ROOT / "verify_index.png"
SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def build_index(paths: list[Path], target: Path, cell=(220, 170), columns=5) -> None:
    if not paths:
        return
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell[0], rows * cell[1]), (235, 235, 235))
    for position, path in enumerate(paths):
        with Image.open(path) as image:
            thumb = ImageOps.contain(
                image.convert("RGB"), (cell[0] - 10, cell[1] - 10)
            )
        x = (position % columns) * cell[0] + (cell[0] - thumb.width) // 2
        y = (position // columns) * cell[1] + (cell[1] - thumb.height) // 2
        sheet.paste(thumb, (x, y))
    sheet.save(target)


def diagnose(files: list[Path]) -> None:
    import cv2
    import numpy as np

    from smartscan.detection import estimate_background, find_photo_cluster

    image = np.asarray(Image.open(files[0]).convert("RGB"))
    background = estimate_background(image)
    difference = np.max(
        np.abs(
            image.astype(np.int16) - np.asarray(background, dtype=np.int16)
        ),
        axis=2,
    )
    raw = (difference > 18).astype(np.uint8) * 255
    kernel = np.ones((3, 3), dtype=np.uint8)
    opened = cv2.morphologyEx(raw, cv2.MORPH_OPEN, kernel)
    current = find_photo_cluster(image, background)

    def components(mask):
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        areas = sorted([int(row[4]) for row in stats[1:]], reverse=True)
        return count - 1, areas[:15]

    print("background", background, "foreground_px", int((raw > 0).sum()))
    print("raw", components(raw))
    print("open_only", components(opened))
    print("current(open+close)", components(current))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(opened)
    for index in range(1, count):
        if stats[index, 4] < 10000:
            continue
        component = (labels == index).astype(np.uint8) * 255
        contours, _ = cv2.findContours(
            component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        rect = cv2.minAreaRect(max(contours, key=cv2.contourArea))
        print("component", index, "area", int(stats[index, 4]), "rect", rect)

    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.bitwise_and(edges, opened)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=60, minLineLength=250, maxLineGap=25
    )
    if lines is not None:
        found = []
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            length = float(np.hypot(x2 - x1, y2 - y1))
            angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            found.append(
                (round(length), round(angle, 1), (int(x1), int(y1)), (int(x2), int(y2)))
            )
        found.sort(reverse=True)
        print("hough_lines", len(found))
        for item in found[:20]:
            print("  line", item)

    rows = (edges > 0).sum(axis=1)
    columns = (edges > 0).sum(axis=0)
    print(
        "top_rows",
        sorted([(int(v), int(i)) for i, v in enumerate(rows)], reverse=True)[:12],
    )
    print(
        "top_cols",
        sorted([(int(v), int(i)) for i, v in enumerate(columns)], reverse=True)[:12],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 张")
    parser.add_argument("--dir", dest="sample_dir", type=Path, default=SAMPLE_DIR)
    parser.add_argument("--diagnose", action="store_true", help="只做检测诊断")
    parser.add_argument("--clean", action="store_true", help="清理旧验收输出后重跑")
    args = parser.parse_args()

    sample_dir = args.sample_dir
    if not sample_dir.is_dir():
        print(f"样本目录不存在：{sample_dir}")
        return 1
    files = sorted(
        p for p in sample_dir.iterdir() if p.suffix.lower() in SUFFIXES
    )
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"未在 {sample_dir} 找到图片")
        return 1

    if args.diagnose:
        diagnose(files[:1])
        return 0

    print(f"样本目录：{sample_dir}，本次 {len(files)} 张")
    sources = []
    for path in files:
        with Image.open(path) as image:
            info = {
                "name": path.name,
                "bytes": path.stat().st_size,
                "size": list(image.size),
                "mode": image.mode,
                "dpi": str(image.info.get("dpi")),
            }
        sources.append(info)
        print(
            f"  {info['name']} | {info['size']} | {info['mode']} | "
            f"dpi={info['dpi']} | {info['bytes']} B"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for old in OUTPUT_DIR.glob("*.png"):
            old.unlink()
    started = time.perf_counter()
    result = run(
        BatchConfig(source_files=files, output_dir=OUTPUT_DIR),
        progress=lambda done, total, stage: print(f"  [{done}/{total}] {stage}"),
        cancel=lambda: False,
    )
    elapsed = time.perf_counter() - started

    outputs = sorted(OUTPUT_DIR.glob("*.png"))
    build_index(outputs, INDEX_PATH)

    report = {
        "sample_dir": str(sample_dir),
        "sources": sources,
        "elapsed_seconds": round(elapsed, 2),
        "ok_count": len(result.ok),
        "failed": [[str(p), reason] for p, reason in result.failed],
        "review": [str(p) for p in result.review],
        "source_counts": {
            path.name: sum(item.source == str(path.resolve()) for item in result.ok)
            for path in files
        },
        "results": [
            {
                "file": item.path.name,
                "source": item.source,
                "rotation": item.rotation,
                "orientation": item.orientation,
                "flags": item.flags,
                "tilt_deg": round(item.tilt_deg, 2),
                "confidence": round(item.confidence, 2),
                "size": list(Image.open(item.path).size),
                "dpi": str(Image.open(item.path).info.get("dpi", "")),
            }
            for item in result.ok
        ],
        "output_dir": str(OUTPUT_DIR),
        "index_image": str(INDEX_PATH),
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"耗时 {elapsed:.2f}s | 成功 {len(result.ok)} | "
        f"失败 {len(result.failed)} | 待复核 {len(result.review)} | "
        f"结果目录共 {len(outputs)} 张 PNG"
    )
    print(f"报告：{REPORT_PATH}")
    print(f"索引图：{INDEX_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
