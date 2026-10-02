"""해달 발주서 이메일 — 꿀고구마 + 호박고구마 발주파일 2개를 한 메일에 첨부 (2026-10-02 요청).

실제 메일은 보내지 않는다: smtplib.SMTP_SSL을 가짜로 바꿔 만들어진 메시지만 검사한다.
"""

from email import message_from_bytes
from email.policy import default as default_policy

from app import email_service


class _FakeSMTP:
    sent: list = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def login(self, *_args):
        return None

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


def test_two_order_files_go_out_in_one_email(monkeypatch):
    _FakeSMTP.sent = []
    monkeypatch.setattr(email_service, "GMAIL_APP_PASSWORD", "dummy-app-password")
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", _FakeSMTP)

    files = [
        (b"PK-kkul", "해달 발주서 한진양식_알제이시스템즈(261002).xlsx"),
        (b"PK-hobak", "해달 발주서 한진양식_아이티소프트_호박고구마(261002).xlsx"),
    ]
    result = email_service.send_order_files_email(files, "haedal")

    assert result["sent"] is True and result["error"] is None
    assert result["to"] == "farmers2022@naver.com"
    assert len(_FakeSMTP.sent) == 1                      # 메일 1통
    msg = message_from_bytes(_FakeSMTP.sent[0].as_bytes(), policy=default_policy)
    attachments = [(part.get_filename(), part.get_content()) for part in msg.iter_attachments()]
    assert [name for name, _ in attachments] == [name for _, name in files]   # 한글 파일명 그대로, 순서 유지
    assert [body for _, body in attachments] == [data for data, _ in files]
