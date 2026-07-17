"""규칙 엔진 관리 API (Phase 1-A).

발주처(rule_suppliers)·상품 매칭 규칙(product_rules) CRUD + 해석 미리보기.
변이 후에는 항상 인메모리 캐시를 갱신한다. 관리자 전용(운영 규칙이므로).
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app import db
from app import rules_engine
from app.auth import require_admin

router = APIRouter(prefix="/api/rules", tags=["rules"])


class SupplierInput(BaseModel):
    key: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9\-]+$")
    name: str = Field(min_length=1, max_length=100)
    courier: str = "롯데택배"
    order_cutoff: str = "10:00"
    delivery_method: str = "download"
    active: bool = True


class ProductRuleInput(BaseModel):
    supplier_key: str
    label: str = Field(min_length=1, max_length=100)
    priority: int = 100
    name_keywords: list[str] = []
    exclude_keywords: list[str] = []
    grades: list[str] = []
    kg_allow: list[str] = []
    pair_map: dict[str, str] = {}
    extra_map: dict[str, str] = {}
    output_template: str = Field(min_length=1)
    require_grade: bool = False
    require_kg: bool = False
    active: bool = True
    notes: str = ""


class PreviewInput(BaseModel):
    supplier_key: str
    product_name: str = ""
    option_text: str = ""


@router.get("/status")
async def rules_status(_admin: dict = Depends(require_admin)):
    return rules_engine.get_status()


@router.post("/refresh")
async def rules_refresh(_admin: dict = Depends(require_admin)):
    return await rules_engine.refresh_rules()


@router.get("/suppliers")
async def get_suppliers(_admin: dict = Depends(require_admin)):
    return {"suppliers": await db.list_rule_suppliers()}


@router.post("/suppliers")
async def save_supplier(data: SupplierInput, _admin: dict = Depends(require_admin)):
    await db.upsert_rule_supplier(data.model_dump())
    await rules_engine.refresh_rules()
    return {"status": "ok", "key": data.key}


@router.delete("/suppliers/{key}")
async def remove_supplier(key: str, _admin: dict = Depends(require_admin)):
    rules = await db.list_product_rules(supplier_key=key)
    if rules:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"이 발주처에 규칙 {len(rules)}건이 있습니다. 규칙을 먼저 삭제하거나 이관하세요.",
        )
    await db.delete_rule_supplier(key)
    await rules_engine.refresh_rules()
    return {"status": "ok"}


@router.get("/products")
async def get_product_rules(supplier: str | None = None, _admin: dict = Depends(require_admin)):
    return {"rules": await db.list_product_rules(supplier_key=supplier)}


@router.post("/products")
async def create_rule(data: ProductRuleInput, _admin: dict = Depends(require_admin)):
    suppliers = {s["key"] for s in await db.list_rule_suppliers()}
    if data.supplier_key not in suppliers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"발주처가 없습니다: {data.supplier_key}")
    rule_id = await db.create_product_rule(data.model_dump())
    await rules_engine.refresh_rules()
    return {"status": "ok", "id": rule_id}


@router.put("/products/{rule_id}")
async def update_rule(rule_id: int, data: ProductRuleInput, _admin: dict = Depends(require_admin)):
    if not await db.get_product_rule(rule_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="규칙을 찾을 수 없습니다.")
    await db.update_product_rule(rule_id, data.model_dump())
    await rules_engine.refresh_rules()
    return {"status": "ok"}


@router.delete("/products/{rule_id}")
async def remove_rule(rule_id: int, _admin: dict = Depends(require_admin)):
    await db.delete_product_rule(rule_id)
    await rules_engine.refresh_rules()
    return {"status": "ok"}


@router.post("/preview")
async def preview(data: PreviewInput, _admin: dict = Depends(require_admin)):
    """규칙 해석 미리보기 — '이 주문 텍스트면 어떤 발주 품목명이 되나'."""
    if not rules_engine.get_status()["loaded"]:
        await rules_engine.refresh_rules()
    result = rules_engine.resolve(data.supplier_key, data.product_name, data.option_text)
    return {"matched": result is not None, "result": result}


@router.post("/simulate")
async def simulate(delivery_file: UploadFile = File(...), _admin: dict = Depends(require_admin)):
    """DeliveryList 업로드 → 전 행 규칙 적용 미리보기 (저장·발주서 생성 없음).

    미매칭 행이 곧 '규칙 추가가 필요한 상품' 목록이 된다.
    """
    if not rules_engine.get_status()["loaded"]:
        await rules_engine.refresh_rules()
    delivery_bytes = await delivery_file.read()
    if not delivery_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="빈 파일입니다.")
    try:
        return rules_engine.simulate_delivery(delivery_bytes)
    except Exception as exc:  # openpyxl 파싱 실패 등
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"DeliveryList를 읽지 못했습니다: {exc}",
        )
