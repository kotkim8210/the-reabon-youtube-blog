"""공개 주소 가입 차단 + 관리자 전용 + 홈 '송장번호 입력' 카드 X-Stats — 2026-11-16 리뷰 2순위.

1) 카카오·구글 로그인이 DISABLE_SIGNUP을 보지 않고 처음 보는 사람에게 계정(role=user)을 만들어 줬다.
   외부인이 자기 카카오 앱 토큰으로 JWT를 받아 /api/process/*(verify_token만 검사)로 고객 개인정보 엑셀을 받고
   발주 이력 오염·가짜 송장 등록·거래처 메일 발송까지 할 수 있었다.
   → DISABLE_SIGNUP 기본 켜짐(신규 계정 403), ADMIN_ONLY 기본 켜짐(관리자 아닌 계정은 로그인·API 모두 403).
2) /api/automation/tracking/unified·/api/tenant/* 가 X-Stats를 ensure_ascii=False로 만들어 한글 stats면
   latin-1 헤더 오류 → 홈 '송장번호 입력' 카드가 어떤 파일이든 실패했다. → ASCII(JSON 이스케이프)로.

TestClient는 with 없이 써서 lifespan(스케줄러·쿠팡 초기 조회)을 돌리지 않고, DB는 tmp_path 임시 파일이다.
"""

import asyncio
import importlib.util
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from passlib.hash import bcrypt

from app import auth, db, main
from app.processors import generic_order
from app.routes import automation, tenant

ADMIN_ONLY_DETAIL = "관리자 계정만 사용할 수 있습니다"
SIGNUP_BLOCKED_DETAIL = "신규 가입이 막혀 있습니다"

KAKAO_STRANGER = {"id": 990001, "kakao_account": {"email": "stranger@example.com", "profile": {"nickname": "외부인"}}}
GOOGLE_STRANGER = {"sub": "g-990001", "email": "stranger@example.com", "email_verified": True, "name": "외부인"}

