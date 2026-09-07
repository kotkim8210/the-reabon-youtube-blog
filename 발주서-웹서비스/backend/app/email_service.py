"""해달 발주서 이메일 자동 발송 (Gmail SMTP).

발주 버튼 클릭 시 생성된 해달 발주서(쿠팡+토스+테무 통합)를
shach457@gmail.com → farmers2022@naver.com 으로 자동 발송한다.
GMAIL_APP_PASSWORD(구글 앱 비밀번호)는 배포 환경 secrets로 주입:
    fly secrets set GMAIL_APP_PASSWORD=xxxx -a rj-balju
"""
import logging
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

GMAIL_USER = os.getenv("GMAIL_USER", "shach457@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
HAEDAL_ORDER_EMAIL_TO = os.getenv("HAEDAL_ORDER_EMAIL_TO", "farmers2022@naver.com")
# 비셀러(리앤유커머스) 발주 메일 — 거래처 안내: 상품명은 반드시 비셀러 상품명으로 작성
BISELLER_ORDER_EMAIL_TO = os.getenv("BISELLER_ORDER_EMAIL_TO", "naeun_order@naver.com")

# 발주처별 수신자·제목·본문. 키는 API의 supplier 값.
ORDER_EMAIL_TARGETS = {
    "haedal": {
        "to": HAEDAL_ORDER_EMAIL_TO,
        "subject": "{ymd} 알제이시스템 발주서",
        "body": "발주서 첨부합니다.\n감사합니다.",
    },
    "biseller": {
        "to": BISELLER_ORDER_EMAIL_TO,
        "subject": "{ymd} 아이티소프트 발주서",
        "body": "발주서 첨부합니다.\n상품명은 비셀러 상품명으로 작성했습니다.\n감사합니다.",
    },
}

_XLSX_MAINTYPE = "application"
_XLSX_SUBTYPE = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def send_haedal_order_email(xlsx_bytes: bytes, filename: str) -> dict:
    """발주서 xlsx 1개를 첨부해 발송 (하위호환 래퍼)."""
    return send_order_files_email([(xlsx_bytes, filename)])


def send_order_files_email(attachments: list[tuple[bytes, str]], supplier: str = "haedal") -> dict:
    """발주서 파일(1개 이상)을 첨부해 발송. 결과 dict(sent/to/subject/error) 반환 — 예외를 밖으로 던지지 않는다.

    제목은 기존 수동 발송 관례를 따른다: 'YYMMDD 알제이시스템 발주서'.
    """
    now = datetime.now(KST)
    target = ORDER_EMAIL_TARGETS.get(supplier) or ORDER_EMAIL_TARGETS["haedal"]
    recipient = target["to"]
    subject = target["subject"].format(ymd=now.strftime("%y%m%d"))
    body = target["body"]
    result = {"sent": False, "to": recipient, "subject": subject, "error": None}

    if not attachments:
        result["error"] = "첨부할 발주서 파일이 없습니다."
        return result
    if not GMAIL_APP_PASSWORD:
        result["error"] = "GMAIL_APP_PASSWORD 미설정 — fly secrets set GMAIL_APP_PASSWORD=... 후 재시도"
        logger.warning("발주서 이메일 미발송: %s", result["error"])
        return result

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Shach <{GMAIL_USER}>"
    msg["To"] = recipient
    msg.set_content(body)
    for file_bytes, filename in attachments:
        msg.add_attachment(
            file_bytes,
            maintype=_XLSX_MAINTYPE,
            subtype=_XLSX_SUBTYPE,
            filename=filename,
        )

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        result["sent"] = True
        logger.info(
            "발주서 이메일 발송 완료: %s -> %s (%s)",
            GMAIL_USER, recipient, ", ".join(name for _, name in attachments),
        )
    except smtplib.SMTPAuthenticationError:
        result["error"] = "Gmail 인증 실패 — 앱 비밀번호(GMAIL_APP_PASSWORD)를 확인하세요"
        logger.exception("발주서 이메일 인증 실패")
    except Exception as exc:  # noqa: BLE001 — 발송 실패가 발주 생성 자체를 막으면 안 됨
        result["error"] = str(exc)
        logger.exception("발주서 이메일 발송 실패")
    return result
