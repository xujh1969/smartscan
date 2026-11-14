from PIL import Image

from smartscan.metadata import build_text_chunk, read_metadata, write_png


def test_png_roundtrip_keeps_dpi_and_text(tmp_path):
    img = Image.new("RGB", (12, 8), (200, 180, 160))
    p = write_png(
        tmp_path / "p.png",
        img,
        dpi=(600, 600),
        icc=None,
        text={"source": r"C:\a\scan.tif", "rotation": "90"},
    )

    reopened = Image.open(p)
    assert tuple(round(v) for v in reopened.info["dpi"]) == (600, 600)
    md = read_metadata(p)
    assert md["source"] == r"C:\a\scan.tif"
    assert md["rotation"] == "90"
    assert not list(tmp_path.glob("*.tmp"))


def test_build_text_chunk_contains_required_fields():
    text = build_text_chunk(
        source="s.tif",
        digest="abcdef12",
        quad=[(0, 0), (1, 0), (1, 1), (0, 1)],
        tilt_deg=3.5,
        rotation=0,
        orientation="unknown",
        flags=["incomplete"],
        confidence=0.8,
    )
    assert text["digest"] == "abcdef12"
    assert text["rotation"] == "0"
    assert text["orientation"] == "unknown"
    assert "incomplete" in text["flags"]


def test_write_png_retries_atomic_replace_when_windows_locks_the_file(
    tmp_path, monkeypatch
):
    import smartscan.metadata as metadata

    original = metadata.os.replace
    calls = {"count": 0}

    def flaky_replace(source, destination):
        calls["count"] += 1
        if calls["count"] == 1:
            raise PermissionError("file temporarily locked")
        return original(source, destination)

    monkeypatch.setattr(metadata.os, "replace", flaky_replace)

    path = write_png(
        tmp_path / "p.png",
        Image.new("RGB", (4, 4)),
        text={"source": "s.tif"},
    )

    assert path.exists()
    assert calls["count"] == 2
    assert read_metadata(path)["source"] == "s.tif"
