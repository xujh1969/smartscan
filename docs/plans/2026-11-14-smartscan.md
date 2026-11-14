# SmartScan 老照片批量拆分工具 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建一个离线 Windows 图形界面程序，把平铺扫描的老照片自动检测、扶正、拆分成单张 PNG，并提供缩略图预览与 ±90° 旋转存盘。

**Architecture:** PySide6 三页 GUI 通过 `pipeline` 编排纯逻辑领域模块；检测走「背景差分切簇 + 原始分辨率直线段/色阶拟合四边形」，拆分阶段唯一一次 Lanczos 扶正，输出 PNG 自带 `tEXt`/`pHYs`/`iCCP` 元数据。领域模块不依赖 Qt，全部可单测。

**Tech Stack:** Python 3.14（兼容 3.11+）、PySide6 6.12、OpenCV 4.13、Pillow 12.1、NumPy 2.4、pytest 9.2、PyInstaller（打包阶段）。

---

## 执行约定

- 遵守 TDD：每个任务先写失败测试 → 运行确认失败 → 写最小实现 → 运行确认通过。
- 测试命令统一：`python -m pytest tests/ -q`。单测文件命令在各任务给出。
- 本项目工作区**不是 git 仓库**，且用户未要求提交；计划中的 commit 步骤不执行，改为在 `progress.md` 记录验证结果（环境约束优先于技能模板）。
- 用户已明确要求「文档生成后进入正式开发」，因此批次之间不中断等待审批，统一在最终回复汇报验证输出。
- 所有路径相对于仓库根目录。

## Task 1: 项目骨架与测试基础设施

**Files:** Create `requirements.txt`, `pytest.ini`, `smartscan/__init__.py`, `tests/__init__.py`, `run.py`, `README.md`

**Step 1: 写失败测试** — `tests/test_package.py`

```python
def test_package_exposes_version():
    import smartscan
    assert isinstance(smartscan.__version__, str) and smartscan.__version__
```

**Step 2:** `python -m pytest tests/test_package.py -q` → FAIL（`smartscan.__version__` 不存在或包不可导入）

**Step 3: 最小实现** — `smartscan/__init__.py` 导出 `__version__ = "1.0.0"`；`requirements.txt` 固定依赖范围；`pytest.ini` 设置 `testpaths=tests`；`run.py` 作为 GUI 入口桩；`README.md` 写运行/测试/打包说明。

**Step 4:** `python -m pytest tests/test_package.py -q` → PASS

## Task 2: 数据模型（`models.py`）

**Files:** Test `tests/test_models.py`; Create `smartscan/models.py`

**Step 1:** 测试 `PhotoQuad` 四个点按左上/右上/右下/左下排序、`SplitResult` 默认标记位、`BatchConfig` 拒绝空文件列表。

```python
def test_photo_quad_normalizes_point_order():
    q = PhotoQuad(points=[(10, 0), (0, 0), (0, 10), (10, 10)])
    assert q.ordered() == [(0, 0), (10, 0), (10, 10), (0, 10)]

def test_batch_config_rejects_empty():
    with pytest.raises(ValueError):
        BatchConfig(source_files=[], output_dir=Path("out"))
```

**Step 2:** `python -m pytest tests/test_models.py -q` → FAIL（模块不存在）

**Step 3:** 用 `@dataclass` 实现 `PhotoQuad`, `SplitResult`, `BatchConfig`, `OrientationState`, `Flags`；`ordered()` 用「按 x+y 最小为左上、按角度排序」的确定性算法；`BatchConfig.__post_init__` 校验。

**Step 4:** → PASS

## Task 3: 几何（`geometry.py`）

**Files:** Test `tests/test_geometry.py`; Create `smartscan/geometry.py`

**Step 1:** 测试倾角计算、内接矩形、点旋转、外接框：

```python
def test_tilt_angle_of_rotated_square():
    quad = [(10, 0), (20, 10), (10, 20), (0, 10)]
    assert abs(tilt_angle(quad) - 45.0) < 1e-6

def test_largest_inscribed_rect_never_exceeds_quad_bbox():
    rect = largest_inscribed_rect(quad, tilt_deg=10.0, shape=(100, 80))
    assert 0 <= rect[0] < rect[2] <= 100 and 0 <= rect[1] < rect[3] <= 80
```

**Step 2:** → FAIL（模块不存在）

**Step 3:** numpy 实现：`order_quad`（质心 + atan2 排序）、`tilt_angle`（最长边方向，归一化到 ±90°）、`largest_inscribed_rect`（旋转矩形内最大轴对齐矩形解析解，比例不小于内接矩形 95%）、`rotate_points`、`quad_bbox`。

**Step 4:** → PASS

## Task 4: 命名与重跑判定（`naming.py`）

**Files:** Test `tests/test_naming.py`; Create `smartscan/naming.py`

**Step 1:** 测试跨目录同名文件得到不同输出名、同内容同路径重跑被识别为已完成、目标已存在时自动让位不覆盖：

