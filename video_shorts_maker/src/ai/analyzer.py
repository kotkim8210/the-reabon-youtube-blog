"""Claude API를 사용한 하이라이트 구간 분석 모듈"""

import json
import os
from dataclasses import dataclass
from typing import Callable, Optional

import anthropic

from .transcriber import TranscriptSegment, segments_to_text


@dataclass
class Highlight:
    start: float
    end: float
    title: str
    reason: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def time_label(self) -> str:
        def fmt(s: float) -> str:
            m, sec = divmod(int(s), 60)
            return f"{m:02d}:{sec:02d}"
        return f"{fmt(self.start)} ~ {fmt(self.end)}"


_SYSTEM_PROMPT = """당신은 영상 편집 전문가입니다. 주어진 영상 스크립트를 분석하여 쇼츠(Shorts) 영상으로 만들기 적합한 하이라이트 구간을 선별합니다.

선별 기준:
- 30초 ~ 90초 길이의 독립적으로 이해 가능한 구간
- 감정적으로 흥미롭거나, 핵심 정보가 담겨있거나, 웃음/놀라움/감동을 주는 구간
- 문장이 중간에 잘리지 않도록 자연스러운 시작/끝 지점

반드시 다음 JSON 배열 형식으로만 응답하세요 (다른 텍스트 없이):
[
  {
    "start": 시작시간(초, 숫자),
    "end": 종료시간(초, 숫자),
    "title": "구간 제목 (한국어, 20자 이내)",
    "reason": "선정 이유 (한국어, 50자 이내)"
  }
]

최소 2개, 최대 8개 구간을 반환하세요."""


def analyze_highlights(
    segments: list[TranscriptSegment],
    api_key: Optional[str] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[Highlight]:
    """
    전사 세그먼트를 Claude API로 분석하여 하이라이트 목록 반환.

    Args:
        segments: TranscriptSegment 목록
        api_key: Anthropic API 키 (None이면 환경변수 사용)
        progress_callback: (progress_0_to_1, status_text) 콜백

    Returns:
        Highlight 목록
    """
    if progress_callback:
        progress_callback(0.0, "Claude AI로 하이라이트 분석 중...")

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

    client = anthropic.Anthropic(api_key=key)
    transcript_text = segments_to_text(segments)

    total_duration = segments[-1].end if segments else 0
    user_message = (
        f"다음은 총 {total_duration:.0f}초 영상의 전사 스크립트입니다. "
        f"쇼츠로 만들기 좋은 하이라이트 구간을 선별해주세요.\n\n{transcript_text}"
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    if progress_callback:
        progress_callback(0.8, "AI 응답 파싱 중...")

    raw = message.content[0].text.strip()

    # JSON 블록 추출 (```json ... ``` 형식 처리)
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1])

    data = json.loads(raw)
    highlights = []
    for item in data:
        highlights.append(
            Highlight(
                start=float(item["start"]),
                end=float(item["end"]),
                title=item.get("title", "하이라이트"),
                reason=item.get("reason", ""),
            )
        )

    if progress_callback:
        progress_callback(1.0, f"분석 완료 ({len(highlights)}개 하이라이트 발견)")

    return highlights
