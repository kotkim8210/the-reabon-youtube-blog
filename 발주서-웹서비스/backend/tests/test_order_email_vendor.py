"""발주서 이메일 발송처 분기 (2026-09 비셀러 추가).

고구마(해달)와 비셀러는 수신 메일도 제목의 발주 주체명도 다르다.
발주처 키를 잘못 넘겨도 엉뚱한 거래처로 나가면 안 되므로 기본값(해달)으로 떨어뜨린다.
"""

from app import email_service


def test_default_vendor_is_haedal():
    conf = email_service.vendor_config()
    assert conf["to"] == "farmers2022@naver.com"
    assert conf["company"] == "알제이시스템"


def test_biseller_vendor_routes_to_naeun():
    conf = email_service.vendor_config("biseller")
    assert conf["to"] == "naeun_order@naver.com"
    assert conf["company"] == "아이티소프트"


def test_unknown_vendor_falls_back_to_default():
    assert email_service.vendor_config("없는거래처") == email_service.vendor_config()


def test_subject_and_to_follow_vendor(monkeypatch):
    """GMAIL_APP_PASSWORD 미설정이라 실제 발송은 안 되지만, 수신처·제목은 결정된다."""
    monkeypatch.setattr(email_service, "GMAIL_APP_PASSWORD", "")
    result = email_service.send_order_files_email([(b"x", "a.xlsx")], vendor="biseller")
    assert result["to"] == "naeun_order@naver.com"
    assert result["subject"].endswith("아이티소프트 발주서")
    assert result["sent"] is False   # 비밀번호 미설정 → 발송 안 함(예외도 안 던짐)


def test_empty_attachments_reported_not_raised():
    result = email_service.send_order_files_email([], vendor="biseller")
    assert result["sent"] is False
    assert "없습니다" in result["error"]
