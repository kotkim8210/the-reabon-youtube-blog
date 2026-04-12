"""faster-whisper를 사용한 음성 전사 모듈"""

import os
from dataclasses import dataclass
from typing import Callable, Optional

from faster_whisper import WhisperModel


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


def transcribe(
    audio_path: str,
    model_size: str = "base",
    device: str = "cpu",
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[TranscriptSegment]:
    """
    오디오 파일을 전사하여 타임스탬프 포함 세그먼트 목록을 반환.

    Args:
        audio_path: 오디오 파일 경로 (WAV/MP3 등)
        model_size: Whisper 모델 크기 (tiny/base/small/medium/large)
        device: 실행 디바이스 (cpu/cuda)
        progress_callback: (progress_0_to_1, status_text) 형태 콜백

    Returns:
        TranscriptSegment 목록
    """
    if progress_callback:
        progress_callback(0.0, f"Whisper {model_size} 모델 로딩 중...")

    model = WhisperModel(model_size, device=device, compute_type="int8")

    if progress_callback:
        progress_callback(0.1, "음성 전사 중...")

    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=5,
        language=None,  # 자동 감지
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments: list[TranscriptSegment] = []
    total_duration = info.duration if info.duration > 0 else 1.0

    for seg in segments_iter:
        segments.append(TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip()))
        if progress_callback:
            progress = 0.1 + (seg.end / total_duration) * 0.85
            progress_callback(min(progress, 0.95), f"전사 중... {seg.end:.0f}s / {total_duration:.0f}s")

    if progress_callback:
        progress_callback(1.0, f"전사 완료 ({len(segments)}개 세그먼트)")

    return segments


def segments_to_text(segments: list[TranscriptSegment]) -> str:
    """세그먼트 목록을 타임스탬프 포함 텍스트로 변환"""
    lines = []
    for seg in segments:
        start_str = _format_time(seg.start)
        end_str = _format_time(seg.end)
        lines.append(f"[{start_str} --> {end_str}] {seg.text}")
    return "\n".join(lines)


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
