"""宠物形象：加载图片帧做空闲/眨眼动画；支持 GIF/WebP 动图；无素材时画一个占位小猫。"""

from pathlib import Path

from PyQt6.QtCore import QPointF, QSize, Qt, QTimer
from PyQt6.QtGui import QColor, QImageReader, QMovie, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QLabel


class PetSprite(QLabel):
    _ANIMATED_EXTS = {".gif", ".webp"}

    def __init__(
        self,
        assets_dir: Path,
        frame_names: list[str],
        target_size: int,
        interval_ms: int = 450,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.target_size = target_size
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 若 frames 里指定了 GIF/WebP 动图，则用 QMovie 播放
        self._movie: QMovie | None = None
        self._timer: QTimer | None = None
        self.frames: list[QPixmap] = []
        animated = self._find_animated(assets_dir, frame_names)
        if animated is not None:
            self._setup_movie(animated, target_size)
            return

        self.frames: list[QPixmap] = self._load_frames(assets_dir, frame_names, target_size)
        if not self.frames:
            self.frames = [self._placeholder(target_size)]
        self.setFixedSize(self.frames[0].size())

        self._idx = 0
        self.setPixmap(self.frames[0])

        if len(self.frames) > 1:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._advance)
            self._timer.start(interval_ms)

    def clear(self) -> None:
        """停掉动图与帧动画并清空，释放对当前图片文件的占用。"""
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.setMovie(None)
        self.setPixmap(QPixmap())
        self.frames = []
        self._idx = 0

    def set_image(self, path: Path, size: int) -> None:
        """运行时更换形象：动图走 QMovie，静态图走 QPixmap。"""
        self.clear()

        if path.suffix.lower() in self._ANIMATED_EXTS:
            self._setup_movie(path, size)
            return

        self.frames = self._load_frames(path.parent, [path.name], size)
        if not self.frames:
            self.frames = [self._placeholder(size)]
        self.setFixedSize(self.frames[0].size())
        self.setPixmap(self.frames[0])

    @staticmethod
    def _find_animated(assets_dir: Path, names: list[str]) -> Path | None:
        for name in names:
            path = assets_dir / name
            if not path.exists():
                continue
            if (
                Path(name).suffix.lower() in PetSprite._ANIMATED_EXTS
                and QImageReader(str(path)).imageCount() > 1
            ):
                return path
        return None

    def _setup_movie(self, path: Path, size: int) -> None:
        self._movie = QMovie(str(path), parent=self)
        orig = QImageReader(str(path)).size()
        scaled = orig.scaled(QSize(size, size), Qt.AspectRatioMode.KeepAspectRatio)
        self._movie.setScaledSize(scaled)
        self.setFixedSize(scaled)
        self.setMovie(self._movie)
        self._movie.start()

    def _load_frames(self, assets_dir: Path, names: list[str], size: int) -> list[QPixmap]:
        frames: list[QPixmap] = []
        for name in names:
            path = assets_dir / name
            if not path.exists():
                continue
            pm = QPixmap(str(path))
            if pm.isNull():
                continue
            frames.append(
                pm.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        return frames

    def _advance(self) -> None:
        self._idx = (self._idx + 1) % len(self.frames)
        self.setPixmap(self.frames[self._idx])

    @staticmethod
    def _placeholder(size: int) -> QPixmap:
        """画一个简单可爱的占位小猫脸，方便无素材时也能跑起来。"""
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = size
        outline = QPen(QColor(120, 80, 60), max(2, s // 60))
        face = QColor(255, 214, 165)
        ear = QColor(255, 214, 165)
        blush = QColor(255, 160, 160, 200)

        # 耳朵（两个三角形）
        p.setPen(outline)
        p.setBrush(ear)
        left_ear = QPolygonF(
            [
                QPointF(s * 0.22, s * 0.38),
                QPointF(s * 0.14, s * 0.10),
                QPointF(s * 0.40, s * 0.24),
            ]
        )
        right_ear = QPolygonF(
            [
                QPointF(s * 0.78, s * 0.38),
                QPointF(s * 0.86, s * 0.10),
                QPointF(s * 0.60, s * 0.24),
            ]
        )
        p.drawPolygon(left_ear)
        p.drawPolygon(right_ear)

        # 脸（圆）
        p.setPen(outline)
        p.setBrush(face)
        r = s * 0.34
        p.drawEllipse(QPointF(s * 0.5, s * 0.62), r, r)

        # 眼睛
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(70, 50, 45))
        eye_r = s * 0.035
        p.drawEllipse(QPointF(s * 0.38, s * 0.58), eye_r, eye_r)
        p.drawEllipse(QPointF(s * 0.62, s * 0.58), eye_r, eye_r)

        # 腮红
        p.setBrush(blush)
        blush_r = s * 0.06
        p.drawEllipse(QPointF(s * 0.28, s * 0.68), blush_r, blush_r)
        p.drawEllipse(QPointF(s * 0.72, s * 0.68), blush_r, blush_r)

        # 嘴
        p.setPen(outline)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(int(s * 0.42), int(s * 0.64), int(s * 0.16), int(s * 0.10), 200 * 16, 140 * 16)

        p.end()
        return pm
