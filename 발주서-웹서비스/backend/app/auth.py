from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.hash import bcrypt
from pydantic import BaseModel

import httpx

from app.config import (
    ALGORITHM, ACCESS_TOKEN_EXPIRE_HOURS, SECRET_KEY, AUTH_DISABLED,
    DISABLE_SIGNUP, ADMIN_ONLY, KAKAO_CLIENT_ID, GOOGLE_CLIENT_ID,
)
from app.db import (
    get_setting, set_setting,
    get_user_by_username, get_user_by_id, get_user_by_email,
    get_user_by_kakao_id, get_user_by_google_id,
    update_user_password, create_user, upsert_subscription,
    upsert_oauth_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=not AUTH_DISABLED)

# 로그인 화면은 detail을 그대로 보여준다
ADMIN_ONLY_DETAIL = "관리자 계정만 사용할 수 있습니다"
SIGNUP_BLOCKED_DETAIL = "신규 가입이 막혀 있습니다"


def _ensure_admin_only(user: dict) -> None:
    """ADMIN_ONLY(기본 켜짐)면 관리자(role=admin)가 아닌 계정은 로그인·API 모두 403.

    공개 주소라 role=user 계정이 생기면 /api/process/*(verify_token만 검사)로 고객 개인정보 엑셀 다운로드·
    발주 이력 오염·가짜 송장 등록·거래처 메일 발송까지 할 수 있었다(2026-11-16 리뷰).
    """
    if ADMIN_ONLY and user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_ONLY_DETAIL)


class LoginRequest(BaseModel):
    username: Optional[str] = None
    password: str


class SignupRequest(BaseModel):
    username: str
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserStatus(BaseModel):
    authenticated: bool
    user_id: Optional[int] = None
    username: Optional[str] = None
    role: Optional[str] = None
    expires_at: Optional[str] = None


class AuthConfig(BaseModel):
    auth_disabled: bool


def create_access_token(user_id: int, role: str, username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "username": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    if AUTH_DISABLED:
        return {"user_id": 1, "role": "admin", "username": "admin"}

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    sub = payload.get("sub")
    # Backward compat: old tokens have sub="team_user"
    if sub == "team_user":
        return {"user_id": 1, "role": "admin", "username": "admin"}

    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await get_user_by_id(user_id)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account deactivated")
    _ensure_admin_only(user)   # 토큰이 아니라 DB의 role로 판단 — 예전에 받은 role=user 토큰도 막힌다

    return {
        "user_id": user["id"],
        "role": user["role"],
        "username": user["username"],
    }


async def require_admin(current_user: dict = Depends(verify_token)) -> dict:
    if current_user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return current_user


async def require_pro(current_user: dict = Depends(verify_token)) -> dict:
    """Admin always passes. Non-admin must have active Pro subscription."""
    from app.config import DISABLE_QUOTA
    if DISABLE_QUOTA or current_user["role"] == "admin":
        return current_user
    from app.db import get_subscription
    sub = await get_subscription(current_user["user_id"])
    if not sub or sub["plan_code"] != "pro" or sub["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Pro 플랜 전용 기능입니다. 업그레이드하세요.",
        )
    return current_user


class OAuthConfig(BaseModel):
    kakao_client_id: str
    google_client_id: str


@router.get("/config", response_model=AuthConfig)
async def get_auth_config():
    return AuthConfig(auth_disabled=AUTH_DISABLED)


@router.get("/oauth-config", response_model=OAuthConfig)
async def get_oauth_config():
    """Public endpoint: returns OAuth client IDs for frontend SDK initialization."""
    return OAuthConfig(
        kakao_client_id=KAKAO_CLIENT_ID,
        google_client_id=GOOGLE_CLIENT_ID,
    )


@router.post("/signup", response_model=TokenResponse)
async def signup(request: SignupRequest):
    if DISABLE_SIGNUP:
        raise HTTPException(status_code=403, detail="회원가입이 비활성화되어 있습니다. 관리자에게 문의하세요.")
    if ADMIN_ONLY:   # 새 계정은 role=user — 만들어도 아무 API도 못 쓰니 만들지 않는다
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_ONLY_DETAIL)
    username = (request.username or "").strip()
    email = (request.email or "").strip().lower()
    password = request.password or ""

    if len(username) < 3 or len(username) > 32:
        raise HTTPException(status_code=400, detail="아이디는 3~32자여야 합니다.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="올바른 이메일을 입력하세요.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    if await get_user_by_username(username):
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")
    if await get_user_by_email(email):
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    password_hash = bcrypt.hash(password)
    user_id = await create_user(username, password_hash, role="user", email=email)
    await upsert_subscription(user_id, plan_code="free", status="active")

    token = create_access_token(user_id, "user", username)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    username = request.username
    password = request.password

    # Backward compat: no username → try admin login with team password
    if not username:
        stored_password = await get_setting("team_password")
        if stored_password and password == stored_password:
            user = await get_user_by_username("admin")
            if user:
                _ensure_admin_only(user)
                token = create_access_token(user["id"], user["role"], user["username"])
                return TokenResponse(access_token=token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비밀번호가 올바르지 않습니다.",
        )

    user = await get_user_by_username(username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다. 관리자에게 문의하세요.",
        )

    if not bcrypt.verify(password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )
    # 비밀번호 확인 뒤에 검사 — 비밀번호를 모르는 사람에게 계정 종류를 알려주지 않는다
    _ensure_admin_only(user)

    token = create_access_token(user["id"], user["role"], user["username"])
    return TokenResponse(access_token=token)


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(verify_token),
):
    user = await get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not bcrypt.verify(request.current_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="현재 비밀번호가 올바르지 않습니다.",
        )

    if len(request.new_password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="새 비밀번호는 4자 이상이어야 합니다.",
        )

    new_hash = bcrypt.hash(request.new_password)
    await update_user_password(current_user["user_id"], new_hash)

    # If admin, also update team_password in app_settings for backward compat
    if current_user["role"] == "admin":
        await set_setting("team_password", request.new_password)

    return {"status": "ok", "message": "비밀번호가 변경되었습니다."}


