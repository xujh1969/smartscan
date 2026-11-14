from pathlib import Path

import pytest

from smartscan.models import BatchConfig, PhotoQuad, SplitResult


def test_photo_quad_normalizes_point_order():
    q = PhotoQuad(points=[(10, 0), (0, 0), (0, 10), (10, 10)])
    assert q.ordered() == [(0, 0), (10, 0), (10, 10), (0, 10)]


def test_batch_config_rejects_empty():
    with pytest.raises(ValueError):
        BatchConfig(source_files=[], output_dir=Path("out"))


def test_split_result_defaults_to_no_flags_and_zero_rotation():
    r = SplitResult(path=Path("001_abcd1234.png"), source="scan.tif", digest="abcd1234")
    assert r.rotation == 0
    assert r.flags == []
