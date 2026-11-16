"""업로드 본문 파싱 DoS 방어 — 2026-11-16 리뷰 2순위(db_infra_security-3).

FastAPI는 인증(verify_token)보다 본문 파싱(request.form())을 먼저 한다. 그래서 업로드 라이브러리 취약점은
로그인 없이 요청 하나로 서버(이벤트 루프)를 멈추거나 로그를 폭주시킨다.
python-multipart 0.0.6·starlette 0.35.1에선 아래 요청이 (Range 건만 빼고) 모두 그대로 통과했다
→ python-multipart 0.0.32·starlette 1.3.1(fastapi 0.133.1)로 올려 막는다(backend/requirements.txt).
"""

import asyncio
import logging
import os
import time
from importlib.metadata import version
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from packaging.version import Version

from app import db as database
from app import main

UPLOAD_URL = "/api/process/batch-tracking-merge"   # 로그인이 필요한 업로드 엔드포인트
BOUNDARY = "dosguardboundary"
FILE_PART = (
    b'Content-Disposition: form-data; name="result_files"; filename="a.xlsx"\r\n'
    b"Content-Type: application/octet-stream\r\n\r\n"
    b"data"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """임시 DB로 실제 HTTP 경로(IP 차단 미들웨어→라우터→본문 파싱)를 탄다. lifespan(스케줄러·쿠팡 조회)은 안 돌린다."""
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "dos.db"))
    monkeypatch.setattr(database, "_db", None)
    asyncio.run(database.init_db())
    test_client = TestClient(main.app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        test_client.close()
        asyncio.run(database.close_db())


def _multipart(*parts: bytes, epilogue: bytes = b"") -> tuple[bytes, dict]:
    sep = b"--" + BOUNDARY.encode()
    body = b"".join(sep + b"\r\n" + part + b"\r\n" for part in parts) + sep + b"--\r\n" + epilogue
    return body, {"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"}


class _CountingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


def test_content_type_redos_answers_fast(client):
    """CVE-2024-24762: Content-Type 매개변수 '"\\\\\\…' 하나로 정규식 역추적이 폭발했다(역슬래시 38개에 약 10초, 2개마다 약 2.6배)."""
    client.get("/api/health")   # 첫 요청 준비 시간은 재지 않는다
    evil = 'application/x-www-form-urlencoded; a="' + "\\" * 38
    started = time.perf_counter()
    res = client.post(UPLOAD_URL, content=b"", headers={"Content-Type": evil})
    elapsed = time.perf_counter() - started
    assert res.status_code < 500
    assert elapsed < 2.0, f"Content-Type 해석 {elapsed:.1f}초 — 정규식 역추적(ReDoS)"


def test_multipart_epilogue_does_not_flood_logs(client):
    """CVE-2024-53981·CVE-2026-40347: 마지막 경계 뒤 바이트마다 경고 1줄 → 5만 바이트면 경고 5만 줄(로그 폭주·CPU)."""
    counter = _CountingHandler()
    loggers = [logging.getLogger(name) for name in ("multipart", "python_multipart")]
    for lg in loggers:
        lg.addHandler(counter)
    try:
        body, headers = _multipart(FILE_PART, epilogue=b"x" * 50_000)
        res = client.post(UPLOAD_URL, content=body, headers=headers)
    finally:
        for lg in loggers:
            lg.removeHandler(counter)
    assert res.status_code < 500
    assert counter.count < 10, f"멀티파트 파서 경고 {counter.count}줄 — 쓰레기 바이트마다 로그"


def test_multipart_huge_text_field_is_cut_at_1mb(client):
    """CVE-2024-47874: 파일 아닌 칸은 크기 제한 없이 메모리에 쌓였다 → 1MB를 넘으면 인증 전에 400."""
    text_part = b'Content-Disposition: form-data; name="memo"\r\n\r\n' + b"x" * (1024 * 1024 + 1)
    body, headers = _multipart(text_part, FILE_PART)
    res = client.post(UPLOAD_URL, content=body, headers=headers)
    assert res.status_code == 400
    assert "maximum size" in res.json()["detail"]


def test_multipart_part_header_flood_is_rejected(client):
    """CVE-2026-42561: 한 칸에 헤더를 끝없이 붙여도 받아줬다 → 칸당 헤더 수 제한(400)."""
    flood = b"X-Pad: v\r\n" * 64
    part = b'Content-Disposition: form-data; name="memo"\r\n' + flood + b"\r\nhello"
    body, headers = _multipart(part, FILE_PART)
    res = client.post(UPLOAD_URL, content=body, headers=headers)
    assert res.status_code == 400


@pytest.mark.parametrize(
    "body",
    ["&".join(f"f{i}=v" for i in range(1500)), "memo=" + "x" * (1024 * 1024 + 1)],
    ids=["fields-1500", "field-over-1mb"],
)
def test_urlencoded_form_limits_apply(client, body):
    """CVE-2026-54283: x-www-form-urlencoded는 칸 수·크기 제한이 아예 없었다(이벤트 루프 수 초 정지·메모리) → 400."""
    res = client.post(
        UPLOAD_URL, content=body.encode(), headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 400


def _largest_asset() -> Path:
    assets = main.FRONTEND_DIR / "assets"
    files = sorted((p for p in assets.glob("*") if p.is_file()), key=lambda p: p.stat().st_size) if assets.is_dir() else []
    if not files:
        pytest.skip("backend/static/assets 없음(프론트 빌드 전)")
    return files[-1]


def test_static_many_ranges_answer_fast(client):
    """CVE-2025-62727: starlette 0.39~0.49.0의 Range 병합이 O(n²) → 정적 파일 요청 하나로 수 초 정지.

    0.35.1은 Range를 몰라 안전했지만 0.40.0으로만 올리면 새로 생기는 구멍이다(1.3.1로 고정한 이유).
    """
    asset = _largest_asset()
    count = min(asset.stat().st_size // 2, 20_000)
    ranges = "bytes=" + ",".join(f"{2 * i}-{2 * i}" for i in range(count))
    client.get("/api/health")
    started = time.perf_counter()
    res = client.head(f"/assets/{asset.name}", headers={"Range": ranges})
    elapsed = time.perf_counter() - started
    assert res.status_code in (200, 206)
    assert elapsed < 2.0, f"Range {count}개 처리 {elapsed:.1f}초 — O(n²) 병합"


@pytest.mark.skipif(os.name != "nt", reason="UNC 경로는 Windows 전용(운영 서버 = Windows)")
def test_static_files_never_resolve_unc_paths(client, monkeypatch):
    """CVE-2026-48818: /assets/\\\\호스트\\공유 를 realpath가 풀면서 외부 SMB로 접속했다(Windows 계정 NTLM 해시 유출).

    네트워크에 닿지 않게 realpath를 가로채 UNC 경로가 들어오는지만 본다.
    """
    real_realpath = os.path.realpath
    touched: list[str] = []

    def guarded_realpath(path, *args, **kwargs):
        text = os.fsdecode(path)
        if text.startswith(("\\\\", "//")):
            touched.append(text)
            return text
        return real_realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", guarded_realpath)
    res = client.get("/assets/%5C%5Cunc-guard.invalid%5Cshare%5Cx.js")
    assert touched == []
    assert res.status_code == 404


def test_upload_stack_versions_have_no_known_cves():
    """재현이 어려운 나머지 CVE(파일 디스크 전환 시 루프 정지 CVE-2025-54121, 쿼리스트링 O(n²) CVE-2026-53539,
    Host 헤더로 request.url 오염 CVE-2026-48710 등)까지 막힌 버전인지. 실패하면 venv를 requirements.txt 핀으로 맞출 것."""
    assert Version(version("python-multipart")) >= Version("0.0.32")   # 0.0.31은 경계 처리 버그 → 0.0.32
    assert Version(version("starlette")) >= Version("1.3.1")
