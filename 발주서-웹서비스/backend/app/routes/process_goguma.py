"""고구마·호박고구마·게걸무·테무·토스 자동·고구마 CS·내부 고구마 프록시 라우트. main.py에서 분리(2026-11-17)."""

import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app import email_service
from app.auth import verify_token
from app.coupang.client import CoupangApiError
from app.processors import (
    event_order,
    gaegeolmu_order,
    gaegeolmu_tracking,
    goguma_auto,
    goguma_cs,
    goguma_order,
    goguma_tracking,
    goguma_tracking_alwayz,
    goguma_tracking_api,
    hobak_goguma,
    issued_orders,
    temu_order,
    temu_tracking,
    toss_auto,
)
from app.toss.client import TossApiError
from app import api_common as common
from app.api_common import KST

logger = logging.getLogger("app.main")  # 분리 전과 같은 로그 이름

router = APIRouter()

@router.post("/api/process/temu-order")
async def process_temu_order(
    order_file: UploadFile | None = File(None),
    order_text: str = Form(""),
    user: dict = Depends(verify_token),
):
    try:
        if order_file is not None and order_file.filename:
            order_bytes = await order_file.read()
            if not order_bytes:
                raise ValueError("테무 주문 파일이 비어 있습니다.")
            outputs = temu_order.process_file(order_bytes, order_file.filename or "")
            if len(outputs) == 1:
                output_bytes, filename, stats = outputs[0]
                await common.record_sales_from_process_stats(user["user_id"], stats)
                logger.info(f"테무 파일 발주 처리 완료: {stats}")
                return common.make_excel_response(output_bytes, filename, stats)

            kst = timezone(timedelta(hours=9))
            filename = f"테무_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = temu_order.combine_output_stats(outputs)
            logger.info(f"테무 파일 발주 묶음 처리 완료: {stats}")
            return common.make_zip_response(
                [(output_bytes, output_name) for output_bytes, output_name, _ in outputs],
                filename,
                stats,
            )

        if not order_text.strip():
            raise ValueError("테무 주문 엑셀 파일을 업로드하거나 주문상세 텍스트를 붙여넣어 주세요.")
        output_bytes, filename, stats = temu_order.process(order_text)
        await common.record_sales_from_process_stats(user["user_id"], stats)
        logger.info(f"테무 텍스트 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("테무 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/temu-tracking")
async def process_temu_tracking(
    order_export_file: UploadFile = File(...),
    tracking_file: UploadFile = File(...),
    tracking_file2: UploadFile | None = File(None),
    _token: dict = Depends(verify_token),
):
    """테무 주문목록 + 택배 송장파일 → 배송 확인 업로드 템플릿 생성."""
    try:
        order_bytes = await order_export_file.read()
        tracking_files = [(tracking_file.filename or "tracking.xlsx", await tracking_file.read())]
        if tracking_file2 is not None:
            tracking_files.append(
                (tracking_file2.filename or "tracking2.xlsx", await tracking_file2.read())
            )
        output_bytes, filename, stats = temu_tracking.process(
            order_bytes,
            tracking_files,
            order_export_file.filename or "",
        )
        logger.info(f"테무 송장 대량등록 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("테무 송장 대량등록 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/goguma-order")
async def process_goguma_order(
    delivery_file: UploadFile = File(...),
    template_file: UploadFile = File(None),
    alwayz_file: UploadFile = File(None),
    toss_file: UploadFile = File(None),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    exclude_issued: str = Form("true"),
    temu_file: UploadFile = File(None),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await common._issued_exclusions("goguma", exclude_issued)
        issued_dates = await common._issued_exclusion_dates("goguma", exclude_issued)
        reissue_keys = await common._issued_stale_keys("goguma", exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        dup_keys: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        template_bytes = None
        if template_file is not None:
            template_bytes = await template_file.read()
            if len(template_bytes) == 0:
                template_bytes = None

        alwayz_bytes = None
        if alwayz_file is not None:
            alwayz_bytes = await alwayz_file.read()
            if len(alwayz_bytes) == 0:
                alwayz_bytes = None

        toss_file_bytes = None
        if toss_file is not None:
            toss_file_bytes = await toss_file.read()
            if len(toss_file_bytes) == 0:
                toss_file_bytes = None

        temu_bytes = None
        if temu_file is not None:
            temu_bytes = await temu_file.read()
            if len(temu_bytes) == 0:
                temu_bytes = None

        if common._goguma_proxy_enabled():
            proxy_files: list[tuple[str, tuple[str, bytes, str]]] = [
                (
                    "delivery_file",
                    (
                        delivery_file.filename or "delivery.xlsx",
                        delivery_bytes,
                        delivery_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )
            ]
            if template_bytes is not None and template_file is not None:
                proxy_files.append((
                    "template_file",
                    (
                        template_file.filename or "template.xlsx",
                        template_bytes,
                        template_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ))
            if alwayz_bytes is not None and alwayz_file is not None:
                proxy_files.append((
                    "alwayz_file",
                    (
                        alwayz_file.filename or "alwayz.xlsx",
                        alwayz_bytes,
                        alwayz_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ))
            if toss_file_bytes is not None and toss_file is not None:
                proxy_files.append((
                    "toss_file",
                    (
                        toss_file.filename or "toss.xlsx",
                        toss_file_bytes,
                        toss_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ))
            proxy_response = await common._post_proxy_files(
                "goguma-order",
                proxy_files,
                {
                    "toss_from_date": toss_from_date or "",
                    "toss_to_date": toss_to_date or "",
                    "include_toss": include_toss or "",
                },
            )
            await common._record_proxy_sales(user["user_id"], proxy_response)
            return common._proxy_excel_response(proxy_response)

        # Fetch Toss orders from API if date range provided
        toss_entries = []
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))

        # 날짜 범위가 있으면 해당 기간 수집
        if toss_from_date and toss_to_date:
            toss_entries = await goguma_order.collect_toss_orders(
                common._widen_start(toss_from_date, issued_dates, reissue_keys), toss_to_date
            )
        # 하위호환: include_toss=true면 오늘 수집
        elif include_toss.lower() == "true":
            today = datetime.now(KST).strftime("%Y-%m-%d")
            toss_entries = await goguma_order.collect_toss_orders(common._widen_start(today, issued_dates, reissue_keys), today)

        toss_entries, _dup_t = issued_orders.filter_entries_by_issued(
            toss_entries, issued_excluded, skipped_names=dup_names,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        dup_skipped += _dup_t

        output_bytes, filename, stats = goguma_order.process(
            delivery_bytes, template_bytes, alwayz_bytes, toss_entries, toss_file_bytes
        )
        # 테무 주문서(선택)의 고구마 주문을 같은 해달 발주서에 합친다
        temu_issued_ids: list[str] = []
        if temu_bytes:
            temu_entries = temu_order.extract_goguma_entries(temu_bytes, temu_file.filename or "")
            temu_entries, _dup_temu = issued_orders.filter_entries_by_issued(
                temu_entries, issued_excluded, skipped_names=dup_names,
                reissue_keys=reissue_keys, reissued=reissued,
            )
            dup_skipped += _dup_temu
            output_bytes = goguma_order.append_entries_to_haedal(output_bytes, temu_entries)
            stats["temu"] = len(temu_entries)
            temu_issued_ids = [issued_orders.normalize_order_id(e.get("order_id")) for e in temu_entries]
            try:
                stats["total"] = int(stats.get("total") or 0) + len(temu_entries)
            except (TypeError, ValueError):
                pass
        await common._record_issued("goguma", filename, stats, extra_ids=temu_issued_ids)
        stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued)
        await common.record_sales_from_process_stats(
            user["user_id"], stats, ymd=common._extract_ymd_from_filename(delivery_file.filename)
        )
        logger.info(f"고구마 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Goguma Toss order collection failed: %s", e.message)
        common._raise_toss_http_error(e)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("고구마 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


class GogumaAutoRequest(BaseModel):
    from_date: str
    to_date: str
    include_toss: bool = False
    exclude_order_ids: list[str] = []


@router.post("/api/process/goguma-auto")
async def process_goguma_auto(
    from_date: str = Form(...),
    to_date: str = Form(...),
    include_toss: str = Form("false"),
    send_email: str = Form("false"),
    exclude_issued: str = Form("true"),
    alwayz_file: UploadFile = File(None),
    temu_file: UploadFile = File(None),
    winners_file: UploadFile = File(None),
    user: dict = Depends(verify_token),
):
    """쿠팡(+토스) 자동 수집 발주서에 올웨이즈·테무 주문서·라이브 이벤트 당첨자 CSV(선택)를 합치고, 옵션으로 발주 이메일 자동 발송."""
    try:
        include_toss_flag = include_toss.strip().lower() in ("true", "1", "on")
        send_email_flag = send_email.strip().lower() in ("true", "1", "on")
        issued_excluded = await common._issued_exclusions("goguma", exclude_issued)
        issued_dates = await common._issued_exclusion_dates("goguma", exclude_issued)
        reissue_keys = await common._issued_stale_keys("goguma", exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        temu_bytes = None
        if temu_file is not None:
            temu_bytes = await temu_file.read()
            if len(temu_bytes) == 0:
                temu_bytes = None
        alwayz_bytes = None
        if alwayz_file is not None:
            alwayz_bytes = await alwayz_file.read()
            if len(alwayz_bytes) == 0:
                alwayz_bytes = None
        winners_bytes = None
        if winners_file is not None:
            winners_bytes = await winners_file.read()
            if len(winners_bytes) == 0:
                winners_bytes = None

        if common._goguma_proxy_enabled():
            proxy_response = await common._post_proxy_json(
                "goguma-auto",
                {
                    "from_date": from_date,
                    "to_date": to_date,
                    "include_toss": include_toss_flag,
                    "exclude_order_ids": sorted(issued_excluded),
                },
            )
            await common._record_proxy_sales(user["user_id"], proxy_response)
            output_bytes = proxy_response.content
            filename = common._filename_from_proxy_response(proxy_response, "goguma-auto.xlsx")
            try:
                stats = json.loads(proxy_response.headers.get("x-stats") or "{}")
            except ValueError:
                stats = {}
        else:
            output_bytes, filename, stats = await goguma_auto.process_from_api(
                common._widen_start(from_date, issued_dates, reissue_keys), to_date, include_toss=include_toss_flag,
                exclude_order_ids=issued_excluded or None,
                skipped_names=dup_names, reissue_keys=reissue_keys, reissued=reissued,
                allow_empty=bool(winners_bytes),   # 당첨자만 발주하는 날도 발주서가 나오게
            )
            await common.record_sales_from_process_stats(
                user["user_id"], stats, ymd=from_date if from_date == to_date else None
            )

        # 올웨이즈·테무 주문서(선택)를 같은 해달 발주서에 합친다
        extra_issued_ids: list[str] = []

        def _bump_stats(kind: str, count: int, dup: int) -> None:
            stats[kind] = count
            if dup:
                try:
                    stats["duplicate_skipped"] = int(stats.get("duplicate_skipped") or 0) + dup
                except (TypeError, ValueError):
                    stats["duplicate_skipped"] = dup
                if dup_names:
                    stats["duplicate_skipped_names"] = ", ".join(n for n in dup_names if n)
            try:
                stats["total"] = int(stats.get("total") or 0) + count
            except (TypeError, ValueError):
                pass

        if alwayz_bytes:
            alwayz_entries = goguma_order.parse_alwayz_entries(alwayz_bytes)
            alwayz_entries, _dup_alz = issued_orders.filter_entries_by_issued(
                alwayz_entries, issued_excluded, skipped_names=dup_names,
                reissue_keys=reissue_keys, reissued=reissued,
            )
            output_bytes = goguma_order.append_entries_to_haedal(output_bytes, alwayz_entries)
            _bump_stats("alwayz", len(alwayz_entries), _dup_alz)
            extra_issued_ids += [issued_orders.normalize_order_id(e.get("order_id")) for e in alwayz_entries]

        if temu_bytes:
            temu_entries = temu_order.extract_goguma_entries(temu_bytes, temu_file.filename or "")
            temu_entries, _dup_temu = issued_orders.filter_entries_by_issued(
                temu_entries, issued_excluded, skipped_names=dup_names,
                reissue_keys=reissue_keys, reissued=reissued,
            )
            output_bytes = goguma_order.append_entries_to_haedal(output_bytes, temu_entries)
            _bump_stats("temu", len(temu_entries), _dup_temu)
            extra_issued_ids += [issued_orders.normalize_order_id(e.get("order_id")) for e in temu_entries]

        # 라이브 이벤트 당첨자 CSV(선택)의 꿀고구마 경품을 같은 해달 발주서에 합친다(2026-11-16 — 호박고구마와 같은 방식).
        # 이력은 일반 주문과 섹션을 나눠 영구 제외한다(같은 명단을 다시 올려도 중복 발송 없음).
        event_keys: list[str] = []
        if winners_bytes:
            event_excluded = await common._issued_exclusions(goguma_order.EVENT_SECTION, exclude_issued, reissue_stale=False)
            issued_dates = {**issued_dates, **await common._issued_exclusion_dates(goguma_order.EVENT_SECTION, exclude_issued)}
            event_notes: list[str] = []
            # 개인정보 미기재 꿀고구마 당첨자는 주문번호로 쿠팡 발주서를 조회해 받는 사람·주소를 채운다(2026-11-23 —
            # 이 화면은 DeliveryList 없이 API로 주문을 모은다). 조회 실패는 그 당첨자만 '확인 필요'로 남는다.
            event_lookup = await goguma_order.coupang_event_lookup(winners_bytes)
            try:
                event_entries, event_info = goguma_order.prepare_event_entries(
                    winners_bytes, exclude_keys=event_excluded, skipped_names=dup_names, delivery_lookup=event_lookup,
                )
            except ValueError as e:
                # 당첨자 CSV가 깨졌거나 발주할 당첨자가 없어도 쿠팡·토스 발주는 그대로 낸다 — 사유는 화면에
                event_entries, event_info = [], {}
                event_notes.append("당첨자 CSV — " + str(e))
            output_bytes = goguma_order.append_entries_to_haedal(output_bytes, event_entries)
            _bump_stats("event", len(event_entries), int(event_info.get("dup") or 0))
            event_keys = [issued_orders.make_order_key(e.get("order_id"), e.get("product")) for e in event_entries]
            if event_info.get("refund_skipped"):
                stats["refund_skipped"] = event_info["refund_skipped"]
            if event_info.get("filled"):
                stats["filled_from_delivery"] = list(event_info["filled"])
            event_notes = (
                list(event_info.get("incomplete") or []) + list(event_info.get("others") or [])
                + list(event_info.get("unreadable") or []) + event_notes
            )
            if event_notes:
                stats["needs_check"] = list(stats.get("needs_check") or []) + event_notes
            try:
                total_now = int(stats.get("total") or 0)
            except (TypeError, ValueError):
                total_now = 1
            if not total_now:
                # 쿠팡·토스 0건인데 당첨자도 전부 제외·오류 → 빈 발주서를 내지 않고 사유를 띄운다
                try:
                    dup_total = int(stats.get("duplicate_skipped") or 0)
                except (TypeError, ValueError):
                    dup_total = 0
                message = (
                    f"신규 고구마 주문이 없습니다 (이전 발주분 {dup_total}건 자동 제외"
                    + (f": {', '.join(n for n in dup_names if n)}" if dup_names else "") + ")."
                    if dup_total else "해당 기간에 고구마 주문·당첨자가 없습니다."
                )
                if stats.get("needs_check"):
                    message += " (" + " / ".join(str(n) for n in stats["needs_check"]) + ")"
                raise ValueError(message)

        # 발주 이력 기록 (다음 영업일 중복발주 방지)
        await common._record_issued("goguma", filename, stats, extra_ids=extra_issued_ids)
        if event_keys:
            await common._record_issued(goguma_order.EVENT_SECTION, filename, extra_ids=event_keys)

        # 발주 이메일 자동 발송 (shach457@gmail.com -> farmers2022@naver.com)
        if send_email_flag:
            stats["email"] = email_service.send_haedal_order_email(output_bytes, filename)

        stats = common._annotate_excluded(
            stats, int((stats or {}).get("duplicate_skipped") or 0), dup_names, [], issued_dates, reissued=reissued
        )
        logger.info(f"고구마 자동 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except CoupangApiError as e:
        logger.warning("Goguma Coupang auto failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("고구마 자동 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/goguma-tracking-api")
async def process_goguma_tracking_api_endpoint(
    haedal_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """Register 고구마 tracking numbers to Coupang via API."""
    try:
        haedal_bytes = await haedal_file.read()
        if common._goguma_proxy_enabled():
            proxy_response = await common._post_proxy_files(
                "goguma-tracking-api",
                [(
                    "haedal_file",
                    (
                        haedal_file.filename or "haedal.xlsx",
                        haedal_bytes,
                        haedal_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )],
            )
            return proxy_response.json()

        result = await goguma_tracking_api.process_tracking_api(haedal_bytes)
        logger.info(
            f"고구마 운송장 API 등록 완료: "
            f"성공={result['success']}, 실패={result['fail']}, 스킵={result['skip']}"
        )
        return result
    except CoupangApiError as e:
        logger.warning("Goguma Coupang tracking failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("고구마 운송장 API 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


class GogumaCsReplyRequest(BaseModel):
    inquiry_id: int
    content: str


class GogumaCsInquiriesRequest(BaseModel):
    days: int = 7


@router.get("/api/process/goguma-cs/inquiries")
async def get_goguma_cs_inquiries(
    days: int = 7,
    _token: dict = Depends(verify_token),
):
    """고구마 쿠팡 계정 미답변 온라인문의 목록 + 추천 답변."""
    try:
        if common._goguma_proxy_enabled():
            proxy_response = await common._post_proxy_json("goguma-cs-inquiries", {"days": days})
            return proxy_response.json()
        return await goguma_cs.list_unanswered_inquiries(days)
    except CoupangApiError as e:
        logger.warning("Goguma CS inquiry fetch failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except Exception as e:
        logger.exception("고구마 CS 문의 조회 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/goguma-cs/reply")
async def post_goguma_cs_reply(
    req: GogumaCsReplyRequest,
    _token: dict = Depends(verify_token),
):
    """고구마 쿠팡 온라인문의에 답변 전송 (사용자가 확인 버튼을 누른 뒤 호출)."""
    try:
        if common._goguma_proxy_enabled():
            proxy_response = await common._post_proxy_json(
                "goguma-cs-reply",
                {"inquiry_id": req.inquiry_id, "content": req.content},
            )
            return proxy_response.json()
        result = await goguma_cs.send_reply(req.inquiry_id, req.content)
        logger.info(f"고구마 CS 답변 전송: inquiry_id={req.inquiry_id}")
        return result
    except CoupangApiError as e:
        logger.warning("Goguma CS reply failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("고구마 CS 답변 전송 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/internal/goguma/goguma-cs-inquiries")
async def internal_goguma_cs_inquiries(
    req: GogumaCsInquiriesRequest,
    _guard: None = Depends(common._internal_api_key_guard),
):
    del _guard
    try:
        return await goguma_cs.list_unanswered_inquiries(req.days)
    except CoupangApiError as e:
        logger.warning("Internal goguma CS inquiry fetch failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except Exception as e:
        logger.exception("Internal goguma CS inquiry bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/internal/goguma/goguma-cs-reply")
async def internal_goguma_cs_reply(
    req: GogumaCsReplyRequest,
    _guard: None = Depends(common._internal_api_key_guard),
):
    del _guard
    try:
        return await goguma_cs.send_reply(req.inquiry_id, req.content)
    except CoupangApiError as e:
        logger.warning("Internal goguma CS reply failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma CS reply bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


class TossAutoRequest(BaseModel):
    from_date: str
    to_date: str
    exclude_issued: bool = True   # 고구마 화면 '이전 발주분 자동 제외' 체크박스 — '토스만' 버튼도 따른다(2026-11-16)


@router.post("/api/process/toss-order")
async def process_toss_order(
    req: TossAutoRequest,
    user: dict = Depends(verify_token),
):
    """토스 주문만 수집하여 해달 발주서 생성."""
    try:
        if common._goguma_proxy_enabled():
            proxy_response = await common._post_proxy_json(
                "toss-order",
                {"from_date": req.from_date, "to_date": req.to_date},
            )
            await common._record_proxy_sales(user["user_id"], proxy_response)
            return common._proxy_excel_response(proxy_response)

        # '전체 수집'(goguma-auto)과 같은 goguma 이력으로 이전 발주분을 빼고, 만든 발주서는 기록한다.
        # 종전엔 조회도 기록도 안 해 '토스만'과 '전체 수집'을 섞어 쓰면 토스 꿀고구마가 해달에 이중 발주됐다(2026-11-16 리뷰).
        flag = "true" if req.exclude_issued else "false"
        issued_excluded = await common._issued_exclusions("goguma", flag)
        issued_dates = await common._issued_exclusion_dates("goguma", flag)
        reissue_keys = await common._issued_stale_keys("goguma", flag, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        output_bytes, filename, stats = await toss_auto.process_toss_order(
            common._widen_start(req.from_date, issued_dates, reissue_keys), req.to_date,
            exclude_order_ids=issued_excluded or None, skipped_names=dup_names,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        await common.record_sales_from_process_stats(
            user["user_id"], stats, ymd=req.from_date if req.from_date == req.to_date else None
        )
        await common._record_issued("goguma", filename, stats)
        stats = common._annotate_excluded(
            stats, int((stats or {}).get("duplicate_skipped") or 0), dup_names, [], issued_dates, reissued=reissued
        )
        logger.info(f"토스 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Toss order API failed: %s", e.message)
        common._raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("토스 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/toss-tracking-api")
async def process_toss_tracking_api_endpoint(
    haedal_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """토스 운송장번호 자동 등록."""
    try:
        haedal_bytes = await haedal_file.read()
        if common._goguma_proxy_enabled():
            proxy_response = await common._post_proxy_files(
                "toss-tracking-api",
                [(
                    "haedal_file",
                    (
                        haedal_file.filename or "haedal.xlsx",
                        haedal_bytes,
                        haedal_file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                )],
            )
            return proxy_response.json()

        result = await toss_auto.process_toss_tracking(haedal_bytes)
        logger.info(
            f"토스 운송장 등록 완료: "
            f"성공={result['success']}, 실패={result['fail']}, 스킵={result['skip']}"
        )
        return result
    except TossApiError as e:
        logger.warning("Toss tracking API failed: %s", e.message)
        common._raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("토스 운송장 등록 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/internal/goguma/goguma-order")
async def internal_process_goguma_order(
    delivery_file: UploadFile = File(...),
    template_file: UploadFile = File(None),
    alwayz_file: UploadFile = File(None),
    toss_file: UploadFile = File(None),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    _guard: None = Depends(common._internal_api_key_guard),
):
    del _guard
    try:
        delivery_bytes = await delivery_file.read()
        template_bytes = None
        if template_file is not None:
            template_bytes = await template_file.read()
            if len(template_bytes) == 0:
                template_bytes = None

        alwayz_bytes = None
        if alwayz_file is not None:
            alwayz_bytes = await alwayz_file.read()
            if len(alwayz_bytes) == 0:
                alwayz_bytes = None

        toss_file_bytes = None
        if toss_file is not None:
            toss_file_bytes = await toss_file.read()
            if len(toss_file_bytes) == 0:
                toss_file_bytes = None

        toss_entries = []
        if toss_from_date and toss_to_date:
            toss_entries = await goguma_order.collect_toss_orders(toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(KST).strftime("%Y-%m-%d")
            toss_entries = await goguma_order.collect_toss_orders(today, today)

        output_bytes, filename, stats = goguma_order.process(
            delivery_bytes, template_bytes, alwayz_bytes, toss_entries, toss_file_bytes
        )
        return common.make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Internal goguma Toss order collection failed: %s", e.message)
        common._raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma order bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/internal/goguma/goguma-auto")
async def internal_process_goguma_auto(
    req: GogumaAutoRequest,
    _guard: None = Depends(common._internal_api_key_guard),
):
    del _guard
    try:
        output_bytes, filename, stats = await goguma_auto.process_from_api(
            req.from_date, req.to_date, include_toss=req.include_toss,
            exclude_order_ids=set(req.exclude_order_ids) or None,
        )
        return common.make_excel_response(output_bytes, filename, stats)
    except CoupangApiError as e:
        logger.warning("Internal goguma Coupang auto failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma auto bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/internal/goguma/goguma-tracking-api")
async def internal_process_goguma_tracking_api(
    haedal_file: UploadFile = File(...),
    _guard: None = Depends(common._internal_api_key_guard),
):
    del _guard
    try:
        haedal_bytes = await haedal_file.read()
        return await goguma_tracking_api.process_tracking_api(haedal_bytes)
    except CoupangApiError as e:
        logger.warning("Internal goguma Coupang tracking failed: %s", e.message)
        common._raise_coupang_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Internal goguma tracking bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/internal/goguma/toss-order")
async def internal_process_toss_order(
    req: TossAutoRequest,
    _guard: None = Depends(common._internal_api_key_guard),
):
    del _guard
    try:
        output_bytes, filename, stats = await toss_auto.process_toss_order(
            req.from_date, req.to_date
        )
        return common.make_excel_response(output_bytes, filename, stats)
    except TossApiError as e:
        logger.warning("Internal toss order API failed: %s", e.message)
        common._raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Internal toss order bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/internal/goguma/toss-tracking-api")
async def internal_process_toss_tracking_api(
    haedal_file: UploadFile = File(...),
    _guard: None = Depends(common._internal_api_key_guard),
):
    del _guard
    try:
        haedal_bytes = await haedal_file.read()
        return await toss_auto.process_toss_tracking(haedal_bytes)
    except TossApiError as e:
        logger.warning("Internal toss tracking API failed: %s", e.message)
        common._raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Internal toss tracking bridge failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/goguma-tracking-alwayz")
async def process_goguma_tracking_alwayz_endpoint(
    haedal_file: UploadFile = File(...),
    alwayz_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        haedal_bytes = await haedal_file.read()
        alwayz_bytes = await alwayz_file.read()
        output_bytes, filename, stats = goguma_tracking_alwayz.process(
            haedal_bytes, alwayz_bytes
        )
        logger.info(f"올웨이즈 송장 입력 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("올웨이즈 송장 입력 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/goguma-tracking")
async def process_goguma_tracking(
    haedal_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        haedal_bytes = await haedal_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = goguma_tracking.process(
            haedal_bytes, delivery_bytes
        )
        logger.info(f"고구마 송장 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("고구마 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/gaegeolmu-order")
async def process_gaegeolmu_order(
    delivery_file: UploadFile = File(...),
    gmarket_file: UploadFile | None = File(None),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        gmarket_bytes = await gmarket_file.read() if gmarket_file else None
        issued_excluded = await common._issued_exclusions("gaegeolmu", exclude_issued)
        issued_dates = await common._issued_exclusion_dates("gaegeolmu", exclude_issued)
        reissue_keys = await common._issued_stale_keys("gaegeolmu", exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        dup_keys: list[str] = []
        output_bytes, filename, stats = gaegeolmu_order.process(
            delivery_bytes, gmarket_bytes,
            exclude_keys=issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        await common._record_issued("gaegeolmu", filename, stats)
        dup_skipped = int((stats or {}).pop("duplicate_skipped", 0) or 0)
        stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued)
        await common.record_sales_from_process_stats(
            user["user_id"], stats, ymd=common._extract_ymd_from_filename(delivery_file.filename)
        )
        logger.info(f"게걸무 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("게걸무 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/hobak-goguma-order")
async def process_hobak_goguma_order(
    delivery_file: UploadFile | None = File(None),
    winners_file: UploadFile | None = File(None),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    """햇 호박고구마 해달 발주서 — 쿠팡 itsoft001 DeliveryList(선택) + 토스 호박고구마(API)
    + 라이브 이벤트 당첨자 CSV(선택)를 한 파일로 (2026-10-12: 당첨자 발주서가 따로 나와 불편하다는 요청)."""
    section = hobak_goguma.SECTION
    try:
        delivery_bytes = await delivery_file.read() if delivery_file else None
        if delivery_bytes:
            common._require_xlsx(delivery_bytes)
        # 당첨자 주문번호 대조용 DeliveryList 원본 — 이전 발주분 제외(아래) 전에 잡는다(당첨 주문은 이미 발송됐을 수 있음)
        raw_delivery_bytes = delivery_bytes
        winners_bytes = await winners_file.read() if winners_file else None
        issued_excluded = await common._issued_exclusions(section, exclude_issued)
        issued_dates = await common._issued_exclusion_dates(section, exclude_issued)
        reissue_keys = await common._issued_stale_keys(section, exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        dup_keys: list[str] = []
        dup_skipped = 0
        if delivery_bytes:
            delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
                delivery_bytes, issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
                reissue_keys=reissue_keys, reissued=reissued,
            )

        toss_entries: list[dict] = []
        toss_error = ""
        if toss_from_date and toss_to_date:
            try:
                toss_entries = await goguma_order.collect_toss_orders(
                    common._widen_start(toss_from_date, issued_dates, reissue_keys), toss_to_date,
                    matcher=goguma_order.is_hobak_goguma_toss_order,
                )
            except Exception as e:
                # 0건으로 조용히 넘기면 '토스 주문 없음'으로 오해한다 — 사유를 화면에 띄운다
                toss_error = str(e) or type(e).__name__
                if "IP" in toss_error.upper():
                    toss_error += " (토스 파트너센터 > API 허용 IP에 이 PC의 공인 IP를 등록해야 합니다)"
                logger.warning("토스 호박고구마 수집 실패(쿠팡분만 계속): %s", e)
            if toss_entries:
                before = len(dup_names)
                toss_entries, toss_dup = issued_orders.filter_entries_by_issued(
                    toss_entries, issued_excluded, skipped_names=dup_names,
                    reissue_keys=reissue_keys, reissued=reissued,
                )
                if toss_dup:
                    dup_skipped += toss_dup
                    # 토스 제외분은 키 목록 길이를 이름 목록에 맞춘다(_annotate_excluded가 인덱스로 짝지음)
                    dup_keys.extend([""] * (len(dup_names) - before))

        # 라이브 이벤트 당첨자: 이력은 이벤트 섹션 따로(10/6 단독 카드로 낸 당첨자 이력과 이어짐)
        event_entries: list[dict] = []
        event_info: dict = {}
        event_error = ""
        if winners_bytes:
            event_excluded = await common._issued_exclusions(hobak_goguma.EVENT_SECTION, exclude_issued, reissue_stale=False)
            issued_dates = {**issued_dates, **await common._issued_exclusion_dates(hobak_goguma.EVENT_SECTION, exclude_issued)}
            try:
                # 개인정보 미기재 당첨자는 같이 올린 DeliveryList에서 주문번호로 찾아 채운다(2026-11-23).
                # 호박고구마 주문 계정(itsoft001)은 쿠팡 API 키가 없어 꿀고구마처럼 API로 조회하지 못한다.
                event_entries, event_info = hobak_goguma.prepare_event_entries(
                    winners_bytes, exclude_keys=event_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
                    delivery_lookup=event_order.build_delivery_lookup([raw_delivery_bytes]) if raw_delivery_bytes else None,
                )
                dup_skipped += int(event_info.get("dup") or 0)
            except ValueError as e:
                # 당첨자 CSV가 깨졌거나 발주 가능한 당첨자가 없어도 쿠팡·토스 발주는 그대로 낸다 — 사유는 화면에
                event_error = str(e)

        output_bytes, filename, stats = hobak_goguma.process_order(
            delivery_bytes, toss_entries, event_entries=event_entries
        )
        if toss_error:
            stats["toss"] = "수집 실패"
            stats["needs_check"] = list(stats.get("needs_check") or []) + ["토스 주문 수집 실패 — " + toss_error]
        if winners_bytes:
            stats.setdefault("event", len(event_entries))
            if event_info.get("refund_skipped"):
                stats["refund_skipped"] = event_info["refund_skipped"]
            if event_info.get("filled"):
                stats["filled_from_delivery"] = list(event_info["filled"])
            extra = list(event_info.get("incomplete") or []) + list(event_info.get("others") or [])
            if event_info.get("incomplete") and not raw_delivery_bytes:
                extra.append("쿠팡 DeliveryList(itsoft001)를 같이 올리면 개인정보 미기재 당첨자를 주문번호로 찾아 채웁니다")
            if event_error:
                extra.append("당첨자 CSV — " + event_error)
            if extra:
                stats["needs_check"] = list(stats.get("needs_check") or []) + extra
        if not int(stats.get("total") or 0):
            if dup_skipped:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"신규 호박고구마 주문이 없습니다 (이전 발주분 {dup_skipped}건 자동 제외: {', '.join(n for n in dup_names if n)})."
                    + (f" (토스 수집 실패 — {toss_error})" if toss_error else ""),   # 토스 실패를 '신규 없음'으로 덮지 않는다
                )
            detail = "호박고구마 주문이 없습니다."
            if toss_error:
                detail += f" (토스 수집 실패 — {toss_error})"
            if event_error:
                detail += f" (당첨자 CSV — {event_error})"
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

        event_options = stats.pop("event_options", None)
        await common._record_issued(section, filename, stats)
        if event_options:
            await common._record_issued(hobak_goguma.EVENT_SECTION, filename, {"options": event_options})
        stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued)
        await common.record_sales_from_process_stats(
            user["user_id"],
            stats,
            ymd=common._extract_ymd_from_filename(delivery_file.filename if delivery_file else None),
        )
        logger.info(f"호박고구마 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("호박고구마 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/hobak-goguma-tracking")
async def process_hobak_goguma_tracking(
    haedal_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """해달 회신 → 쿠팡 itsoft001 DeliveryList 호박고구마 행 E(송장)·D(한진택배) 입력."""
    try:
        haedal_bytes = await haedal_file.read()
        delivery_bytes = await delivery_file.read()
        common._require_xlsx(delivery_bytes)
        output_bytes, filename, stats = hobak_goguma.process_tracking(haedal_bytes, delivery_bytes)
        logger.info(f"호박고구마 쿠팡 운송장 입력 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("호박고구마 운송장 입력 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/hobak-goguma-event-order")
async def process_hobak_goguma_event_order(
    winners_file: UploadFile = File(...),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    """라이브 이벤트 당첨자 CSV → 호박고구마 경품 해달 발주서 (같은 CSV 재업로드 시 이전 발주분 자동 제외)."""
    section = hobak_goguma.EVENT_SECTION
    try:
        csv_bytes = await winners_file.read()
        issued_excluded = await common._issued_exclusions(section, exclude_issued, reissue_stale=False)
        issued_dates = await common._issued_exclusion_dates(section, exclude_issued)
        dup_names: list[str] = []
        dup_keys: list[str] = []
        output_bytes, filename, stats = hobak_goguma.process_event(
            csv_bytes, exclude_keys=issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys
        )
        await common._record_issued(section, filename, stats)
        dup_skipped = int((stats or {}).pop("duplicate_skipped", 0) or 0)
        stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates)
        logger.info(f"호박고구마 이벤트 당첨자 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("호박고구마 이벤트 당첨자 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/hobak-goguma-toss-tracking")
async def process_hobak_goguma_toss_tracking(
    haedal_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """해달 회신 → 토스 호박고구마 주문에 운송장 API 등록 (꿀고구마 토스 주문은 건드리지 않음)."""
    try:
        haedal_bytes = await haedal_file.read()
        result = await toss_auto.process_toss_tracking(
            haedal_bytes,
            product_filter=goguma_order.is_hobak_goguma_toss_order,
            product_label="호박고구마",
        )
        logger.info(
            f"토스 호박고구마 운송장 등록: 성공={result['success']}, 실패={result['fail']}, 스킵={result['skip']}"
        )
        return result
    except TossApiError as e:
        logger.warning("Toss hobak tracking API failed: %s", e.message)
        common._raise_toss_http_error(e)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("토스 호박고구마 운송장 등록 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/gaegeolmu-tracking")
async def process_gaegeolmu_tracking(
    tracking_file: UploadFile = File(None),
    delivery_file: UploadFile = File(...),
    tracking_text: str = Form(""),
    _token: dict = Depends(verify_token),
):
    """게걸무 운송장 입력. 택배발송 파일 또는 이름/운송장 복붙 텍스트(둘 다 가능)."""
    try:
        tracking_bytes = None
        if tracking_file is not None:
            tracking_bytes = await tracking_file.read()
            if not tracking_bytes:
                tracking_bytes = None
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = gaegeolmu_tracking.process(
            tracking_bytes, delivery_bytes, tracking_text=tracking_text
        )
        logger.info(f"게걸무 운송장 입력 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("게걸무 운송장 입력 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )
