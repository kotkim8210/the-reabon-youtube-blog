"""과일·채소 발주서·송장 라우트(콜라비/제주다팜·참두릅·당근·쥬얼리·이벤트·제이비티·토스 과일). main.py에서 분리(2026-11-17)."""

import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app import email_service, product_registry
from app.auth import verify_token
from app.processors import (
    batch_tracking_merge,
    chamdureup_order,
    chamdureup_tracking,
    daangn_order,
    event_order,
    issued_orders,
    kolrabi_order,
    myeongi_order,
    myeongi_tracking,
    tomato_order,
    tomato_tracking,
    tracking_input,
)
from app.toss.client import TossApiError
from app import api_common as common
from app.api_common import KST

logger = logging.getLogger("app.main")  # 분리 전과 같은 로그 이름

router = APIRouter()

@router.post("/api/process/kolrabi-order")
async def process_kolrabi_order(
    delivery_file: UploadFile = File(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        common._require_xlsx(delivery_bytes)
        issued_excluded = await common._issued_exclusions("kolrabi", exclude_issued)
        issued_dates = await common._issued_exclusion_dates("kolrabi", exclude_issued)
        reissue_keys = await common._issued_stale_keys("kolrabi", exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        dup_keys: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        # 토스 제주다팜 주문(상품 레지스트리 TOSS_PRODUCTS)을 토스 API로 수집해 각 발주서에 합친다.
        toss_entries: dict[str, list] = {product.key: [] for product in product_registry.TOSS_PRODUCTS}
        toss_error = ""
        collect_dates = None
        if toss_from_date and toss_to_date:
            collect_dates = (toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            collect_dates = (today, today)
        if collect_dates:
            # 재발주 대상 발주일까지 수집 기간을 넓힌다(기본 기간엔 옛 주문이 안 들어와 재발주가 안 걸림)
            collect_dates = (common._widen_start(collect_dates[0], issued_dates, reissue_keys), collect_dates[1])
            try:
                toss_jeju = await tomato_order.collect_toss_jejudapam_orders(*collect_dates)
                toss_dup = 0
                for product in product_registry.TOSS_PRODUCTS:
                    toss_entries[product.key], _dup = issued_orders.filter_entries_by_issued(
                        toss_jeju.get(product.key, []), issued_excluded, skipped_names=dup_names,
                        reissue_keys=reissue_keys, reissued=reissued,
                    )
                    toss_dup += _dup
                dup_skipped += toss_dup
            except Exception as toss_exc:
                toss_error = str(toss_exc)
                logger.warning(f"토스 제주다팜({product_registry.toss_labels()}) 수집 실패(발주는 계속): {toss_exc}")

        results = kolrabi_order.process_outputs(delivery_bytes, toss_entries=toss_entries)
        if not results:
            dup_note = f" (이전 발주분 {dup_skipped}건 자동 제외됨)" if dup_skipped else ""
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"제주다팜 발주로 출력할 {product_registry.toss_labels()} 주문을 찾지 못했습니다.{dup_note}" + (f" (토스 수집 실패 — {toss_error})" if toss_error else ""),
            )

        sales_ymd = common._extract_ymd_from_filename(delivery_file.filename)
        for _, _, item_stats in results:
            await common.record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)
        await common._record_issued("kolrabi", results[0][1], *[item_stats for _, _, item_stats in results])

        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued)
            if toss_error:
                stats = {**(stats or {}), "toss_error": toss_error}
            response = common.make_excel_response(output_bytes, filename, stats)
        else:
            kst = timezone(timedelta(hours=9))
            filename = f"제주다팜_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = {
                "files": len(results),
                "total": sum(int((item_stats or {}).get("total", 0)) for _, _, item_stats in results),
            }
            zip_notes = common._merge_needs_check(results)   # 파일별 '거래처 판매옵션에 없음' 경고를 zip 응답에도 싣는다
            if zip_notes:
                stats["needs_check"] = zip_notes
            stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued)
            if toss_error:
                stats["toss_error"] = toss_error
            response = common.make_zip_response(
                [(output_bytes, output_name) for output_bytes, output_name, _ in results],
                filename,
                stats,
            )
        logger.info(f"콜라비 발주 처리 완료: {stats}")
        return response
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("콜라비 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/chamdureup-order")
async def process_chamdureup_order(
    delivery_file: UploadFile = File(...),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await common._issued_exclusions("chamdureup", exclude_issued)
        issued_dates = await common._issued_exclusion_dates("chamdureup", exclude_issued)
        reissue_keys = await common._issued_stale_keys("chamdureup", exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        dup_keys: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        output_bytes, filename, stats = chamdureup_order.process(delivery_bytes)
        await common._record_issued("chamdureup", filename, stats)
        stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued)
        await common.record_sales_from_process_stats(
            user["user_id"], stats, ymd=common._extract_ymd_from_filename(delivery_file.filename)
        )
        logger.info(f"참두릅 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("참두릅 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/chamdureup-tracking")
async def process_chamdureup_tracking(
    orderlist_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        orderlist_bytes = await orderlist_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = chamdureup_tracking.process(
            orderlist_bytes, delivery_bytes
        )
        logger.info(f"참두릅 운송장 입력 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("참두릅 운송장 입력 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/daangn-order")
async def process_daangn_order(
    text: str = Form(...),
    user: dict = Depends(verify_token),
):
    """당근마켓 주문 상세 텍스트 → 쥬얼리프룻 발주서."""
    try:
        result = daangn_order.process(text)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="당근 주문 텍스트에서 발주할 주문을 찾지 못했습니다. (상품·옵션(예: '대과 2kg 1개')·받는 사람 줄이 있는지 확인)",
            )
        output_bytes, filename, stats = result
        await common.record_sales_from_process_stats(user["user_id"], stats, ymd=None)
        logger.info(f"당근 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("당근 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/myeongi-order")
async def process_myeongi_order(
    delivery_file: UploadFile = File(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        common._require_xlsx(delivery_bytes)
        issued_excluded = await common._issued_exclusions("myeongi", exclude_issued)
        issued_dates = await common._issued_exclusion_dates("myeongi", exclude_issued)
        reissue_keys = await common._issued_stale_keys("myeongi", exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        dup_keys: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        # 토스 쥬얼리 주문(수박·성주참외·신비복숭아·망고수박)을 토스 API로 수집해 함께 발주.
        # 토스 신비복숭아 수집은 이 페이지(명이)로 일원화됨.
        toss_entries = []
        toss_error = ""
        collect_dates = None
        if toss_from_date and toss_to_date:
            collect_dates = (toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            collect_dates = (today, today)
        if collect_dates:
            # 재발주 대상 발주일까지 수집 기간을 넓힌다(기본 기간엔 옛 주문이 안 들어와 재발주가 안 걸림)
            collect_dates = (common._widen_start(collect_dates[0], issued_dates, reissue_keys), collect_dates[1])
            try:
                toss_entries = await tomato_order.collect_toss_jewelry_orders(*collect_dates)
                toss_entries, _dup_t = issued_orders.filter_entries_by_issued(
                    toss_entries, issued_excluded, skipped_names=dup_names,
                    reissue_keys=reissue_keys, reissued=reissued,
                )
                dup_skipped += _dup_t
            except Exception as toss_exc:
                toss_error = str(toss_exc)
                logger.warning(f"토스 쥬얼리 수집 실패(발주는 계속): {toss_exc}")

        output_bytes, filename, stats = myeongi_order.process(
            delivery_bytes, toss_entries=toss_entries
        )
        await common._record_issued("myeongi", filename, stats)
        stats = common._annotate_excluded(stats, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued)
        if toss_error:
            stats = {**(stats or {}), "toss_error": toss_error}
        await common.record_sales_from_process_stats(
            user["user_id"], stats, ymd=common._extract_ymd_from_filename(delivery_file.filename)
        )
        logger.info(f"명이나물 발주 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("명이나물 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/event-winner-order")
async def process_event_winner_order(
    winners_file: UploadFile = File(...),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    """라이브 이벤트 당첨자 CSV → 발주처별 발주서(제주다팜·쥬얼리프룻·제이비티, 2곳 이상이면 zip).

    꿀·호박고구마 경품은 고구마 화면에서 해달로 발주하므로 여기선 뺀다(event_order.process).
    같은 명단을 다시 올려도 이전에 발주한 당첨자는 영구 제외한다(event_order.EVENT_SECTION) — 종전엔 화면의
    '이전 발주분 자동 제외' 체크박스를 백엔드가 받지 않아 재업로드하면 전원 다시 발주됐다(2026-11-16 리뷰).
    """
    section = event_order.EVENT_SECTION
    try:
        csv_bytes = await winners_file.read()
        issued_excluded = await common._issued_exclusions(section, exclude_issued, reissue_stale=False)
        issued_dates = await common._issued_exclusion_dates(section, exclude_issued)
        dup_names: list[str] = []
        dup_keys: list[str] = []
        event_keys: list[str] = []
        results = event_order.process(
            csv_bytes, exclude_keys=issued_excluded, skipped_names=dup_names,
            skipped_keys=dup_keys, issued_keys=event_keys,
        )
        if len(results) == 1:
            output_bytes, filename, stats = results[0]
        else:
            filename = f"이벤트당첨_발주묶음({datetime.now(KST).strftime('%Y%m%d')}).zip"
            first = results[0][2] or {}
            stats = {
                "files": len(results),
                "winners": sum(int((s or {}).get("winners", 0)) for _, _, s in results),
                "suppliers": ", ".join((s or {}).get("supplier", "") for _, _, s in results),
            }
            # 환불 제외·확인필요는 event_order가 첫 파일에만 싣는다 → zip 응답에도 옮겨 화면에 보이게
            for key in ("skipped_refund", "needs_check"):
                if first.get(key):
                    stats[key] = first[key]
        if isinstance(stats.get("needs_check"), str):
            stats = {**stats, "needs_check": [stats["needs_check"]]}   # _annotate_excluded가 목록에 덧붙인다
        await common._record_issued(section, filename, extra_ids=event_keys)
        stats = common._annotate_excluded(stats, len(dup_names), dup_names, dup_keys, issued_dates)
        logger.info(f"이벤트 당첨자 발주 처리 완료: {stats}")
        if len(results) == 1:
            return common.make_excel_response(output_bytes, filename, stats)
        # 한글 X-Stats는 ensure_ascii=True(make_zip_response)라야 헤더 인코딩 오류가 안 난다
        return common.make_zip_response([(b, name) for b, name, _ in results], filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("이벤트 당첨자 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/tomato-order")
async def process_tomato_order(
    delivery_file: UploadFile = File(...),
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    include_toss: str = Form(""),
    exclude_issued: str = Form("true"),
    user: dict = Depends(verify_token),
):
    try:
        delivery_bytes = await delivery_file.read()
        issued_excluded = await common._issued_exclusions("tomato", exclude_issued)
        issued_dates = await common._issued_exclusion_dates("tomato", exclude_issued)
        reissue_keys = await common._issued_stale_keys("tomato", exclude_issued, issued_dates)
        reissued: list[tuple[str, str]] = []
        dup_names: list[str] = []
        dup_keys: list[str] = []
        delivery_bytes, dup_skipped = issued_orders.filter_delivery_by_issued(
            delivery_bytes, issued_excluded, skipped_names=dup_names, skipped_keys=dup_keys,
            reissue_keys=reissue_keys, reissued=reissued,
        )
        # 신비복숭아 3·4kg은 쿠팡(DeliveryList) + 토스(API)에서 모두 제이비티 발주로 합친다.
        # (1·2kg은 명이/쥬얼리 메뉴, 수박·성주참외 등 다른 토스 품목은 명이로 일원화)
        toss_peach_entries = []
        toss_peach_error = ""
        collect_dates = None
        if toss_from_date and toss_to_date:
            collect_dates = (toss_from_date, toss_to_date)
        elif include_toss.lower() == "true":
            today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
            collect_dates = (today, today)
        if collect_dates:
            # 재발주 대상 발주일까지 수집 기간을 넓힌다(기본 기간엔 옛 주문이 안 들어와 재발주가 안 걸림)
            collect_dates = (common._widen_start(collect_dates[0], issued_dates, reissue_keys), collect_dates[1])
            try:
                toss_peach_entries = await tomato_order.collect_toss_peach_orders(
                    *collect_dates, kgs=tomato_order.JBT_PEACH_KGS
                )
                toss_peach_entries, _dup_p = issued_orders.filter_entries_by_issued(
                    toss_peach_entries, issued_excluded, skipped_names=dup_names,
                    reissue_keys=reissue_keys, reissued=reissued,
                )
                dup_skipped += _dup_p
            except Exception as toss_exc:
                toss_peach_error = str(toss_exc)
                logger.warning(f"토스 신비복숭아 3·4kg 수집 실패(발주는 계속): {toss_exc}")

        results = tomato_order.process_outputs(delivery_bytes, toss_peach_entries=toss_peach_entries)
        if not results:
            # 그날 주문이 전부 이전 발주분이면 '찾지 못했습니다'만으로는 왜 비었는지 모른다 → 건수·받는분(발주일)을 붙인다
            dup_note = ""
            if dup_skipped:
                labels = common._annotate_excluded({}, dup_skipped, dup_names, dup_keys, issued_dates).get("duplicate_skipped_names")
                dup_note = f" (이전 발주분 {dup_skipped}건 자동 제외됨: {labels})" if labels else f" (이전 발주분 {dup_skipped}건 자동 제외됨)"
            # 토스 수집이 실패했으면 함께 알린다 — '주문 없음'으로 덮으면 토스 신비복숭아가 조용히 빠진다
            toss_note = f" (토스 신비복숭아 수집 실패 — {toss_peach_error})" if toss_peach_error else ""
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"제이비티 발주로 출력할 대저토마토·남해땅두릅·초당옥수수·신비복숭아 주문을 찾지 못했습니다.{dup_note} 수박·성주참외는 쥬얼리프룻 메뉴에서 출력됩니다." + toss_note,
            )
        sales_ymd = common._extract_ymd_from_filename(delivery_file.filename)
        for _, _, item_stats in results:
            await common.record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)
        # 제이비티 stats는 버킷이 품목별 sales_groups 안에 있다 → 기록용 'options'로 펴서 넘긴다(그대로 넘기면 키 0개)
        await common._record_issued(
            "tomato", results[0][1], *[tomato_order.issued_record_stats(item_stats) for _, _, item_stats in results]
        )

        toss_peach_info = {}
        if toss_peach_entries:
            toss_peach_info["toss_peach_orders"] = len(toss_peach_entries)
        if toss_peach_error:
            toss_peach_info["toss_peach_error"] = toss_peach_error
        # 제외·재발주 받는분 옆에 발주일을 붙인다(콜라비 등 다른 메뉴와 같은 표시) — 동명이인 새 주문과 구분
        toss_peach_info = common._annotate_excluded(
            toss_peach_info, dup_skipped, dup_names, dup_keys, issued_dates, reissued=reissued,
        )

        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            stats = {**(stats or {}), **toss_peach_info}
            response = common.make_excel_response(output_bytes, filename, stats)
        else:
            kst = timezone(timedelta(hours=9))
            filename = f"아이티소프트_발주묶음({datetime.now(kst).strftime('%Y%m%d')}).zip"
            stats = {
                "files": len(results),
                "total": sum(int((item_stats or {}).get("total", 0)) for _, _, item_stats in results),
                **toss_peach_info,
            }
            response = common.make_zip_response(
                [(output_bytes, output_name) for output_bytes, output_name, _ in results],
                filename,
                stats,
            )
        logger.info(f"대저토마토 발주 처리 완료: {stats}")
        return response
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("대저토마토 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/toss-watermelon-order")
async def process_toss_watermelon_order(
    toss_from_date: str = Form(""),
    toss_to_date: str = Form(""),
    alwayz_file: UploadFile | None = File(default=None),
    user: dict = Depends(verify_token),
):
    try:
        alwayz_bytes = await alwayz_file.read() if alwayz_file else None
        # ※ 토스 수집은 명이(쥬얼리) 메뉴로 일원화됨 — 이 메뉴는 올웨이즈 파일만 처리.
        del toss_from_date, toss_to_date
        today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
        from_date = to_date = today
        results = await tomato_order.process_toss_watermelon_order(
            from_date,
            to_date,
            alwayz_bytes=alwayz_bytes,
            collect_toss=False,
        )
        if not results:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="토스/올웨이즈에서 발주 대상 주문을 찾지 못했습니다.",
            )
        sales_ymd = from_date if from_date == to_date else None
        for _, _, item_stats in results:
            await common.record_sales_from_process_stats(user["user_id"], item_stats, ymd=sales_ymd)

        if len(results) == 1:
            output_bytes, filename, stats = results[0]
            logger.info(f"토스 발주 처리 완료(단일): {stats}")
            return common.make_excel_response(output_bytes, filename, stats)

        kst = timezone(timedelta(hours=9))
        zip_name = f"토스발주묶음_쥬얼리_제이비티({datetime.now(kst).strftime('%Y%m%d')}).zip"
        zip_stats = {
            "files": len(results),
            "total": sum(int((s or {}).get("total", 0)) for _, _, s in results),
            "filenames": [fn for _, fn, _ in results],
        }
        logger.info(f"토스 발주 처리 완료(묶음): {zip_stats}")
        return common.make_zip_response(
            [(b, fn) for b, fn, _ in results],
            zip_name,
            zip_stats,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("토스 발주 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/send-order-email")
async def send_order_email(
    files: list[UploadFile] = File(...),
    supplier: str = Form("haedal"),
    _token: dict = Depends(verify_token),
):
    """업로드한 발주서 파일(1개 이상)을 발주처 메일로 첨부 발송.

    supplier=haedal(기본) → farmers2022@naver.com.
    테무 해달 발주서를 따로 뽑았거나 발주서를 수정해서 재발송할 때 사용.
    """
    attachments: list[tuple[bytes, str]] = []
    for upload in files:
        data = await upload.read()
        if data:
            attachments.append((data, upload.filename or "발주서.xlsx"))
    if not attachments:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="첨부할 발주서 파일이 없습니다.")
    result = email_service.send_order_files_email(attachments, supplier)
    if not result.get("sent"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"이메일 발송 실패: {result.get('error')}",
        )
    logger.info(f"발주서 수동 이메일 발송({supplier}): {[name for _, name in attachments]}")
    return {"status": "ok", **result, "files": [name for _, name in attachments]}


@router.post("/api/process/tracking-input")
async def process_tracking_input(
    orderlist_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        orderlist_bytes = await orderlist_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = tracking_input.process(
            orderlist_bytes, delivery_bytes
        )
        logger.info(f"운송장 입력 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("운송장 입력 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/myeongi-tracking")
async def process_myeongi_tracking(
    orderlist_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        orderlist_bytes = await orderlist_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = myeongi_tracking.process(
            orderlist_bytes, delivery_bytes
        )
        logger.info(f"명이나물 운송장 입력 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("명이나물 운송장 입력 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/tomato-tracking")
async def process_tomato_tracking(
    tomato_reply_file: UploadFile = File(...),
    delivery_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        tomato_reply_bytes = await tomato_reply_file.read()
        delivery_bytes = await delivery_file.read()
        output_bytes, filename, stats = tomato_tracking.process(
            tomato_reply_bytes, delivery_bytes
        )
        try:
            toss_stats = await tomato_tracking.process_toss_watermelon_tracking(tomato_reply_bytes)
        except Exception as toss_error:
            logger.exception("토스 수박 6/7/8kg 송장 자동등록 중 오류")
            toss_stats = {
                "toss_orders": 0,
                "toss_success": 0,
                "toss_fail": 0,
                "toss_skip": 0,
                "toss_error": str(toss_error),
            }
        stats = {**(stats or {}), **toss_stats}
        logger.info(f"대저토마토 송장 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except Exception as e:
        logger.exception("대저토마토 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/toss-watermelon-tracking")
async def process_toss_watermelon_tracking(
    tomato_reply_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        tomato_reply_bytes = await tomato_reply_file.read()
        stats = await tomato_tracking.process_toss_watermelon_tracking(tomato_reply_bytes)
        logger.info(f"토스 수박 6/7/8kg 송장 처리 완료: {stats}")
        return {"status": "ok", **stats}
    except TossApiError as e:
        logger.warning("Toss watermelon tracking API failed: %s", e.message)
        common._raise_toss_http_error(e)
    except Exception as e:
        logger.exception("토스 수박 6/7/8kg 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/alwayz-jbt-tracking")
async def process_alwayz_jbt_tracking(
    tomato_reply_file: UploadFile = File(...),
    alwayz_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """제이비티 회신 파일 운송장번호를 올웨이즈 주문내역 파일에 입력해 반환."""
    try:
        tomato_reply_bytes = await tomato_reply_file.read()
        alwayz_bytes = await alwayz_file.read()
        output_bytes, filename, stats = tomato_tracking.process_alwayz_tracking(
            tomato_reply_bytes, alwayz_bytes
        )
        logger.info(f"올웨이즈 송장 처리 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("올웨이즈 송장 처리 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/toss-excel-tracking")
async def process_toss_excel_tracking(
    tomato_reply_file: UploadFile = File(...),
    toss_export_file: UploadFile = File(...),
    _token: dict = Depends(verify_token),
):
    """거래처 회신 운송장번호를 토스 '엑셀 일괄발송' 파일에 채워 반환."""
    try:
        reply_bytes = await tomato_reply_file.read()
        toss_export_bytes = await toss_export_file.read()
        output_bytes, filename, stats = tomato_tracking.process_toss_excel_tracking(
            reply_bytes, toss_export_bytes
        )
        logger.info(f"토스 엑셀 송장 입력 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("토스 엑셀 송장 입력 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"처리 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("/api/process/batch-tracking-merge")
async def process_batch_tracking_merge(
    result_files: list[UploadFile] = File(...),
    _token: dict = Depends(verify_token),
):
    try:
        files_to_merge = []
        for result_file in result_files:
            files_to_merge.append(
                (result_file.filename or "result.xlsx", await result_file.read())
            )
        output_bytes, filename, stats = batch_tracking_merge.process(files_to_merge)
        logger.info(f"일괄 운송장 입력 통합 파일 생성 완료: {stats}")
        return common.make_excel_response(output_bytes, filename, stats)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("일괄 운송장 입력 통합 파일 생성 중 오류")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"통합 파일 생성 중 오류가 발생했습니다: {str(e)}",
        )