```python
def test_same_basename_different_dirs_get_distinct_names(tmp_path):
    a, b = tmp_path / "a" / "scan.tif", tmp_path / "b" / "scan.tif"
    a.parent.mkdir(); b.parent.mkdir(); a.write_bytes(b"A"); b.write_bytes(b"B")
    assert next_name(1, content_hash(a)) != next_name(2, content_hash(b))

def test_existing_output_is_never_overwritten(tmp_path):
    target = tmp_path / "001_deadbeef.png"; target.write_bytes(b"KEEP")
    chosen = reserve_name(tmp_path, "001_deadbeef.png")
    assert chosen != target and target.read_bytes() == b"KEEP"
```

**Step 2:** → FAIL

**Step 3:** `content_hash` 流式 sha256 取前 8 位；`next_name` 用三位序号；`find_existing` 按「完整路径 + 内容哈希」比对；`reserve_name` 冲突时追加 `_2`、`_3` 后缀。

**Step 4:** → PASS

## Task 5: PNG 元数据与原子写盘（`metadata.py`）

**Files:** Test `tests/test_metadata.py`; Create `smartscan/metadata.py`

**Step 1:** 测试写入后能回读 DPI、ICC、来源、旋转状态，且临时文件不残留：

```python
def test_png_roundtrip_keeps_dpi_and_text(tmp_path):
    img = Image.new("RGB", (12, 8), (200, 180, 160))
    p = write_png(tmp_path / "p.png", img, dpi=(600, 600), icc=None,
                  text={"source": r"C:\a\scan.tif", "rotation": "90"})
    reopened = Image.open(p)
    assert reopened.info["dpi"] == (600, 600)
    assert read_metadata(p)["source"] == r"C:\a\scan.tif"
    assert read_metadata(p)["rotation"] == "90"
    assert not list(tmp_path.glob("*.tmp"))
```

**Step 2:** → FAIL

**Step 3:** Pillow `PngInfo` 写 `tEXt`；`dpi=` 写 `pHYs`；`icc_profile=` 写 `iCCP`；写临时文件后 `os.replace`；`read_metadata` 回读 `im.info` 与 `im.text`。

**Step 4:** → PASS

## Task 6: 90° 无损旋转与状态（`rotation.py`）

**Files:** Test `tests/test_rotation.py`; Create `smartscan/rotation.py`

**Step 1:** 测试四次顺时针回到原图（像素完全一致）、状态循环、从基准图一次性应用：

```python
def test_four_clockwise_rotations_are_pixel_identical():
    arr = np.arange(24, dtype=np.uint8).reshape(4, 6)
    out = arr
    for _ in range(4):
        out = rotate_90(out, clockwise=True)
    assert np.array_equal(out, arr)

def test_state_wraps_and_apply_from_base():
    assert state_after(270, 1) == 0
    assert state_after(0, -1) == 270
    base = np.arange(24, dtype=np.uint8).reshape(4, 6)
    assert np.array_equal(apply_state(base, 0), base)
```

**Step 2:** → FAIL

**Step 3:** `np.rot90` 实现（无插值）；`state_after` 模 360；`apply_state` 只用 `k=state//90` 一次旋转，杜绝代际损失。

**Step 4:** → PASS

## Task 7: 方向保守投票（`orientation.py`）

**Files:** Test `tests/test_orientation.py`; Create `smartscan/orientation.py`

**Step 1:** 测试证据不足一律 `unknown`、单一信号不触发自动旋转、多信号一致才返回角度：

```python
def test_no_evidence_returns_unknown():
    blank = np.full((64, 64, 3), 180, np.uint8)
    assert should_auto_rotate(vote(blank)) == 0
    assert vote(blank).state == "unknown"

def test_single_weak_signal_does_not_auto_rotate():
    v = OrientationVote(state="unknown", signals={"horizon": 90}, confidence=0.4)
    assert should_auto_rotate(v) == 0
```

**Step 2:** → FAIL

**Step 3:** `vote` 用 cv2 计算水平/垂直直线占比、上下半区亮度差（天空/地面）、人脸级联（若级联可用，缺席即不计票）；`should_auto_rotate` 要求 ≥2 个信号一致且 confidence ≥ 0.8，否则返回 0（保持原样）。**不做 180°**。

**Step 4:** → PASS

## Task 8: 接缝检测与四边形拟合（`detection.py`）

**Files:** Test `tests/test_detection.py`; Create `smartscan/detection.py`

**Step 1:** 用合成图测试：白底上两块紧贴不同灰度矩形 → 检到 2 个四边形；带 10° 倾斜 → 角度误差 < 2°；有阴影线 → 取内侧边；压角重叠 → 遮挡关系正确：

```python
def test_two_touching_rectangles_are_detected():
    img = synthetic_scan([((0, 0), (100, 80), 150), ((100, 0), (100, 80), 90)])
    quads = detect_quads(img, background=estimate_background(img))
    assert len(quads) == 2

def test_tilted_quad_angle_within_two_degrees():
    img = synthetic_tilted_scan(10.0)
    quads = detect_quads(img, background=estimate_background(img))
    assert len(quads) == 1 and abs(quads[0].tilt_deg - 10.0) < 2.0
```

