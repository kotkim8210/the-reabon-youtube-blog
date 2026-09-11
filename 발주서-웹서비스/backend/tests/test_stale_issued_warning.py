"""이전 발주분 제외 시 발주일 표기 + 이틀째 미출고 경고 (2026-09-11 임재숙 사고).

발주서엔 넣었지만 거래처가 못 받은 주문이 '이전 발주분'으로 조용히 빠져 이틀 지연됐다.
"""
from datetime import date, timedelta

from app import main as app_main


def _dates(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_excluded_names_show_issue_date_and_stale_warning(monkeypatch):
    monkeypatch.setattr(app_main, "_today_kst", lambda: date.today().isoformat())
    stats = {"total": 1}
    dup_names = ["임재숙", "김새주문"]
    dup_keys = ["12102839347891|3kg1박스", "999|3kg1박스"]
    issued_dates = {"12102839347891|3kg1박스": _dates(2), "999|3kg1박스": _dates(1)}
    out = app_main._annotate_excluded(stats, 2, dup_names, dup_keys, issued_dates)
    assert out["duplicate_skipped"] == 2
    names = out["duplicate_skipped_names"]
    assert "임재숙(" in names and "발주분" in names
    # 이틀째 미출고만 경고, 어제 발주분은 정상(다음날 출고 대기)
    assert len(out["needs_check"]) == 1
    assert "임재숙" in out["needs_check"][0] and "2일째" in out["needs_check"][0]
    assert "김새주문" not in out["needs_check"][0]


def test_no_exclusion_leaves_stats_untouched():
    stats = {"total": 3}
    assert app_main._annotate_excluded(stats, 0, [], [], {}) == {"total": 3}
