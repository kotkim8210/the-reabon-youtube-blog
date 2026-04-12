"""하이라이트 클립 카드 위젯"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..ai.analyzer import Highlight


class ClipCard(QFrame):
    """하이라이트 구간을 표시하는 카드 위젯"""

    checked_changed = pyqtSignal(bool)

    def __init__(self, index: int, highlight: Highlight, parent: QWidget = None):
        super().__init__(parent)
        self.highlight = highlight
        self._setup_ui(index)

    def _setup_ui(self, index: int) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("clipCard")
        self.setStyleSheet("""
            QFrame#clipCard {
                background-color: #2b2b3b;
                border: 1px solid #444466;
                border-radius: 8px;
                padding: 4px;
            }
            QFrame#clipCard:hover {
                border-color: #7777cc;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # 체크박스
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(True)
        self.checkbox.setStyleSheet("QCheckBox::indicator { width: 18px; height: 18px; }")
        self.checkbox.stateChanged.connect(lambda s: self.checked_changed.emit(s == 2))
        layout.addWidget(self.checkbox, 0, Qt.AlignmentFlag.AlignVCenter)

        # 인덱스 뱃지
        badge = QLabel(f"#{index + 1}")
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet("""
            background-color: #5555aa;
            color: white;
            border-radius: 16px;
            font-weight: bold;
            font-size: 12px;
        """)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # 텍스트 영역
        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)

        title_label = QLabel(self.highlight.title)
        title_label.setStyleSheet("color: #ddddff; font-size: 14px; font-weight: bold;")
        text_layout.addWidget(title_label)

        time_label = QLabel(f"⏱  {self.highlight.time_label}  ({self.highlight.duration:.0f}초)")
        time_label.setStyleSheet("color: #aaaacc; font-size: 12px;")
        text_layout.addWidget(time_label)

        reason_label = QLabel(self.highlight.reason)
        reason_label.setStyleSheet("color: #888899; font-size: 11px;")
        reason_label.setWordWrap(True)
        text_layout.addWidget(reason_label)

        layout.addLayout(text_layout, 1)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()