KOREAN_STATS = {"product": "콜라비", "matched": 3, "needs_check": ["송장 없음: 홍길동"]}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """임시 DB + TestClient + 관리자(admin)·일반(member, role=user) 계정."""
    db_path = tmp_path / "auth.db"
    monkeypatch.setattr(db, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(db, "_db", None)
    monkeypatch.setattr(auth, "AUTH_DISABLED", False)
    monkeypatch.setattr(auth, "DISABLE_SIGNUP", True)
    monkeypatch.setattr(auth, "ADMIN_ONLY", True)

    async def setup():
        await db.init_db()                                   # 빈 DB → admin 계정 자동 생성
        admin = await db.get_user_by_username("admin")
        await db.update_user_password(admin["id"], bcrypt.hash("admin-pw"))
        await db.set_setting("team_password", "team-pw")
        member_id = await db.create_user(
            "member", bcrypt.hash("member-pw"), role="user", email="member@example.com",
        )
        await db.close_db()                                  # 요청은 TestClient 쪽 이벤트 루프에서 새로 연다
        return admin["id"], member_id

    admin_id, member_id = asyncio.run(setup())
    yield SimpleNamespace(
        client=TestClient(main.app),
        db_path=str(db_path),
        admin_id=admin_id,
        member_id=member_id,
        admin_headers=_bearer(auth.create_access_token(admin_id, "admin", "admin")),
        member_headers=_bearer(auth.create_access_token(member_id, "user", "member")),
    )
    asyncio.run(db.close_db())


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _users(env) -> list[dict]:
    with closing(sqlite3.connect(env.db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT id, username, role, kakao_id, google_id FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _link_kakao(env, user_id: int, kakao_id: str) -> None:
    with closing(sqlite3.connect(env.db_path)) as con:
        con.execute("UPDATE users SET kakao_id = ? WHERE id = ?", (kakao_id, user_id))
        con.commit()


class _Resp:
    def __init__(self, status_code: int, data: dict):
        self.status_code = status_code
        self._data = data

    def json(self) -> dict:
        return self._data


def _fake_oauth(monkeypatch, kakao: dict | None = None, google: dict | None = None) -> list[str]:
    """auth 모듈이 쓰는 httpx만 가짜로 바꾼다 — 카카오·구글 실제 호출 없음."""
    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append(url)
            if "kapi.kakao.com" in url and kakao is not None:
                return _Resp(200, kakao)
            if "userinfo" in url and google is not None:
                return _Resp(200, google)
            if "tokeninfo" in url:
                return _Resp(200, {"aud": "test-google-client"})
            raise AssertionError(f"예상 밖 외부 호출: {url}")

    monkeypatch.setattr(auth, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient))
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "test-google-client")
    return calls


# ── 관리자 전용 API ────────────────────────────────────────────────────────

def test_member_token_is_refused_on_order_apis(env):
    """리뷰 재현: role=user 토큰으로 발주·송장 API를 쓰던 것 → 403."""
    for method, path in [
        ("post", "/api/process/tracking-input"),
        ("get", "/api/automation/batches"),
        ("get", "/api/auth/me"),
    ]:
        res = getattr(env.client, method)(path, headers=env.member_headers)
        assert res.status_code == 403, path
        assert res.json()["detail"] == ADMIN_ONLY_DETAIL, path


def test_admin_token_passes_auth(env):
    res = env.client.get("/api/automation/batches", headers=env.admin_headers)
    assert res.status_code == 200 and res.json() == {"batches": []}
    # 인증을 통과해 '파일 없음' 입력 오류(422)까지 간다 — 프로세서는 돌지 않는다
    assert env.client.post("/api/process/tracking-input", headers=env.admin_headers).status_code == 422
    me = env.client.get("/api/auth/me", headers=env.admin_headers).json()
    assert me["role"] == "admin" and me["user_id"] == env.admin_id


def test_admin_only_off_keeps_member_access(env, monkeypatch):
    monkeypatch.setattr(auth, "ADMIN_ONLY", False)
    assert env.client.get("/api/automation/batches", headers=env.member_headers).status_code == 200


def test_legacy_team_user_token_and_auth_disabled_stay_admin(env, monkeypatch):
    legacy = jwt.encode(
        {"sub": "team_user", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        auth.SECRET_KEY, algorithm=auth.ALGORITHM,
    )
    res = env.client.get("/api/auth/me", headers=_bearer(legacy))
    assert res.status_code == 200 and res.json()["role"] == "admin"

    monkeypatch.setattr(auth, "AUTH_DISABLED", True)
    assert asyncio.run(auth.verify_token(None)) == {"user_id": 1, "role": "admin", "username": "admin"}


# ── 로그인·가입 ────────────────────────────────────────────────────────────

def test_password_login_refuses_member_but_not_admin(env):
    res = env.client.post("/api/auth/login", json={"username": "member", "password": "member-pw"})
    assert res.status_code == 403 and res.json()["detail"] == ADMIN_ONLY_DETAIL
    # 비밀번호가 틀리면 예전처럼 401 — 비밀번호를 모르는 사람에게 계정 종류를 알려주지 않는다
    wrong = env.client.post("/api/auth/login", json={"username": "member", "password": "wrong-pw"})
    assert wrong.status_code == 401
    ok = env.client.post("/api/auth/login", json={"username": "admin", "password": "admin-pw"})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_team_password_login_still_works(env):
    res = env.client.post("/api/auth/login", json={"password": "team-pw"})
    assert res.status_code == 200
    me = env.client.get("/api/auth/me", headers=_bearer(res.json()["access_token"]))
    assert me.status_code == 200 and me.json()["role"] == "admin"


def test_signup_blocked_and_no_account_created(env, monkeypatch):
    body = {"username": "stranger", "email": "stranger@example.com", "password": "stranger-pw"}
    assert env.client.post("/api/auth/signup", json=body).status_code == 403      # DISABLE_SIGNUP 기본 켜짐
    monkeypatch.setattr(auth, "DISABLE_SIGNUP", False)
    res = env.client.post("/api/auth/signup", json=body)    # 가입을 켜도 새 계정(role=user)은 ADMIN_ONLY면 못 쓴다
    assert res.status_code == 403 and res.json()["detail"] == ADMIN_ONLY_DETAIL
    assert [u["username"] for u in _users(env)] == ["admin", "member"]


def test_kakao_stranger_is_blocked_without_creating_account(env, monkeypatch):
    """리뷰 재현: 외부인 카카오 토큰 → 종전엔 계정 생성 + role=user JWT."""
    calls = _fake_oauth(monkeypatch, kakao=KAKAO_STRANGER)
    res = env.client.post("/api/auth/kakao/token", json={"access_token": "stranger-kakao-token"})
    assert res.status_code == 403 and res.json()["detail"] == SIGNUP_BLOCKED_DETAIL
    assert calls == ["https://kapi.kakao.com/v2/user/me"]
    assert [u["username"] for u in _users(env)] == ["admin", "member"]


def test_google_stranger_is_blocked_without_creating_account(env, monkeypatch):
    _fake_oauth(monkeypatch, google=GOOGLE_STRANGER)
    res = env.client.post("/api/auth/google/token", json={"credential": "stranger-google-token"})
    assert res.status_code == 403 and res.json()["detail"] == SIGNUP_BLOCKED_DETAIL
    assert [u["username"] for u in _users(env)] == ["admin", "member"]


def test_kakao_member_matched_by_email_is_refused_and_not_linked(env, monkeypatch):
    _fake_oauth(monkeypatch, kakao={"id": 990002, "kakao_account": {"email": "member@example.com", "profile": {}}})
    res = env.client.post("/api/auth/kakao/token", json={"access_token": "member-kakao-token"})
    assert res.status_code == 403 and res.json()["detail"] == ADMIN_ONLY_DETAIL
    member = next(u for u in _users(env) if u["username"] == "member")
    assert member["kakao_id"] is None              # 거부하면서 카카오 연결(upsert)도 하지 않는다


def test_kakao_linked_admin_still_logs_in(env, monkeypatch):
    _link_kakao(env, env.admin_id, "990003")
    _fake_oauth(monkeypatch, kakao={"id": 990003, "kakao_account": {"profile": {"nickname": "사장님"}}})
    res = env.client.post("/api/auth/kakao/token", json={"access_token": "admin-kakao-token"})
    assert res.status_code == 200
    me = env.client.get("/api/auth/me", headers=_bearer(res.json()["access_token"]))
    assert me.json()["role"] == "admin" and me.json()["user_id"] == env.admin_id


def test_flags_off_keep_old_social_signup(env, monkeypatch):
    monkeypatch.setattr(auth, "DISABLE_SIGNUP", False)
    monkeypatch.setattr(auth, "ADMIN_ONLY", False)
    _fake_oauth(monkeypatch, kakao=KAKAO_STRANGER)
    res = env.client.post("/api/auth/kakao/token", json={"access_token": "stranger-kakao-token"})
    assert res.status_code == 200
    assert any(u["kakao_id"] == "990001" and u["role"] == "user" for u in _users(env))


def _load_config(monkeypatch, **env_values):
    """app/config.py를 별도 모듈로 읽어 기본값을 본다 — 전역 app.config는 건드리지 않는다."""
    for key in ("DISABLE_SIGNUP", "ADMIN_ONLY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env_values.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("config_probe", Path(auth.__file__).with_name("config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_defaults_block_signup_and_admin_only(monkeypatch):
    cfg = _load_config(monkeypatch)
    assert cfg.DISABLE_SIGNUP is True and cfg.ADMIN_ONLY is True
    cfg = _load_config(monkeypatch, DISABLE_SIGNUP="false", ADMIN_ONLY="false")    # .env로 끌 수 있다
    assert cfg.DISABLE_SIGNUP is False and cfg.ADMIN_ONLY is False


# ── X-Stats 헤더(한글 stats) ───────────────────────────────────────────────

def _assert_ascii_stats(res) -> None:
    header = res.headers["x-stats"]
    assert header.isascii()                                  # 한글은 \uXXXX — latin-1 헤더 인코딩 오류 없음
    assert json.loads(header) == KOREAN_STATS


def _tracking_files(*reply_names: str) -> list:
    """화면과 같은 모양 — 회신 파일마다 reply_files 칸 하나씩 + DeliveryList."""
    names = reply_names or ("회신.xlsx",)
    return [("reply_files", (name, b"reply", XLSX)) for name in names] + [
        ("delivery_file", ("DeliveryList.xlsx", b"delivery", XLSX)),
    ]


def test_home_tracking_card_with_korean_stats(env, monkeypatch):
    """리뷰 재현: 홈 '송장번호 입력' 카드(/api/automation/tracking/unified).

    한글 stats면 latin-1 헤더 오류로 500이었고, 그 전에 reply_files(list | None)를 FastAPI 0.109가 목록으로
    못 읽어 파일을 올리면 422부터 났다.
    """
    received: list[str] = []

    def fake_process(replies, delivery):
        received.extend(name for name, _bytes in replies)
        return b"xlsx", "통합송장.xlsx", KOREAN_STATS

    monkeypatch.setattr(automation.unified_tracking, "process", fake_process)
    res = env.client.post(
        "/api/automation/tracking/unified", headers=env.admin_headers,
        files=_tracking_files("해달회신.xlsx", "제주다팜회신.xlsx"),
    )
    assert res.status_code == 200, res.text
    _assert_ascii_stats(res)
    assert received == ["해달회신.xlsx", "제주다팜회신.xlsx"]       # 여러 파일이 전부 들어온다

    only_delivery = [("delivery_file", ("DeliveryList.xlsx", b"delivery", XLSX))]
    res = env.client.post("/api/automation/tracking/unified", headers=env.admin_headers, files=only_delivery)
    assert res.status_code == 400 and "1개 이상" in res.json()["detail"]   # 422가 아니라 화면용 안내


def test_danharu_batch_response_with_korean_stats():
    res = automation._batch_excel_response(b"xlsx", "단하루_발주.xlsx", KOREAN_STATS, 7, "local_only")
    _assert_ascii_stats(res)
    assert res.headers["x-batch-id"] == "7"


def test_tenant_tracking_and_process_with_korean_stats(env, monkeypatch):
    monkeypatch.setattr(automation.unified_tracking, "process", lambda replies, delivery: (b"xlsx", "송장.xlsx", KOREAN_STATS))
    res = env.client.post("/api/tenant/tracking", headers=env.admin_headers, files=_tracking_files())
    assert res.status_code == 200, res.text
    _assert_ascii_stats(res)

    async def fake_generic(user_id, delivery_bytes):
        return [(b"xlsx", "발주서.xlsx", KOREAN_STATS)]

    async def no_quota(*_args, **_kwargs):
        return None

    monkeypatch.setattr(generic_order, "process_generic_order", fake_generic)
    monkeypatch.setattr(tenant, "check_order_quota", no_quota)
    monkeypatch.setattr(tenant, "record_order_usage", no_quota)
    res = env.client.post(
        "/api/tenant/process", headers=env.admin_headers,
        files=[("delivery_file", ("DeliveryList.xlsx", b"delivery", XLSX))],
    )
    assert res.status_code == 200, res.text
    _assert_ascii_stats(res)
