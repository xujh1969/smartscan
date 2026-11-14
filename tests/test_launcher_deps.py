"""启动链路必须能在 Python 3.14 上安装，且版本不能与依赖清单漂移。

PySide6 6.9.3 声明 Requires-Python >=3.9,<3.14，在 Python 3.14 上无可用
wheel；run.bat 又硬编码断言这个版本，导致每次启动都触发一次必然失败的
pip install。这里固定两处的行为契约。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyside_lines() -> list[str]:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("PySide6")
    ]


def test_python_314_has_its_own_installable_pyside6_pin():
    lines = _pyside_lines()

    modern = [line for line in lines if 'python_version >= "3.14"' in line]

    assert len(modern) == 1
    assert "PySide6==" in modern[0]
    assert "6.9.3" not in modern[0]


def test_older_python_keeps_the_verified_pin():
    lines = _pyside_lines()

    legacy = [line for line in lines if 'python_version < "3.14"' in line]

    assert len(legacy) == 1
    assert "PySide6==6.9.3" in legacy[0]


def test_launcher_checks_exactly_the_pins_in_requirements():
    bat = (ROOT / "run.bat").read_text(encoding="utf-8")
    pins = {
        match.group(1)
        for line in _pyside_lines()
        if (match := re.search(r"PySide6==([0-9]+\.[0-9]+\.[0-9]+)", line))
    }
    mentioned = set(re.findall(r"[0-9]+\.[0-9]+\.[0-9]+", bat))

    assert pins
    assert mentioned == pins
