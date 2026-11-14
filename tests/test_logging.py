from smartscan.models import BatchConfig
from smartscan.pipeline import log_file_path, run
from tests.synthetic import make_scan_file


def test_batch_log_is_written_outside_the_output_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    source = make_scan_file(tmp_path / "g.tif")
    output = tmp_path / "out"

    run(
        BatchConfig([source], output),
        progress=lambda *args: None,
        cancel=lambda: False,
    )

    log = log_file_path()
    assert log.exists()
    assert log.parent != output
    assert "done" in log.read_text(encoding="utf-8")
    assert all(p.suffix == ".png" for p in output.iterdir())
