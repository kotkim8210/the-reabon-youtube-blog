"""이전 발주분 제외 시 발주일 표기 + 영업일 2일↑ 미출고는 자동 재발주 (2026-10-12 호박고구마 2건 누락 사고).

2026-09-11(임재숙)엔 '이틀째 미출고' 경고만 띄웠는데, 경고를 못 보고 넘어가 10/8 해달 휴무일에 만든
발주서 2건(김영옥·정복순)이 10/12까지 '이전 발주분'으로 빠졌다. 이제 경고 대신 자동으로 다시 넣는다.
"""
from datetime import date, timedelta

from app import main as app_main
from app.processors import issued_orders


def _dates(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_excluded_names_show_issue_date_without_stale_warning(monkeypatch):
    monkeypatch.setattr(app_main, "_today_kst", lambda: date.today().isoformat())
    stats = {"total": 1}
    dup_names = ["김새주문"]
    dup_keys = ["999|3kg1박스"]
    issued_dates = {"999|3kg1박스": _dates(1)}
    out = app_main._annotate_excluded(stats, 1, dup_names, dup_keys, issued_dates)
    assert out["duplicate_skipped"] == 1
    assert "김새주문(" in out["duplicate_skipped_names"] and "발주분" in out["duplicate_skipped_names"]
    assert "needs_check" not in out          # '체크 해제하세요' 경고는 폐지


def test_reissued_rows_are_labelled_with_original_issue_date(monkeypatch):
    monkeypatch.setattr(app_main, "_today_kst", lambda: "2026-10-12")
    issued_dates = {"15103446848104|1박스2kg(한입)": "2026-10-08"}
    out = app_main._annotate_excluded({"total": 3}, 0, [], [], issued_dates,
                                      reissued=[("김영옥", "15103446848104|1박스2kg(한입)")])
    assert out["reissued"] == 1
    assert out["reissued_names"] == "김영옥(10/8 발주분)"
    assert out["total"] == 3


def test_no_exclusion_leaves_stats_untouched():
    stats = {"total": 3}
    assert app_main._annotate_excluded(stats, 0, [], [], {}) == {"total": 3}


# ── 영업일 계산: 2026-10-08(목) 발주 → 10/9(금, 한글날이지만 평일로 셈) 10/12(월) = 2영업일 → 재발주 ──
def test_business_days_count_weekdays_only():
    assert issued_orders.business_days_since("2026-10-08", "2026-10-09") == 1   # 다음날 → 아직 제외
    assert issued_orders.business_days_since("2026-10-08", "2026-10-10") == 1   # 토요일에 돌리면 평일은 금요일 하루뿐 → 아직 제외
    assert issued_orders.business_days_since("2026-10-08", "2026-10-12") == 2   # 사고 당일: 금·월 → 재발주
    assert issued_orders.business_days_since("2026-10-09", "2026-10-12") == 1   # 금요일 발주 → 월요일은 아직 제외
    assert issued_orders.business_days_since("2026-10-09", "2026-10-13") == 2   # 화요일에 재발주
    assert issued_orders.business_days_since("2026-10-12", "2026-10-12") == 0
    assert issued_orders.business_days_since("깨진날짜", "2026-10-12") == 0      # 못 읽으면 계속 제외(안전)


def test_stale_keys_split_from_exclusions(monkeypatch):
    dates = {"A|x": "2026-10-08", "B|x": "2026-10-09", "C": "2026-10-01"}
    stale = issued_orders.stale_issued_keys(dates, "2026-10-12")
    assert stale == {"A|x", "C"}                 # B는 금요일 발주 → 월요일엔 아직 제외 대상
