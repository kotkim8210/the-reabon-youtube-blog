"""QThread 기반 백그라운드 작업 워커"""

import os
import tempfile
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..ai.analyzer import Highlight, analyze_highlights
from ..ai.transcriber import transcribe
from ..video.extractor import extract_audio
from ..video.processor import process_to_shorts


class AnalysisWorker(QThread):
    """
    영상 분석 백그라운드 워커:
    오디오 추출 → Whisper 전사 → Claude 하이라이트 분석
    """

    progress = pyqtSignal(int, str)          # (0~100, 상태 메시지)
    finished = pyqtSignal(list)              # list[Highlight]
    error = pyqtSignal(str)

    def __init__(
        self,
        video_path: str,
        whisper_model: str = "base",
        whisper_device: str = "cpu",
        api_key: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.whisper_model = whisper_model
        self.whisper_device = whisper_device
        self.api_key = api_key
        self._audio_tmp: Optional[str] = None

    def run(self) -> None:
        try:
            # 1. 오디오 추출
            self.progress.emit(2, "오디오 추출 중...")
            fd, audio_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            self._audio_tmp = audio_path
            extract_audio(self.video_path, audio_path)

            # 2. 음성 전사 (0~60%)
            def transcribe_cb(p: float, msg: str) -> None:
                self.progress.emit(int(5 + p * 55), f"[전사] {msg}")

            self.progress.emit(5, "Whisper 모델 로딩 중...")
            segments = transcribe(
                audio_path,
                model_size=self.whisper_model,
                device=self.whisper_device,
                progress_callback=transcribe_cb,
            )

            # 3. AI 분석 (60~100%)
            def analyze_cb(p: float, msg: str) -> None:
                self.progress.emit(int(60 + p * 38), f"[AI 분석] {msg}")

            self.progress.emit(60, "Claude AI 분석 중...")
            highlights = analyze_highlights(
                segments,
                api_key=self.api_key,
                progress_callback=analyze_cb,
            )

            self.progress.emit(100, "분석 완료!")
            self.finished.emit(highlights)

        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if self._audio_tmp and os.path.exists(self._audio_tmp):
                os.remove(self._audio_tmp)
                self._audio_tmp = None


class ExportWorker(QThread):
    """
    쇼츠 내보내기 백그라운드 워커:
    선택된 하이라이트 → 9:16 MP4 파일 일괄 생성
    """

    progress = pyqtSignal(int, str)          # (0~100, 상태 메시지)
    clip_done = pyqtSignal(int, str)         # (index, output_path)
    finished = pyqtSignal(list)              # list[str] 출력 경로
    error = pyqtSignal(str)

    def __init__(
        self,
        video_path: str,
        highlights: list[Highlight],
        output_dir: str,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.highlights = highlights
        self.output_dir = output_dir

    def run(self) -> None:
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            output_paths = []
            total = len(self.highlights)

            for i, hl in enumerate(self.highlights):
                base_name = _safe_filename(hl.title)
                output_path = os.path.join(self.output_dir, f"short_{i + 1:02d}_{base_name}.mp4")

                def clip_cb(p: float, msg: str) -> None:
                    overall = int((i / total + p / total) * 100)
                    self.progress.emit(overall, f"[{i+1}/{total}] {msg}")

                self.progress.emit(int(i / total * 100), f"[{i+1}/{total}] '{hl.title}' 처리 중...")

                process_to_shorts(
                    self.video_path,
                    hl.start,
                    hl.end,
                    output_path,
                    progress_callback=clip_cb,
                )

                output_paths.append(output_path)
                self.clip_done.emit(i, output_path)

            self.progress.emit(100, f"{total}개 쇼츠 생성 완료!")
            self.finished.emit(output_paths)

        except Exception as exc:
            self.error.emit(str(exc))


def _safe_filename(name: str) -> str:
    """파일명으로 사용할 수 없는 문자 제거"""
    invalid = r'\/:*?"<>|'
    for ch in invalid:
        name = name.replace(ch, "_")
    return name[:40].strip()