# ---------------------------------------------------------------------------
# Social OAuth endpoints  (client-side token exchange)
# ---------------------------------------------------------------------------

class KakaoTokenRequest(BaseModel):
    access_token: str


class GoogleTokenRequest(BaseModel):
    credential: str  # Google ID Token


def _is_unverified_google_email(info: dict) -> bool:
    verified = info.get("email_verified")
    if verified is None:
        return False
    if isinstance(verified, bool):
        return not verified
    return str(verified).lower() not in {"true", "1", "yes"}


async def _check_social_login(provider: str, provider_id: str, email: Optional[str]) -> None:
    """소셜 로그인 — 계정을 만들거나 연결(upsert_oauth_user)하기 전에 막을 사람은 막는다.

    종전엔 처음 보는 카카오·구글 계정이면 DISABLE_SIGNUP과 무관하게 새 계정(role=user)을 만들어 줘서
    외부인이 자기 카카오 개발자 앱 토큰만으로 발주 API를 쓸 수 있었다(2026-11-16 리뷰).
    찾는 순서는 upsert_oauth_user와 같다(제공자 ID → 이메일).
    """
    find_by_provider = get_user_by_kakao_id if provider == "kakao" else get_user_by_google_id
    existing = await find_by_provider(provider_id)
    if existing is None and email:
        existing = await get_user_by_email(email)
    if existing is None:
        if DISABLE_SIGNUP:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SIGNUP_BLOCKED_DETAIL)
        existing = {"role": "user"}   # 새로 만들 계정은 항상 role=user
    _ensure_admin_only(existing)


@router.post("/kakao/token", response_model=TokenResponse)
async def kakao_login(req: KakaoTokenRequest):
    """Exchange a Kakao access_token (from JS SDK) for an app JWT."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {req.access_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="카카오 토큰 검증 실패")

    data = resp.json()
    kakao_id = str(data["id"])
    kakao_account = data.get("kakao_account", {})
    profile = kakao_account.get("profile", {})
    email = kakao_account.get("email")
    nickname = profile.get("nickname") or profile.get("name")
    avatar_url = profile.get("thumbnail_image_url") or profile.get("profile_image_url")

    await _check_social_login("kakao", kakao_id, email)
    user = await upsert_oauth_user("kakao", kakao_id, email, nickname, avatar_url)
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")
    _ensure_admin_only(user)

    # Ensure subscription row exists
    await upsert_subscription(user["id"], plan_code="free", status="active")

    token = create_access_token(user["id"], user["role"], user["username"])
    return TokenResponse(access_token=token)


@router.post("/google/token", response_model=TokenResponse)
async def google_login(req: GoogleTokenRequest):
    """Exchange a Google access_token (from useGoogleLogin) for an app JWT.

    The credential field accepts either:
    - An OAuth 2.0 access_token → calls /userinfo
    - An ID Token (credential from One Tap) → calls tokeninfo
    We detect by attempting userinfo first.
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="구글 로그인이 아직 설정되지 않았습니다.")

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Try as access_token (useGoogleLogin flow)
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {req.credential}"},
        )
        if resp.status_code == 200:
            if GOOGLE_CLIENT_ID:
                token_info_resp = await client.get(
                    "https://oauth2.googleapis.com/tokeninfo",
                    params={"access_token": req.credential},
                )
                if token_info_resp.status_code != 200:
                    raise HTTPException(status_code=401, detail="구글 토큰 검증 실패")
                token_info = token_info_resp.json()
                if token_info.get("aud") != GOOGLE_CLIENT_ID:
                    raise HTTPException(status_code=401, detail="구글 클라이언트 ID 불일치")
            info = resp.json()
            google_id = info.get("sub")
        else:
            # Fall back: try as ID Token (One Tap / credentialResponse.credential)
            resp2 = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": req.credential},
            )
            if resp2.status_code != 200:
                raise HTTPException(status_code=401, detail="구글 토큰 검증 실패")
            info = resp2.json()
            if GOOGLE_CLIENT_ID and info.get("aud") != GOOGLE_CLIENT_ID:
                raise HTTPException(status_code=401, detail="구글 클라이언트 ID 불일치")
            google_id = info.get("sub")

    if not google_id:
        raise HTTPException(status_code=401, detail="구글 사용자 정보 없음")
    if _is_unverified_google_email(info):
        raise HTTPException(status_code=401, detail="인증되지 않은 구글 이메일입니다.")

    email = info.get("email")
    name = info.get("name") or info.get("given_name")
    avatar_url = info.get("picture")

    await _check_social_login("google", google_id, email)
    user = await upsert_oauth_user("google", google_id, email, name, avatar_url)
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")
    _ensure_admin_only(user)

    await upsert_subscription(user["id"], plan_code="free", status="active")

    token = create_access_token(user["id"], user["role"], user["username"])
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserStatus)
async def me(payload: dict = Depends(verify_token)):
    return UserStatus(
        authenticated=True,
        user_id=payload.get("user_id"),
        username=payload.get("username"),
        role=payload.get("role"),
    )
