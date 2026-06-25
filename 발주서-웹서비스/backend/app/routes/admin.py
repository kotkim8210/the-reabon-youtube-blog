"""Admin routes: user management, IP blocking, and admin-only utilities."""

import json
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from passlib.hash import bcrypt
from pydantic import BaseModel
from typing import Optional

from app.auth import require_admin
from app.db import (
    get_all_users, create_user, update_user_active,
    get_blocked_ips, add_blocked_ip, remove_blocked_ip,
)
from app.processors import temu_kolrabi_goods

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str
    password: str = "12345"
    role: str = "user"
    email: Optional[str] = None


class BlockIPRequest(BaseModel):
    ip_address: str
    user_id: Optional[int] = None
    reason: str = ""


def _make_excel_response(output_bytes: bytes, filename: str, stats: dict | None = None) -> StreamingResponse:
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Access-Control-Expose-Headers": "Content-Disposition, X-Stats",
    }
    if stats:
        headers["X-Stats"] = json.dumps(stats, ensure_ascii=True)
    return StreamingResponse(
        BytesIO(output_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/users")
async def list_users(admin: dict = Depends(require_admin)):
    users = await get_all_users()
    return {"users": users}


@router.post("/users")
async def create_new_user(req: CreateUserRequest, admin: dict = Depends(require_admin)):
    password_hash = bcrypt.hash(req.password)
    try:
        user_id = await create_user(req.username, password_hash, req.role, req.email)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 존재하는 아이디입니다.",
        )
    return {"status": "ok", "user_id": user_id}


@router.patch("/users/{user_id}/toggle")
async def toggle_user_active(user_id: int, admin: dict = Depends(require_admin)):
    from app.db import get_user_by_id
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user["role"] == "admin":
        raise HTTPException(status_code=400, detail="Cannot deactivate admin")
    new_state = not bool(user["is_active"])
    await update_user_active(user_id, new_state)
    return {"status": "ok", "is_active": new_state}


@router.get("/blocked-ips")
async def list_blocked_ips(admin: dict = Depends(require_admin)):
    ips = await get_blocked_ips()
    return {"blocked_ips": ips}


@router.post("/blocked-ips")
async def block_ip(req: BlockIPRequest, admin: dict = Depends(require_admin)):
    block_id = await add_blocked_ip(
        req.ip_address, admin["user_id"], req.user_id, req.reason,
    )
    return {"status": "ok", "id": block_id}


@router.delete("/blocked-ips/{block_id}")
async def unblock_ip(block_id: int, admin: dict = Depends(require_admin)):
    await remove_blocked_ip(block_id)
    return {"status": "ok"}


@router.post("/temu/kolrabi-goods/download")
async def download_temu_kolrabi_goods(admin: dict = Depends(require_admin)):
    output_bytes, filename, stats = temu_kolrabi_goods.generate_workbook()
    return _make_excel_response(output_bytes, filename, stats)