**Step 2:** → FAIL

**Step 3:** 实现 `estimate_background`（四角区域中位数）、`find_photo_cluster`（背景差分 + 形态学）、`detect_quads`（原始分辨率 Canny + HoughLinesP/LSD → 按方向聚类 → 平行/直角配对 → 轮廓近似 → 置信度）、`resolve_occlusion`（T 结点与边缘连续性，低置信度标 `uncertain`）。阴影线取内侧平行边。

**Step 4:** → PASS

## Task 9: 裁切、扶正与填充（`split.py`）

**Files:** Test `tests/test_split.py`; Create `smartscan/split.py`

**Step 1:** 测试输出水平、四角为背景色、照片内容未被内接裁掉、缺口填充：

```python
def test_deskew_output_is_horizontal_and_corners_filled():
    img = synthetic_tilted_scan(10.0, photo_value=60, background=240)
    quad = detect_quads(img, estimate_background(img))[0]
    out = deskew_and_crop(img, quad, background=240)
    assert out.shape[0] > 0 and out.shape[1] > 0
    assert tuple(out[0, 0]) == (240, 240, 240)
    assert np.mean(out) < 240
```

**Step 2:** → FAIL

**Step 3:** `deskew_and_crop` 以 quad 中心做一次 `cv2.warpAffine`（`INTER_LANCZOS4`、`BORDER_CONSTANT` 填背景色），再按 `largest_inscribed_rect` 裁切；`fill_gaps` 用同一背景色填充 `incomplete`/`uncertain` 的遮挡缺口，并把多边形写入元数据。全程不缩放。

**Step 4:** → PASS

## Task 10: 批处理管线（`pipeline.py`）

**Files:** Test `tests/test_pipeline.py`; Create `smartscan/pipeline.py`

**Step 1:** 测试取消后已完成结果保留、单文件失败不中断批次、重跑跳过、结果目录只有 PNG：

```python
def test_failure_of_one_file_does_not_stop_batch(tmp_path, monkeypatch):
    good, bad = make_scan(tmp_path / "g.tif"), tmp_path / "missing.tif"
    results = run(BatchConfig([good, bad], tmp_path / "out"), progress=lambda *_: None, cancel=lambda: False)
    assert len(results.ok) == 1 and len(results.failed) == 1
    assert all(p.suffix == ".png" for p in (tmp_path / "out").iterdir())
```

**Step 2:** → FAIL

**Step 3:** `run` 逐文件 try/except、检查 cancel、`estimate_disk_need`（源总字节 × 3）、`atomic_save`；`BatchResult` 汇总 ok/failed/review；输出目录只写 PNG，日志写 `%LOCALAPPDATA%\SmartScan\logs\`。

**Step 4:** → PASS

## Task 11: PySide6 三页 GUI（`gui/`）

**Files:** Test `tests/test_gui.py`; Create `smartscan/gui/__init__.py`, `app.py`, `pages/select_page.py`, `progress_page.py`, `result_page.py`, `thumbnails.py`

**Step 1:** offscreen 构造测试：

```python
def test_main_window_has_three_pages_and_start_button(qapp):
    w = MainWindow()
    assert w.page_count() == 3
    assert w.select_page.start_button.isEnabled() is False
```

**Step 2:** `set QT_QPA_PLATFORM=offscreen; python -m pytest tests/test_gui.py -q` → FAIL

**Step 3:** `MainWindow` 用 `QStackedWidget`；选择页支持多选/拖拽/移除/输出目录/设置/开始按钮（有文件且有输出目录才启用）；进度页 `QProgressBar` + 阶段标签 + 取消 + `QThread` 后台 worker；结果页 `QListWidget`/网格缩略图 + 角标筛选 + 每张两个旋转按钮 + 多选批量旋转 + 快捷键；旋转通过 `rotation.apply_state` + `metadata.write_png` 原子落盘，成功后刷新缩略图。

**Step 4:** → PASS

## Task 12: 端到端与验收验证

**Files:** Modify `progress.md`, `findings.md`; Test `tests/test_end_to_end.py`

**Step 1:** 写端到端测试：合成一张含 2 张紧贴 + 1 张倾斜 + 1 组重叠的扫描图 → `pipeline.run` → 断言输出数量、DPI 保持、PNG 元数据可回读、结果目录只有 PNG、重跑不新增也不覆盖。

**Step 2:** 运行 → FAIL（若链路有缺口）

**Step 3:** 修复链路缺口（不新增功能）

**Step 4:** `python -m pytest tests/ -q` 全绿；`QT_QPA_PLATFORM=offscreen python run.py --smoke` 启动窗口并自动退出，退出码 0；`python -m compileall -q smartscan` 通过。

**Step 5:** 对照设计规格第 9 节逐条勾验收清单，把证据写入 `progress.md`。

---

## 打包（开发完成后，非 TDD 任务）

`pyinstaller -F -w -n SmartScan run.py`，产物 `dist/SmartScan.exe`；验证在离线环境双击可启动。PyInstaller 需 `pip install pyinstaller`，不在运行期依赖清单内。
