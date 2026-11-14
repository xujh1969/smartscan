# Boundary Review Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Preview, edit, remember photo crop boxes and export the saved selections in one batch.

**Architecture:** A small review store validates native-pixel quadrilaterals and persists them by full source hash and image size. The existing pipeline consumes confirmed boxes before automatic detection and includes their revision in repeat-run matching. A Qt scene/dialog edits corners, draws/deletes boxes and saves them while navigating; the selection page launches it and dispatches the confirmed sources to the existing batch worker.

**Tech Stack:** Python, NumPy/OpenCV, Pillow, PySide6, pytest.

## Global Constraints

- Keep original scan files read-only; preserve native resolution, DPI and ICC on export.
- Store confirmed boxes in the local SmartScan configuration directory.
- Never overwrite existing exported files; changed box revisions can re-export.
- No cloud uploads or production AI dependencies in this change.
- User approved the design and specifically requested editable, addable, deletable boxes remembered for one batch crop.

### Task 1: Store and export reviewed boxes

**Files:** create `smartscan/review.py`, `tests/test_review.py`; modify `smartscan/pipeline.py`.

**Interfaces:** `save_review(source, points) -> Review`; `load_review(source) -> Review | None`; `Review.revision`, `Review.quads()`.

- [x] Write failing tests for round-trip, source-content invalidation, invalid quadrilaterals and damaged cache.
- [x] Implement full SHA-256 identity, dimension validation, atomic JSON writes and stable geometry revision.
- [x] Write failing pipeline tests: a horizon photo manually split into specified boxes must export those boxes; same revision skips; changed revision re-exports without overwriting.
- [x] Let the pipeline prefer saved reviews, skip automatic occlusion inference for reviewed geometry and match `review_revision` metadata.
- [x] Verify with `python -m pytest tests/test_review.py -q`, then the complete suite.

### Task 2: Mouse editor and persistence

**Files:** create `smartscan/gui/review_dialog.py`, `tests/test_review_gui.py`; modify `smartscan/gui/pages/select_page.py`.

**Interfaces:** `CropScene.set_image`, `set_quads`, `points`, `add_quad`, `remove_selected`; `ReviewDialog.export_requested(list)`.

- [x] Write failing Qt tests that drag a corner, draw a new box, delete a selected box and preserve unselected boxes.
- [x] Implement a native-coordinate scene with four draggable corner handles, drawing mode, deletion, wheel zoom and fit-to-window.
- [x] Load cached geometry immediately; otherwise compute initial candidates in a worker so the editor stays responsive.
- [x] Save valid boxes on navigation and explicit save; export all saved/confirmed sources in original order in a single existing batch job.
- [x] Keep dirty state on save errors, handle source read failures visibly, and close the dialog safely while detection is running.
- [x] Add the selection-page entry point without changing the existing direct-processing path.
- [x] Verify with `python -m pytest tests/test_review_gui.py tests/test_gui.py -q` and the full suite.

### Task 3: Delivery and model findings

**Files:** update `README.md`, approved design status, version and this ledger; create a small-model assessment note.

- [x] Exercise the real scan editor with the difficult 2×2 layout; save four corrected boxes and export four complete photos from the original image.
- [x] Verify PNG decoding, original DPI and repeat-run/changed-revision behavior.
- [x] Research official SAM 2.1 Tiny, FastSAM and small rotated-box detector capabilities; distinguish candidates from measured gains.
- [x] Run compile, tests, GUI startup and diff checks; request one fresh review and resolve material findings.

## Execution ledger

- Ruling: continue in the user-visible SmartScan directory on `feat/boundary-review`, preserving the prior uncommitted fixes, rather than moving the active work out of the directory the user requested.
- Ruling: no intermediate commits of the combined previous/current work; leave a reviewable working tree and do not push.
- Ruling: navigate/save boxes before a single batch export; do not silently export unvisited scans as confirmed.

- Completed store/export tests: stable saved revisions, full-hash invalidation, invalid-quad rejection, bad-cache fallback, reviewed-only export, changed revision and per-crop resume.
- Completed scene/dialog tests: real mouse corner edits, add/delete, selected shared corners, middle/space pan, wheel zoom, saved navigation/reopen, read/detection/save failures, worker closure and fresh-process shutdown.
- Ruling: use plain native graphics items and scene-owned mouse editing to keep corner lifetimes simple. PySide6 6.12.0 still exhibited process shutdown crashes in local tests; identical editor code passed with clean exits on 6.9.3, so pin that verified runtime and check it in run.bat.
- Fresh review: source identity mismatch was reproduced, fixed with expected_digest, and independently rechecked; no remaining actionable findings in that pass. A reviewed-only batch now rechecks every confirmed source and refuses automatic fallback after file replacement.
- Real scan 28: deleted initial merged candidate, mouse-drew and adjusted four boxes, saved/restored, exported four original-resolution 300 DPI PNGs, verified no duplicates on repeat and unchanged source hash. CUA reached native preview, but further computer-use calls were aborted; complete mouse workflow validated with offscreen Qt events.
- Validation: 94 tests passed, GUI smoke passed, diff check passed. Artifacts remain ignored/private under verify_output; no commits or pushes performed.
