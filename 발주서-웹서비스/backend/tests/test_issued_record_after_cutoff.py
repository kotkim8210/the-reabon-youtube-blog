"""발주 마감(10:30 KST) 이후 생성분도 발주 이력에 기록해야 한다.

2026-08-17 16:17에 만든 제주다팜 발주서(청사과 90·콜라비 1·미니밤호박 41)가
마감 이후라는 이유로 미기록됐고, 다음날 아침 자동제외가 그 주문들을 몰라
132건이 통째로 중복 발주됐다. 시각만으로 실제 발주와 미리보기를 구분할 수 없으므로
항상 기록한다 — 잘못 기록되면 다음날 제외 목록에 이름이 떠서 되살릴 수 있지만,
빠뜨리면 거래처로 중복 발주가 나간다.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app import main

KST = timezone(timedelta(hours=9))


class _FrozenDateTime:
    """main 모듈이 쓰는 datetime.now(tz)만 고정."""

    frozen = datetime(2026, 8, 17, 16, 17, tzinfo=KST)

    @classmethod
    def now(cls, tz=None):
        return cls.frozen.astimezone(tz) if tz else cls.frozen


def _stats(order_id: str, option: str) -> dict:
    return {
        "options": [
            {
                "coupang_option_keyword": option,
                "orders": [{"order_id": order_id}],
            }
        ]
    }


@pytest.fixture
def recorded(monkeypatch):
    """record_issued_orders 호출을 가로채 기록 내용을 돌려준다."""
    calls = []

    async def _fake_record(section, order_ids, filename, ymd):
        calls.append({"section": section, "ids": list(order_ids), "file": filename, "ymd": ymd})

    monkeypatch.setattr(main.database, "record_issued_orders", _fake_record)
    return calls


def _freeze(monkeypatch, at: datetime) -> None:
    _FrozenDateTime.frozen = at
    monkeypatch.setattr(main, "datetime", _FrozenDateTime)


@pytest.mark.parametrize(
    "at, label",
    [
        (datetime(2026, 8, 17, 16, 17, tzinfo=KST), "마감 이후(사고 재현 시각)"),
        (datetime(2026, 8, 17, 23, 59, tzinfo=KST), "심야"),
        (datetime(2026, 8, 17, 9, 31, tzinfo=KST), "마감 이전"),
    ],
)
def test_records_regardless_of_generation_time(monkeypatch, recorded, at, label):
    _freeze(monkeypatch, at)

    asyncio.run(
        main._record_issued(
            "kolrabi",
            "제주다팜_아이티소프트_청사과발주(20260817).xlsx",
            _stats("30012345678", "청사과 소과(가정용) 2kg"),
        )
    )

    assert len(recorded) == 1, f"{label}에 발주 이력이 기록되지 않았다"
    assert recorded[0]["section"] == "kolrabi"
    assert recorded[0]["ids"] == ["30012345678|청사과소과(가정용)2kg"]
    assert recorded[0]["ymd"] == "2026-08-17"


def test_extra_ids_merged_after_cutoff(monkeypatch, recorded):
    """토스 등 extra_ids도 마감 이후 생성분에서 함께 기록된다."""
    _freeze(monkeypatch, datetime(2026, 8, 17, 16, 20, tzinfo=KST))

    asyncio.run(
        main._record_issued(
            "kolrabi",
            "제주다팜_아이티소프트_미니밤호박발주 추가건(20260817).xlsx",
            _stats("30099999999", "미니밤호박 3kg"),
            extra_ids=["TOSS-1|미니밤호박3kg"],
        )
    )

    assert recorded[0]["ids"] == ["30099999999|미니밤호박3kg", "TOSS-1|미니밤호박3kg"]
