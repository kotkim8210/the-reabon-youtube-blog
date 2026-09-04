#!/usr/bin/env python3
"""AdminPlus CS JSON을 복사 가능한 한국어 6줄 템플릿으로 렌더링한다."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NoReturn, TextIO


FIELDS = (
    "order_date",
    "delivery_date",
    "internal_order_number",
    "recipient_name",
    "product_name",
    "tracking_number",
    "request_summary",
)


def fail(message: str) -> NoReturn:
    print(f"오류: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalize(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()


def validate_record(record: object, context: str) -> dict[str, str]:
    if not isinstance(record, dict):
        fail(f"{context}은(는) JSON 객체여야 합니다.")

    normalized: dict[str, str] = {}
    for key in FIELDS:
        if key not in record:
            fail(f"{context}에 필수 키 '{key}'가 없습니다.")
        value = record[key]
        if not isinstance(value, str):
            fail(f"{context}의 '{key}' 값은 문자열이어야 합니다.")
        value = normalize(value)
        if not value:
            fail(f"{context}의 '{key}' 값은 빈 문자열일 수 없습니다.")
        normalized[key] = value
    return normalized


def render(record: dict[str, str]) -> str:
    return "\n".join(
        (
            f"발주일자/수령일자 : {record['order_date']}/{record['delivery_date']}",
            f"고객 주문번호 : {record['internal_order_number']}",
            f"수취인 성함 : {record['recipient_name']}",
            f"발주 상품명 : {record['product_name']}",
            f"송장번호 : {record['tracking_number']}",
            f"원하시는 환불비중 : {record['request_summary']}",
        )
    )


def load_json_text(text: str, source: str) -> object:
    try:
        return json.loads(text.lstrip("\ufeff"))
    except json.JSONDecodeError as exc:
        fail(
            f"{source}의 내용이 올바른 JSON이 아닙니다: "
            f"{exc.msg} (줄 {exc.lineno}, 열 {exc.colno})"
        )


def load_json(input_stream: TextIO, source: str) -> object:
    return load_json_text(input_stream.read(), source)


def render_data(data: object) -> str:
    if isinstance(data, dict):
        return render(validate_record(data, "입력 객체"))

    if isinstance(data, list):
        if not data:
            fail("입력 배열에는 최소 1개의 객체가 필요합니다.")
        if len(data) == 1:
            return render(validate_record(data[0], "배열 1번째 항목"))
        blocks = []
        for index, item in enumerate(data, start=1):
            record = validate_record(item, f"배열 {index}번째 항목")
            blocks.append(f"[CS {index}]\n\n{render(record)}")
        return "\n\n".join(blocks)

    fail("JSON 최상위 값은 객체 또는 객체 배열이어야 합니다.")


def main() -> None:
    if len(sys.argv) != 2:
        fail("사용법: render_template.py <입력.json|->")

    source = sys.argv[1]
    if source == "-":
        try:
            stdin_text = sys.stdin.buffer.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            fail(f"표준입력은 UTF-8이어야 합니다: {exc}")
        data = load_json_text(stdin_text, "표준입력")
    else:
        input_path = Path(source)
        try:
            with input_path.open("r", encoding="utf-8-sig") as input_file:
                data = load_json(input_file, str(input_path))
        except FileNotFoundError:
            fail(f"입력 파일을 찾을 수 없습니다: {input_path}")
        except UnicodeError as exc:
            fail(f"입력 파일은 UTF-8이어야 합니다: {exc}")
        except OSError as exc:
            fail(f"입력 파일을 읽을 수 없습니다: {exc}")

    print(render_data(data))


if __name__ == "__main__":
    main()
