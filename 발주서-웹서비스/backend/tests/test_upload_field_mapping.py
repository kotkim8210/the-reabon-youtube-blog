"""업로드 필드명 정합성 가드.

프론트 업로드 칸의 key가 api.ts의 fieldNameMap을 거쳐 백엔드 UploadFile 파라미터명과
맞지 않으면, FastAPI는 그 파일을 조용히 무시한다(에러도 안 난다).
2026-08-31 지마켓 파일이 이렇게 통째로 무시돼 발주서가 0건으로 나왔다.
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
BACKEND_MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _field_name_map() -> dict[str, str]:
    src = (FRONTEND / "api.ts").read_text(encoding="utf-8")
    block = re.search(r"const fieldNameMap[^{]*\{(.*?)\n  \};", src, re.S)
    assert block, "api.ts에서 fieldNameMap을 찾지 못했습니다"
    return dict(re.findall(r"(\w+):\s*'(\w+)'", block.group(1)))


def _upload_keys() -> dict[str, str]:
    """프론트 업로드 칸 key -> 정의된 페이지 파일명"""
    keys: dict[str, str] = {}
    for page in ("pages/ProcessPage.tsx", "pages/UnifiedProcessPage.tsx"):
        src = (FRONTEND / page).read_text(encoding="utf-8")
        for key in re.findall(r"\{\s*key:\s*'([a-z_0-9]+)'[^}]*?label:", src):
            keys.setdefault(key, page)
    return keys


def _backend_upload_params() -> set[str]:
    src = BACKEND_MAIN.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*(\w+):\s*UploadFile", src, re.M))


def test_every_upload_key_reaches_backend():
    field_map = _field_name_map()
    params = _backend_upload_params()
    # 파일이 아니라 문자열(Form)로 전송되는 key는 제외
    text_keys = {"tracking_text"}

    missing = []
    for key, page in sorted(_upload_keys().items()):
        if key in text_keys:
            continue
        sent_as = field_map.get(key, key)
        if sent_as not in params:
            missing.append(f"{key} -> '{sent_as}' ({page})")

    assert not missing, (
        "프론트 업로드 칸이 백엔드 파라미터와 연결되지 않았습니다(파일이 조용히 무시됨): "
        + ", ".join(missing)
    )


def test_gmarket_file_is_mapped():
    """게걸무 지마켓 슬롯 회귀 방지."""
    assert _field_name_map().get("gmarket") == "gmarket_file"
    assert "gmarket_file" in _backend_upload_params()
