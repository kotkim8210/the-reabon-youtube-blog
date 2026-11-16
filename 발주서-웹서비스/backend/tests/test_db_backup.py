"""DB 자동 백업 — 매일 1회 + 서버 시작 시 캐치업 + 다른 물리 디스크(미러) 복사.

종전엔 일요일 03:00(KST) 주 1회 CronTrigger에 misfire 유예가 기본값(1초)이라, 그 시각에 PC가
꺼져 있으면 그 주 백업이 통째로 빠졌다 — 2026-10-25 이후 백업 0건(data/backups에
backup_20261024_1800.db 하나뿐). 백업도 DB와 같은 디스크(C:)에만 있어 디스크가 죽으면 같이 잃는다.
"""

import asyncio
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from app import config
from app import scheduler as sched

KST = timezone(timedelta(hours=9))
NEW_NAME = "backup_20261116_123000.db"  # 2026-11-16 12:30:00 KST (UTC였으면 0330)


class _FrozenDateTime(datetime):
    """scheduler 모듈의 datetime.now / utcnow 만 2026-11-16 12:30:00 KST로 고정."""

    frozen = datetime(2026, 11, 16, 3, 30, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.frozen.astimezone(tz) if tz else cls.frozen.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return cls.frozen.replace(tzinfo=None)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """임시 DB 경로 + 임시 미러 폴더. 실제 data/·D: 드라이브는 건드리지 않는다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_file = data_dir / "suyikolla.db"
    mirror = tmp_path / "mirror"
    monkeypatch.setattr(config, "DATABASE_PATH", str(db_file))
    monkeypatch.setenv("BACKUP_MIRROR_DIR", str(mirror))
    monkeypatch.setattr(sched, "datetime", _FrozenDateTime)
    return {"db": db_file, "local": data_dir / "backups", "mirror": mirror}


def _run_backup(monkeypatch, db_file: Path):
    """임시 DB에 주문 1건을 넣고 backup_database()를 실행한다(db.get_db만 임시 연결로 교체)."""

    async def _go():
        conn = await aiosqlite.connect(str(db_file))
        try:
            await conn.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT)")
            await conn.execute("INSERT INTO orders VALUES ('30012345678')")
            await conn.commit()

            async def _fake_get_db():
                return conn

            monkeypatch.setattr(sched.db, "get_db", _fake_get_db)
            return await sched.backup_database()
        finally:
            await conn.close()

    return asyncio.run(_go())


def _orders_in(path: Path) -> list:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT id FROM orders").fetchall()


def _auto_backups(folder: Path) -> list[str]:
    return sorted(n for n in os.listdir(folder) if n.startswith("backup_2"))


def _set_mtime(path: Path, when: datetime) -> None:
    os.utime(path, (when.timestamp(), when.timestamp()))


def _missing_drive_dir() -> str:
    """이 PC에 없는 드라이브 문자의 경로(미러 디스크가 빠진 상황)."""
    for letter in "ZYXWVUTSRQPONMLKJIHGF":
        if not os.path.isdir(f"{letter}:\\"):
            return f"{letter}:/rj-balju-backups"
    pytest.skip("비어 있는 드라이브 문자가 없다")


# ── backup_database ────────────────────────────────────────────────


def test_backup_writes_local_and_mirror_with_kst_name(env, monkeypatch):
    result = _run_backup(monkeypatch, env["db"])

    local = env["local"] / NEW_NAME
    mirror = env["mirror"] / NEW_NAME
    assert local.exists(), f"KST 시각 이름의 로컬 백업이 없다: {sorted(os.listdir(env['local']))}"
    assert mirror.exists(), "다른 디스크(미러)로 복사되지 않았다"
    assert _orders_in(local) == [("30012345678",)]
    assert _orders_in(mirror) == [("30012345678",)]
    assert Path(result) == local


def test_backup_keeps_14_local_and_30_mirror(env, monkeypatch):
    env["local"].mkdir()
    env["mirror"].mkdir()
    old_local = [f"backup_202610{d:02d}_1230.db" for d in range(1, 21)]  # 10/01~10/20 (20개)
    old_local.append("backup_20261024_1800.db")  # 종전(UTC·4자리 시각) 이름도 같이 센다
    for name in old_local:
        (env["local"] / name).write_bytes(b"old")
    manual = ["backup_before_migration.db", "memo.txt"]  # 자동 백업 이름이 아니면 손대지 않는다
    for name in manual:
        (env["local"] / name).write_bytes(b"manual")
    old_mirror = [f"backup_2026{m:02d}{d:02d}_1230.db" for m in (9, 10) for d in range(1, 21)]  # 40개
    for name in old_mirror:
        (env["mirror"] / name).write_bytes(b"old")

    _run_backup(monkeypatch, env["db"])

    local_now = _auto_backups(env["local"])
    assert len(local_now) == 14
    assert local_now[-1] == NEW_NAME
    assert local_now[-2] == "backup_20261024_1800.db"
    assert "backup_20261008_1230.db" not in local_now  # 오래된 것부터 지운다
    assert "backup_20261009_1230.db" in local_now
    for name in manual:
        assert (env["local"] / name).exists(), f"자동 백업이 아닌 {name}을 지웠다"

    mirror_now = _auto_backups(env["mirror"])
    assert len(mirror_now) == 30
    assert mirror_now[-1] == NEW_NAME
    assert "backup_20260911_1230.db" not in mirror_now
    assert "backup_20260912_1230.db" in mirror_now


def test_mirror_drive_missing_keeps_local_backup(env, monkeypatch, caplog):
    monkeypatch.setenv("BACKUP_MIRROR_DIR", _missing_drive_dir())

    with caplog.at_level(logging.WARNING, logger="app.scheduler"):
        result = _run_backup(monkeypatch, env["db"])  # 예외 없이 끝나야 한다

    local = env["local"] / NEW_NAME
    assert local.exists()
    assert Path(result) == local
    assert any("미러" in r.getMessage() for r in caplog.records), "미러 드라이브 없음 경고가 없다"


def test_mirror_copy_failure_keeps_local_backup(env, monkeypatch, caplog):
    def _partial_copy(src, dst, *args, **kwargs):
        with open(dst, "wb") as f:  # 반쯤 쓰다가 디스크가 빠지거나 가득 찬 상황
            f.write(b"partial")
        raise OSError("디스크 가득 참")

    monkeypatch.setattr(sched.shutil, "copy2", _partial_copy)

    with caplog.at_level(logging.WARNING, logger="app.scheduler"):
        result = _run_backup(monkeypatch, env["db"])  # 예외 없이 끝나야 한다

    local = env["local"] / NEW_NAME
    assert local.exists()
    assert Path(result) == local
    leftovers = os.listdir(env["mirror"]) if env["mirror"].exists() else []
    assert leftovers == [], f"미러에 반쯤 쓴 파일이 남았다: {leftovers}"
    assert any("미러" in r.getMessage() for r in caplog.records), "미러 복사 실패 경고가 없다"


# ── 캐치업 판단 ─────────────────────────────────────────────────────


def test_backup_catchup_needed(tmp_path):
    now = datetime(2026, 11, 16, 14, 0, tzinfo=KST)
    folder = tmp_path / "backups"

    assert sched.backup_catchup_needed(str(folder), now=now)  # 폴더 자체가 없음
    folder.mkdir()
    assert sched.backup_catchup_needed(str(folder), now=now)  # 비어 있음
    (folder / "memo.txt").write_text("x")
    assert sched.backup_catchup_needed(str(folder), now=now)  # 자동 백업 파일이 아님

    last = folder / "backup_20261024_1800.db"  # 사고 당시 마지막 백업(10/25 03:00 KST)
    last.write_bytes(b"x")
    _set_mtime(last, datetime(2026, 10, 25, 3, 0, tzinfo=KST))
    assert sched.backup_catchup_needed(str(folder), now=now)

    yesterday = folder / "backup_20261115_123000.db"  # 25.5시간 전 → 캐치업
    yesterday.write_bytes(b"x")
    _set_mtime(yesterday, now - timedelta(hours=25, minutes=30))
    assert sched.backup_catchup_needed(str(folder), now=now)

    today = folder / "backup_20261116_123000.db"  # 1.5시간 전 → 불필요
    today.write_bytes(b"x")
    _set_mtime(today, now - timedelta(hours=1, minutes=30))
    assert not sched.backup_catchup_needed(str(folder), now=now)


# ── 스케줄 등록 ─────────────────────────────────────────────────────


def _fresh_scheduler(monkeypatch) -> AsyncIOScheduler:
    fresh = AsyncIOScheduler()
    monkeypatch.setattr(fresh, "start", lambda *a, **k: None)  # 실제로 돌리지는 않는다
    monkeypatch.setattr(sched, "scheduler", fresh)
    return fresh


def test_daily_backup_job_tolerates_missed_time(env, monkeypatch):
    fresh = _fresh_scheduler(monkeypatch)
    sched.start_scheduler()

    job = fresh.get_job("backup_database")
    assert isinstance(job.trigger, CronTrigger)
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["day_of_week"] == "*", "매일 돌아야 한다(종전: 일요일만)"
    assert (fields["hour"], fields["minute"]) == ("12", "30")
    assert str(job.trigger.timezone) == "Asia/Seoul"
    assert job.misfire_grace_time >= 3 * 3600, "그 시각에 PC가 잠들어 있었으면 깨어날 때 실행돼야 한다"
    assert job.coalesce is True
    ids = {j.id for j in fresh.get_jobs()}
    assert {"refresh_products", "refresh_orders", "renew_subscriptions",
            "backup_database", "refresh_supplier_price_monitors"} <= ids


def test_startup_catchup_when_last_backup_is_old(env, monkeypatch):
    env["local"].mkdir()
    last = env["local"] / "backup_20261024_1800.db"
    last.write_bytes(b"x")
    _set_mtime(last, datetime(2026, 10, 25, 3, 0, tzinfo=KST))  # 22일 전

    fresh = _fresh_scheduler(monkeypatch)
    sched.start_scheduler()

    job = fresh.get_job("backup_database_catchup")
    assert job is not None, "마지막 백업이 24시간 넘었는데 서버 시작 시 캐치업이 없다"
    assert isinstance(job.trigger, DateTrigger)
    assert job.func is sched.backup_database
    delay = job.trigger.run_date - _FrozenDateTime.frozen
    assert timedelta(minutes=1) <= delay <= timedelta(minutes=10), delay


def test_no_startup_catchup_when_backup_is_recent(env, monkeypatch):
    env["local"].mkdir()
    recent = env["local"] / "backup_20261116_090000.db"
    recent.write_bytes(b"x")
    _set_mtime(recent, _FrozenDateTime.frozen - timedelta(hours=3))

    fresh = _fresh_scheduler(monkeypatch)
    sched.start_scheduler()

    assert fresh.get_job("backup_database_catchup") is None
    assert fresh.get_job("backup_database") is not None
