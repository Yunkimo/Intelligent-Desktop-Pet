"""语音气泡：圆角矩形 + 小尾巴，支持流式打字机显示与自动收起。"""

from PyQt6.QtCore import QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

_PADDING = 12
_TAIL_H = 8


def wrap_text(text: str, max_width: int, measure) -> list[str]:
    """按字符折行（适配中文无空格）。measure(str)->int 返回像素宽度。

    拆成纯函数便于单元测试。
    """
    lines: list[str] = []
    cur = ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if cur and measure(cur + ch) > max_width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    return lines or [""]


def bubble_placement(
    avatar: QRect,
    screen: QRect,
    bubble_w: int,
    bubble_h: int,
    gap: int,
    above: bool | None = None,
) -> tuple[int, int, bool]:
    """计算气泡贴住形象一侧的屏幕坐标，返回 (x, y, tail_up)。

    规则：形象中心在下半屏时气泡在形象上方（尾巴朝下，False）；在上半屏时翻到
    形象下方（尾巴朝上，True）。above 传 True/False 可强制方位（如输入框展开占用
    形象下方时让气泡让位到上方）。水平锚点取形象靠近屏幕中心的四分之一处，使气泡
    偏向屏幕内侧；最终位置夹在 screen 可用区域内。拆成纯函数便于单元测试。
    """
    if above is None:
        acy = avatar.y() + avatar.height() // 2
        above = acy >= screen.center().y()
    acx = avatar.x() + avatar.width() // 2
    quarter = avatar.width() // 4
    anchor_x = avatar.x() + (3 * quarter if acx < screen.center().x() else quarter)
    x = min(max(anchor_x - bubble_w // 2, screen.left()), screen.right() - bubble_w)
    y = avatar.y() - bubble_h - gap if above else avatar.y() + avatar.height() + gap
    y = min(max(y, screen.top()), screen.bottom() - bubble_h)
    return x, y, not above


def badge_placement(
    anchor: QRect,
    screen: QRect,
    badge_w: int,
    badge_h: int,
    gap: int,
    bubble: QRect | None = None,
) -> tuple[int, int]:
    """计算状态角标的屏幕坐标，返回 (x, y)。

    默认沿用 bubble_placement 的方位规则贴住桌宠窗口；气泡可见时若与角标
    相交，就把角标叠到气泡外侧（气泡在上方则继续往上，在下方则继续往下），
    避免遮住对话文字。屏幕边缘放不下时翻到桌宠另一侧。拆成纯函数便于测试。
    """
    x, y, tail_up = bubble_placement(anchor, screen, badge_w, badge_h, gap)
    if bubble is None or bubble.isEmpty():
        return x, y
    if not QRect(x, y, badge_w, badge_h).intersects(bubble):
        return x, y

    if not tail_up:  # 气泡在桌宠上方：角标叠到气泡上方
        y = bubble.y() - badge_h - gap
    else:  # 气泡在桌宠下方：角标叠到气泡下方
        y = bubble.y() + bubble.height() + gap
    y = min(max(y, screen.top()), screen.bottom() - badge_h)
    if not QRect(x, y, badge_w, badge_h).intersects(bubble):
        return x, y

    # 屏幕边缘空间不足，翻到桌宠另一侧
    x, y, _ = bubble_placement(anchor, screen, badge_w, badge_h, gap, above=tail_up)
    return x, y


class SpeechBubble(QWidget):
    resized = pyqtSignal()
    visibility_changed = pyqtSignal(bool)

    def __init__(self, timeout_ms: int = 8000, max_width: int = 240, parent=None) -> None:
        super().__init__(parent)
        self.timeout_ms = timeout_ms
        self.max_width = max_width
        self._text = ""
        self._tail_up = False

        # 气泡是独立置顶浮层，可随形象在屏幕上的方位自由翻转摆位：
        # 无边框置顶、不抢焦点、不挡鼠标点击。
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        font = QFont()
        font.setPointSize(10)
        self.setFont(font)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def set_text(self, text: str) -> None:
        self._text = text
        self._apply_text()

    def append_chunk(self, chunk: str) -> None:
        self._text += chunk
        self._apply_text()

    def clear(self) -> None:
        self._text = ""
        self.update()

    def set_tail_up(self, up: bool) -> None:
        """翻转尾巴方向：True 朝上（气泡在形象下方时），False 朝下（默认，在形象上方）。"""
        if up == self._tail_up:
            return
        self._tail_up = up
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802
        # 显示时抬到最前，避免被桌宠窗口盖住尾巴
        super().showEvent(event)
        self.raise_()
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def _apply_text(self) -> None:
        self._resize_to_text()
        self.show()
        self.update()
        if self.timeout_ms > 0:
            self._timer.start(self.timeout_ms)

    def _wrap(self) -> list[str]:
        return wrap_text(self._text, self.max_width, self.fontMetrics().horizontalAdvance)

    def _resize_to_text(self) -> None:
        lines = self._wrap()
        fm = self.fontMetrics()
        line_h = fm.lineSpacing()
        text_w = max((fm.horizontalAdvance(line) for line in lines), default=0)
        w = int(min(self.max_width, text_w) + _PADDING * 2)
        h = int(line_h * len(lines) + _PADDING * 2 + _TAIL_H)
        self.resize(w, h)
        self.resized.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        body_h = h - _TAIL_H
        top = _TAIL_H if self._tail_up else 0

        p.setPen(QPen(QColor(0, 0, 0, 60), 1))
        p.setBrush(QColor(255, 255, 255, 238))
        p.drawRoundedRect(QRectF(0, top, w, body_h), 12, 12)

        cx = w / 2
        tail = QPainterPath()
        if self._tail_up:
            tail.moveTo(cx - 8, top)
            tail.lineTo(cx, 0)
            tail.lineTo(cx + 8, top)
        else:
            tail.moveTo(cx - 8, body_h)
            tail.lineTo(cx, h)
            tail.lineTo(cx + 8, body_h)
        tail.closeSubpath()
        p.drawPath(tail)

        p.setPen(QColor(45, 45, 45))
        fm = self.fontMetrics()
        y = top + _PADDING + fm.ascent()
        for line in self._wrap():
            p.drawText(_PADDING, y, line)
            y += fm.lineSpacing()
        p.end()
