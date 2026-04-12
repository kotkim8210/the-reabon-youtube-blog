"""9:16 스마트 크롭 및 인코딩 모듈"""

import os
import tempfile
from typing import Callable, Optional

import cv2
import ffmpeg

from .extractor import extract_clip, get_video_info

# 출력 해상도 (YouTube Shorts 표준)
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

_FACE_CASCADE = None


def _get_face_cascade() -> cv2.CascadeClassifier:
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _FACE_CASCADE = cv2.CascadeClassifier(cascade_path)
    return _FACE_CASCADE


def _detect_face_center_x(video_path: str, sample_interval: float = 5.0) -> Optional[float]:
    """
    영상에서 얼굴을 감지하여 중심 x 좌표 비율(0~1)을 반환.
    감지 실패 시 None 반환.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    step = max(1, int(fps * sample_interval))

    face_x_list = []
    cascade = _get_face_cascade()

    frame_idx = 0
    while frame_idx < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        for (x, y, w, h) in faces:
            face_x_list.append((x + w / 2) / width)

        frame_idx += step

    cap.release()

    if not face_x_list:
        return None

    return sum(face_x_list) / len(face_x_list)


def process_to_shorts(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> str:
    """
    영상 구간을 9:16 쇼츠 포맷으로 변환하여 저장.

    1. 구간 추출 (임시 파일)
    2. 얼굴 감지로 크롭 중심 결정
    3. ffmpeg으로 크롭 + 리사이즈 + 인코딩

    Args:
        video_path: 원본 영상 경로
        start: 시작 시간 (초)
        end: 종료 시간 (초)
        output_path: 출력 MP4 경로
        progress_callback: (0~1, 상태 텍스트) 콜백

    Returns:
        output_path
    """
    if progress_callback:
        progress_callback(0.1, "구간 추출 중...")

    fd, clip_path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)

    try:
        extract_clip(video_path, start, end, clip_path)

        if progress_callback:
            progress_callback(0.4, "얼굴 감지 중...")

        info = get_video_info(clip_path)
        src_w = info["width"]
        src_h = info["height"]

        # 9:16 비율로 크롭할 영역 계산
        target_aspect = OUTPUT_WIDTH / OUTPUT_HEIGHT  # 9/16
        crop_w = int(src_h * target_aspect)
        crop_h = src_h

        if crop_w > src_w:
            # 세로가 너무 길면 가로 기준으로 크롭
            crop_w = src_w
            crop_h = int(src_w / target_aspect)

        # 얼굴 감지로 x 중심 결정
        face_cx_ratio = _detect_face_center_x(clip_path)
        if face_cx_ratio is not None:
            cx = int(face_cx_ratio * src_w)
        else:
            cx = src_w // 2  # 중앙 크롭

        # 크롭 좌표 계산 (경계 클램핑)
        x = max(0, min(cx - crop_w // 2, src_w - crop_w))
        y = max(0, (src_h - crop_h) // 2)

        if progress_callback:
            progress_callback(0.6, "9:16 변환 및 인코딩 중...")

        vf = f"crop={crop_w}:{crop_h}:{x}:{y},scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"

        (
            ffmpeg
            .input(clip_path)
            .output(
                output_path,
                vf=vf,
                vcodec="libx264",
                acodec="aac",
                crf=23,
                preset="fast",
                movflags="+faststart",
            )
            .overwrite_output()
            .run(quiet=True)
        )

        if progress_callback:
            progress_callback(1.0, "완료")

    finally:
        if os.path.exists(clip_path):
            os.remove(clip_path)

    return output_path
