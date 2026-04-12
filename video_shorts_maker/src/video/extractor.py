"""ffmpeg-python을 사용한 영상 오디오 추출 및 클립 추출 모듈"""

import os
import tempfile
from typing import Optional

import ffmpeg


def extract_audio(video_path: str, output_path: Optional[str] = None) -> str:
    """
    영상에서 오디오를 WAV로 추출.

    Args:
        video_path: 원본 영상 파일 경로
        output_path: 출력 오디오 경로 (None이면 임시 파일 생성)

    Returns:
        추출된 오디오 파일 경로
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

    (
        ffmpeg
        .input(video_path)
        .output(
            output_path,
            acodec="pcm_s16le",
            ac=1,
            ar="16000",
            vn=None,
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def extract_clip(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
) -> str:
    """
    영상에서 특정 구간을 클립으로 추출 (재인코딩 없이 빠른 추출).

    Args:
        video_path: 원본 영상 파일 경로
        start: 시작 시간 (초)
        end: 종료 시간 (초)
        output_path: 출력 클립 경로

    Returns:
        output_path
    """
    duration = end - start
    (
        ffmpeg
        .input(video_path, ss=start, t=duration)
        .output(
            output_path,
            vcodec="copy",
            acodec="copy",
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def get_video_info(video_path: str) -> dict:
    """영상의 width, height, duration 정보 반환"""
    probe = ffmpeg.probe(video_path)
    video_stream = next(
        (s for s in probe["streams"] if s["codec_type"] == "video"),
        None,
    )
    if not video_stream:
        raise ValueError(f"영상 스트림을 찾을 수 없습니다: {video_path}")

    duration = float(probe["format"].get("duration", 0))
    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "duration": duration,
    }
