"""웹 스택 업그레이드 스모크 — 2026-11-16 리뷰 2순위(db_infra_security-3).

fastapi 0.109.0→0.133.1, starlette 0.35.1→1.3.1, python-multipart 0.0.6→0.0.32.
기존 테스트는 엔드포인트 함수를 직접 불러 HTTP 계층(미들웨어·폼 파싱·응답 헤더·정적 파일)을 안 탄다.
여기선 TestClient로 실제 요청 경로를 탄다. 임시 DB, 외부 호출 없음. lifespan은 스케줄러·쿠팡 조회를
가짜로 바꾼 테스트 1개에서만 돌린다.
"""

import asyncio
import json
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app import config, main, rules_engine
from app import db as database
from app.auth import verify_token

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ADMIN = {"user_id": 1, "role": "admin", "username": "admin"}
WINNERS_HEADER = "경품명,별명,개인 식별 정보 확인,이름,연락처,주소,주문 아이디,구매 금액,환불/취소 금액,환불/날짜/시간"
ROW_CHESTNUT = "햇밤1kg,별명1,2026/11/15 21:01,밤당첨,010-0000-0001,부산광역시 테스트로 1,7103820345139,7700,0,"
ROW_BUSA = "부사 사과2kg(소과),별명2,2026/11/15 21:02,부사당첨,010-0000-0002,대구광역시 테스트로 2,21103842199632,34400,0,"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "smoke.db"))
    monkeypatch.setattr(database, "_db", None)
    asyncio.run(database.init_db())
    test_client = TestClient(main.app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        test_client.close()
        asyncio.run(database.close_db())


@pytest.fixture
def authed(client, monkeypatch):
    """로그인은 의존성 override로 통과(토큰 발급·DB 사용자 조회 없이)."""
    monkeypatch.setitem(main.app.dependency_overrides, verify_token, lambda: dict(ADMIN))
    return client


def _xlsx(rows: list[list[str]]) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _issued_count(section: str) -> int:
    db = await database.get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM issued_order_items WHERE section = ?", (section,))
    row = await cursor.fetchone()
    return int(row[0])


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_login_failure_keeps_detail_format(client):
    res = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert res.status_code == 401
    assert res.json() == {"detail": "아이디 또는 비밀번호가 올바르지 않습니다."}


def test_login_success_then_me_with_bearer_token(client):
    """response_model(TokenResponse·UserStatus) 직렬화와 HTTPBearer→verify_token(DB 조회) 실제 경로."""
    res = client.post("/api/auth/login", json={"username": "admin", "password": config.TEAM_PASSWORD})
    assert res.status_code == 200
    token = res.json()
    assert token["token_type"] == "bearer" and token["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token['access_token']}"})
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert (me.json()["username"], me.json()["role"]) == ("admin", "admin")


def test_lifespan_startup_and_shutdown_run(tmp_path, monkeypatch):
    """starlette 1.0에서 on_event가 없어졌다 — 앱은 lifespan이라 시작(init_db·스케줄러)·종료(close_db)가 그대로 돈다.
    스케줄러·쿠팡 조회·규칙 캐시는 가짜로 바꿔 외부 호출·전역 상태 변경이 없다."""
    calls: list[str] = []

    async def fake_refresh():
        calls.append("refresh")

    async def fake_rules():
        calls.append("rules")
        return {}

    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "lifespan.db"))
    monkeypatch.setattr(database, "_db", None)
    monkeypatch.setattr(main, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(main, "stop_scheduler", lambda: calls.append("stop"))
    monkeypatch.setattr(main, "refresh_products", fake_refresh)
    monkeypatch.setattr(main, "refresh_orders", fake_refresh)
    monkeypatch.setattr(rules_engine, "refresh_rules", fake_rules)

    with TestClient(main.app) as lifespan_client:
        assert lifespan_client.get("/api/health").json() == {"status": "ok"}
        assert calls == ["rules", "start", "refresh", "refresh"]
    assert calls[-1] == "stop"
    assert database._db is None                       # 종료 때 close_db
    assert (tmp_path / "lifespan.db").exists()        # 시작 때 init_db


def test_upload_without_token_is_401(client):
    """fastapi 0.122부터 토큰 없는 요청은 403이 아니라 401(WWW-Authenticate: Bearer). 프론트(api.ts)는 401이면 로그인 화면으로."""
    res = client.post("/api/process/batch-tracking-merge", files={"result_files": ("a.xlsx", b"x", XLSX)})
    assert res.status_code == 401
    assert res.json() == {"detail": "Not authenticated"}
    assert res.headers.get("www-authenticate") == "Bearer"


def test_event_winner_upload_returns_zip_with_ascii_stats(authed):
    csv_bytes = ("\n".join((WINNERS_HEADER, ROW_CHESTNUT, ROW_BUSA)) + "\n").encode("utf-8-sig")
    res = authed.post(
        "/api/process/event-winner-order",
        files={"winners_file": ("당첨자명단.csv", csv_bytes, "text/csv")},
        data={"exclude_issued": "true"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert res.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert "X-Stats" in res.headers["access-control-expose-headers"]
    stats_header = res.headers["x-stats"]
    assert stats_header.isascii()                     # 한글은 \uXXXX — 헤더 인코딩 오류 없음
    stats = json.loads(stats_header)
    assert stats["files"] == 2 and stats["winners"] == 2
    with zipfile.ZipFile(BytesIO(res.content)) as zf:
        assert len(zf.namelist()) == 2
    # 요청마다 이벤트 루프가 달라도 같은 DB 연결로 발주 이력이 기록돼야 재업로드 때 제외된다
    assert asyncio.run(_issued_count("fruit_event")) == 2


def test_batch_merge_accepts_several_files_and_streams_xlsx(authed):
    head = ["주문번호", "받는분", "운송장번호"]
    first = _xlsx([head, ["1", "가", "111"], ["2", "나", "222"]])
    second = _xlsx([head, ["3", "다", "333"]])
    res = authed.post(
        "/api/process/batch-tracking-merge",
        files=[
            ("result_files", ("송장입력_A.xlsx", first, XLSX)),
            ("result_files", ("송장입력_B.xlsx", second, XLSX)),
        ],
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == XLSX
    stats = json.loads(res.headers["x-stats"])
    assert stats == {"source_files": 2, "merged_rows": 3, "sources": ["송장입력_A.xlsx", "송장입력_B.xlsx"]}
    ws = load_workbook(BytesIO(res.content)).active
    assert [c.value for c in ws["C"]] == ["운송장번호", "111", "222", "333"]


def test_static_assets_and_spa_fallback(client):
    css = next(iter(sorted((main.FRONTEND_DIR / "assets").glob("*.css"))), None)
    if css is None:
        pytest.skip("backend/static/assets 없음(프론트 빌드 전)")
    res = client.get(f"/assets/{css.name}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/css")
    assert res.content == css.read_bytes()

    index = (main.FRONTEND_DIR / "index.html").read_bytes()
    for path in ("/", "/orders/kolrabi"):
        page = client.get(path)
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert page.content == index

    missing = client.get("/api/no-such-endpoint")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}
