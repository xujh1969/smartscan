from smartscan.naming import content_hash, find_existing, next_name, reserve_name


def test_same_basename_different_dirs_get_distinct_names(tmp_path):
    a = tmp_path / "a" / "scan.tif"
    b = tmp_path / "b" / "scan.tif"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_bytes(b"A")
    b.write_bytes(b"B")

    assert len(content_hash(a)) == 8
    assert next_name(1, content_hash(a)) != next_name(2, content_hash(b))


def test_existing_output_is_never_overwritten(tmp_path):
    target = tmp_path / "001_deadbeef.png"
    target.write_bytes(b"KEEP")

    chosen = reserve_name(tmp_path, "001_deadbeef.png")

    assert chosen != target
    assert target.read_bytes() == b"KEEP"
    assert chosen.name.endswith(".png")


def test_find_existing_requires_both_path_and_digest():
    metas = [{"path": "x.png", "source": r"C:\a\s.tif", "digest": "abcd1234"}]
    assert find_existing(metas, r"C:\a\s.tif", "abcd1234") == "x.png"
    assert find_existing(metas, r"C:\b\s.tif", "abcd1234") is None
    assert find_existing(metas, r"C:\a\s.tif", "other123") is None
