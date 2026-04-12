"""메인 윈도우 UI"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..ai.analyzer import Highlight
from .clip_card import ClipCard
from .worker import AnalysisWorker, ExportWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 쇼츠 메이커")
        self.setMinimumSize(780, 700)
        self.resize(900, 750)

        self._video_path: str = ""
        self._highlights: list[Highlight] = []
        self._cards: list[ClipCard] = []
        self._analysis_worker: AnalysisWorker | None = None
        self._export_worker: ExportWorker | None = None

        self._apply_dark_theme()
        self._build_ui()

    # ──────────────────────────────────────────
    # UI 구성
    # ──────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        # ── 헤더 ──
        header = QLabel("🎬  AI 쇼츠 메이커")
        header.setFont(QFont("", 20, QFont.Weight.Bold))
        header.setStyleSheet("color: #aaaaff;")
        root.addWidget(header)

        subtitle = QLabel("긴 영상에서 AI가 하이라이트를 자동으로 찾아 9:16 쇼츠로 만들어드립니다")
        subtitle.setStyleSheet("color: #777799; font-size: 12px;")
        root.addWidget(subtitle)

        root.addWidget(self._make_separator())

        # ── API 키 입력 ──
        api_layout = QHBoxLayout()
        api_label = QLabel("Anthropic API Key:")
        api_label.setStyleSheet("color: #aaaacc; min-width: 130px;")
        api_layout.addWidget(api_label)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("sk-ant-... (없으면 .env 파일 사용)")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setStyleSheet(self._input_style())
        env_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if env_key:
            self.api_key_input.setText(env_key)
            self.api_key_input.setPlaceholderText(".env 파일에서 불러옴")
        api_layout.addWidget(self.api_key_input)
        root.addLayout(api_layout)

        # ── 영상 파일 선택 ──
        file_layout = QHBoxLayout()
        self.file_label = QLineEdit()
        self.file_label.setReadOnly(True)
        self.file_label.setPlaceholderText("영상 파일을 선택하세요...")
        self.file_label.setStyleSheet(self._input_style())
        file_layout.addWidget(self.file_label)

        browse_btn = QPushButton("파일 선택")
        browse_btn.setFixedWidth(90)
        browse_btn.setStyleSheet(self._btn_style("#4455aa"))
        browse_btn.clicked.connect(self._browse_file)
        file_layout.addWidget(browse_btn)
        root.addLayout(file_layout)

        # ── 분석 버튼 ──
        self.analyze_btn = QPushButton("AI로 하이라이트 분석 시작")
        self.analyze_btn.setFixedHeight(42)
        self.analyze_btn.setFont(QFont("", 13, QFont.Weight.Bold))
        self.analyze_btn.setStyleSheet(self._btn_style("#5566cc"))
        self.analyze_btn.clicked.connect(self._start_analysis)
        self.analyze_btn.setEnabled(False)
        root.addWidget(self.analyze_btn)

        # ── 진행 상태 ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(22)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border-radius: 11px; background: #222233; color: white; text-align: center; }
            QProgressBar::chunk { background: #5566cc; border-radius: 11px; }
        """)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #8888bb; font-size: 11px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status_label)

        root.addWidget(self._make_separator())

        # ── 하이라이트 카드 스크롤 영역 ──
        self.cards_label = QLabel("하이라이트 구간")
        self.cards_label.setFont(QFont("", 13, QFont.Weight.Bold))
        self.cards_label.setStyleSheet("color: #ccccee;")
        self.cards_label.setVisible(False)
        root.addWidget(self.cards_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setSpacing(8)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.addStretch()

        scroll.setWidget(self.cards_container)
        root.addWidget(scroll, 1)

        # ── 출력 폴더 + 내보내기 버튼 ──
        export_layout = QHBoxLayout()

        out_label = QLabel("저장 폴더:")
        out_label.setStyleSheet("color: #aaaacc; min-width: 70px;")
        export_layout.addWidget(out_label)

        self.output_dir_input = QLineEdit(os.path.join(os.path.expanduser("~"), "video_shorts_maker", "output"))
        self.output_dir_input.setStyleSheet(self._input_style())
        export_layout.addWidget(self.output_dir_input)

        out_browse = QPushButton("...")
        out_browse.setFixedWidth(36)
        out_browse.setStyleSheet(self._btn_style("#444466"))
        out_browse.clicked.connect(self._browse_output_dir)
        export_layout.addWidget(out_browse)

        self.export_btn = QPushButton("쇼츠 생성")
        self.export_btn.setFixedWidth(110)
        self.export_btn.setFixedHeight(36)
        self.export_btn.setFont(QFont("", 12, QFont.Weight.Bold))
        self.export_btn.setStyleSheet(self._btn_style("#336633"))
        self.export_btn.clicked.connect(self._start_export)
        self.export_btn.setEnabled(False)
        export_layout.addWidget(self.export_btn)

        root.addLayout(export_layout)

    # ──────────────────────────────────────────
    # 슬롯
    # ──────────────────────────────────────────

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "영상 파일 선택",
            os.path.expanduser("~"),
            "영상 파일 (*.mp4 *.mkv *.avi *.mov *.webm *.flv);;모든 파일 (*)",
        )
        if path:
            self._video_path = path
            self.file_label.setText(path)
            self.analyze_btn.setEnabled(True)
            self._clear_cards()

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", self.output_dir_input.text())
        if path:
            self.output_dir_input.setText(path)

    def _start_analysis(self) -> None:
        if not self._video_path:
            return

        api_key = self.api_key_input.text().strip() or None

        self._clear_cards()
        self._set_busy(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("분석 준비 중...")

        self._analysis_worker = AnalysisWorker(
            video_path=self._video_path,
            whisper_model=os.environ.get("WHISPER_MODEL", "base"),
            whisper_device=os.environ.get("WHISPER_DEVICE", "cpu"),
            api_key=api_key,
        )
        self._analysis_worker.progress.connect(self._on_analysis_progress)
        self._analysis_worker.finished.connect(self._on_analysis_finished)
        self._analysis_worker.error.connect(self._on_error)
        self._analysis_worker.start()

    def _on_analysis_progress(self, value: int, msg: str) -> None:
        self.progress_bar.setValue(value)
        self.status_label.setText(msg)

    def _on_analysis_finished(self, highlights: list) -> None:
        self._highlights = highlights
        self._set_busy(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"{len(highlights)}개 하이라이트를 발견했습니다. 원하는 구간을 선택 후 '쇼츠 생성'을 클릭하세요.")

        self._clear_cards()
        self.cards_label.setVisible(True)

        for i, hl in enumerate(highlights):
            card = ClipCard(i, hl, self.cards_container)
            self._cards.append(card)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

        self.export_btn.setEnabled(True)

    def _start_export(self) -> None:
        selected = [hl for card, hl in zip(self._cards, self._highlights) if card.is_checked()]
        if not selected:
            QMessageBox.warning(self, "선택 없음", "내보낼 클립을 하나 이상 선택하세요.")
            return

        output_dir = self.output_dir_input.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "폴더 없음", "저장 폴더를 지정하세요.")
            return

        self._set_busy(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.status_label.setText("쇼츠 생성 중...")

        self._export_worker = ExportWorker(
            video_path=self._video_path,
            highlights=selected,
            output_dir=output_dir,
        )
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_finished)
        self._export_worker.error.connect(self._on_error)
        self._export_worker.start()

    def _on_export_progress(self, value: int, msg: str) -> None:
        self.progress_bar.setValue(value)
        self.status_label.setText(msg)

    def _on_export_finished(self, paths: list) -> None:
        self._set_busy(False)
        self.progress_bar.setVisible(False)
        output_dir = self.output_dir_input.text()
        self.status_label.setText(f"완료! {len(paths)}개 파일 저장됨 → {output_dir}")
        QMessageBox.information(
            self,
            "완료",
            f"{len(paths)}개의 쇼츠 영상이 생성되었습니다.\n\n저장 위치:\n{output_dir}",
        )

    def _on_error(self, msg: str) -> None:
        self._set_busy(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"오류: {msg}")
        QMessageBox.critical(self, "오류 발생", msg)

    # ──────────────────────────────────────────
    # 헬퍼
    # ──────────────────────────────────────────

    def _clear_cards(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._highlights.clear()
        self.cards_label.setVisible(False)
        self.export_btn.setEnabled(False)

    def _set_busy(self, busy: bool) -> None:
        self.analyze_btn.setEnabled(not busy)
        self.export_btn.setEnabled(not busy and bool(self._cards))

    def _make_separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #444455;")
        return line

    def _input_style(self) -> str:
        return (
            "QLineEdit { background: #1e1e2e; border: 1px solid #444466; border-radius: 6px; "
            "padding: 6px 10px; color: #ccccee; font-size: 13px; }"
            "QLineEdit:focus { border-color: #7777cc; }"
        )

    def _btn_style(self, color: str) -> str:
        return (
            f"QPushButton {{ background: {color}; color: white; border: none; border-radius: 6px; padding: 7px 14px; }}"
            f"QPushButton:hover {{ background: {color}dd; }}"
            f"QPushButton:disabled {{ background: #333344; color: #666677; }}"
        )

    def _apply_dark_theme(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #13131f;
                color: #ccccee;
                font-family: "Segoe UI", "Malgun Gothic", sans-serif;
                font-size: 13px;
            }
            QScrollBar:vertical {
                background: #1e1e2e; width: 8px; border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background: #444466; border-radius: 4px;
            }
        """)
