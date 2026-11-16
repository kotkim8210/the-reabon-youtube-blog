"""pyflakes 깨끗 유지 — 미사용 import·정의 안 된 이름(NameError 예비군)을 테스트 단계에서 잡는다.

커밋 전 훅(.githooks/pre-commit)도 같은 검사를 한다. 설치: python -m pip install pyflakes
"""

from pathlib import Path

import pytest

pytest.importorskip("pyflakes")


def test_backend_is_pyflakes_clean():
    from pyflakes.api import checkRecursive
    from pyflakes.reporter import Reporter
    import io

    backend = Path(__file__).resolve().parents[1]
    out, err = io.StringIO(), io.StringIO()
    count = checkRecursive([str(backend / "app"), str(backend / "tests")], Reporter(out, err))
    assert count == 0, out.getvalue() + err.getvalue()
