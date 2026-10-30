"""宠物主窗口：无边框/置顶/透明，组合形象、气泡、输入框，编排聊天与语音。"""

import os
from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMenu, QWidget

from .agent_status import AgentStatusMonitor
from .asr import ASREngine
from .avatar import create_avatar
from .backend_client import BackendClient, WsListener, build_ws_url
from .bubble import SpeechBubble, badge_placement, bubble_placement
from .commands import Command, Submenu, populate_menu
from .config import Settings
from .event_cache import RecentEvents
from .health import HealthMonitor
from .hook_install import (
    claude_code_installed,
    codex_installed,
    ensure_claude_hooks,
    ensure_codex_hooks,
)
from .image_utils import normalize_image
from .input_box import ChatInput
from .llm import LLMClient
from .memory import Memory
from .persona import build_system_prompt
from .providers import create_chat_provider
from .rice_button import RiceButton
from .sfx import AgentSfx
from .status_badge import StatusBadge
from .tools import build_tools
from .tray import TrayIcon
from .tts import TTSEngine
from .usage import UsageStore
from .worker import ASRWorker, ChatWorker, TTSWorker

_GAP = 8
_INPUT_H = 36
_RICE_MARGIN = 4

# 回复里出现这些词，通常表示宠物没听懂 / 需要用户澄清，此时做「疑惑」表情
_DOUBT_KEYWORDS = (
    "不明白",
    "没听懂",
    "没听清",
    "没听明白",
    "没明白",
    "没懂",
    "不太懂",
    "不理解",
    "理解不了",
    "听不懂",
    "再说一遍",
    "再说一次",
    "能再说",
)


def _is_confused_reply(text: str) -> bool:
    """判断回复是否表示「没听懂用户提问」。"""
    return any(k in text for k in _DOUBT_KEYWORDS)


class PetWindow(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

        # —— 引擎 ——
        # 用量记账是旁路：provider 每次调用回来顺手记一笔，失败不影响对话
        self.usage_store = UsageStore(settings.usage_path, settings.usage_retention_days)
        self.llm = LLMClient(create_chat_provider(settings, on_usage=self.usage_store.record_usage))
        self.asr_engine = ASREngine(settings.whisper_model)
        self.tts_engine = TTSEngine(
            settings.tts_voice,
            settings.tts_rate,
            settings.tts_pitch,
            settings.tts_timeout_seconds,
            settings.tts_windows_fallback,
        )

        # —— 后端客户端（惰性：不配置后端也不影响纯聊天）——
        self.backend = BackendClient(settings.backend_url, settings.api_token)
        self.tools = build_tools(self.backend)

        # —— WebSocket 实时接收（未配置 API_TOKEN 时不启动）——
        self._recent_events = RecentEvents()
        self.ws = WsListener(build_ws_url(settings.backend_url, settings.api_token), parent=self)
        self.ws.event.connect(self._on_backend_event)
        self.ws.error.connect(lambda e: print(f"[ws] {e}"))
        if settings.api_token:
            self.ws.start()

        # —— 记忆 ——
        self.memory = Memory(settings.history_path, settings.max_history, settings.persist_history)
        self.memory.set_system(build_system_prompt(settings))

        self._init_window()
        self._init_children()
        self._init_claude_monitor()
        self._size_and_position()
        self._init_audio()
        self._init_hotkey()
        self._init_health()

        # 托盘：左键显隐；关闭窗口时按 tray_enabled 决定隐藏还是真正退出
        self._quitting = False
        self.tray = TrayIcon(self, settings, parent=self) if settings.tray_enabled else None

        # 拖拽/点击状态
        self._press_pos = None
        self._moved = False

        # worker 引用（保持存活，防被 GC）
        self.chat_worker: ChatWorker | None = None
        self.asr_worker: ASRWorker | None = None
        self.tts_worker: TTSWorker | None = None
        self._tts_tmp: str | None = None
        self._tool_status_active = False

    # ---------- 初始化 ----------
    def _init_window(self) -> None:
        self.setWindowTitle(self.settings.pet_name)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 需要无按键的 move 事件，用于在米饭图标上给出可点击光标提示
        self.setMouseTracking(True)

    def _init_children(self) -> None:
        self.avatar = create_avatar(self.settings, parent=self)
        self.bubble = SpeechBubble(self.settings.bubble_timeout_ms, parent=self)
        self.input = ChatInput(parent=self)
        self.input.hide()
        self.rice = RiceButton(self.settings.assets_dir / self.settings.rice_icon, parent=self)

        self.input.submitted.connect(self.send_text)
        self.input.mic_toggled.connect(self.on_mic_toggled)
        self.bubble.resized.connect(self._position_bubble)
        # 气泡显隐/改变大小都会影响角标可用的空间，需重新摆位以免遮挡
        self.bubble.resized.connect(self._position_status_badge)
        self.bubble.visibility_changed.connect(self._position_status_badge)

    def _init_audio(self) -> None:
        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(1.0)
        self.player.mediaStatusChanged.connect(self._on_media_status)

    def _size_and_position(self) -> None:
        sw = self.avatar.widget.width()
        sh = self.avatar.widget.height()
        self.win_w = max(320, sw + 120)
        # 气泡已是独立置顶浮层，窗口只需容纳形象 + 输入框，不再预留气泡空间
        self.win_h = sh + _INPUT_H + _GAP * 2
        self.resize(self.win_w, self.win_h)

        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.win_w - 40, geo.bottom() - self.win_h - 40)

        self._layout_children()

    def _layout_children(self) -> None:
        sw = self.avatar.widget.width()
        sh = self.avatar.widget.height()
        sx = (self.width() - sw) // 2
        sy = self.height() - sh - _INPUT_H - _GAP * 2
        self.avatar.widget.setGeometry(sx, sy, sw, sh)

        ix = (self.width() - self.input.width()) // 2
        iy = sy + sh + _GAP
        self.input.move(ix, iy)

        # 用量入口贴头像右下角内侧；子控件随窗口移动，天然不会与桌宠分离
        rx = sx + sw - self.rice.width() - _RICE_MARGIN
        ry = sy + sh - self.rice.height() - _RICE_MARGIN
        self.rice.move(rx, ry)
        self.rice.raise_()

        self._position_bubble()
        self._position_status_badge()

    def _position_bubble(self) -> None:
        # 气泡随宠物在屏幕上的方位自适应：形象靠下半屏时气泡在形象上方，靠上半屏
        # 时翻到形象下方（尾巴方向随之翻转），水平方向偏向屏幕中心，并夹在可用区域
        # 内。首条文本前气泡仍隐藏，但 move() 对隐藏控件同样生效，故不判断
        # isVisible()，避免首条气泡落在屏幕左上角。
        avatar = self.avatar.widget
        screen = avatar.screen() or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo is None:
            return
        rect = QRect(avatar.mapToGlobal(QPoint(0, 0)), avatar.size())
        # 输入框展开时占住形象下方，气泡强制让位到上方，避免挡住输入栏
        above = True if self.input.isVisible() else None
        x, y, tail_up = bubble_placement(
            rect, geo, self.bubble.width(), self.bubble.height(), _GAP, above
        )
        self.bubble.set_tail_up(tail_up)
        self.bubble.move(x, y)

    # ---------- 拖拽与点击 ----------
    def _hit_avatar(self, pos) -> bool:
        """判断给定窗口坐标是否落在形象区域内，避免透明空白区误触。"""
        return self.avatar.widget.geometry().contains(pos)

    def _hit_rice(self, pos) -> bool:
        """是否落在右下角的用量入口图标上。"""
        return getattr(self, "rice", None) is not None and self.rice.geometry().contains(pos)

    def _hit_drag_area(self, pos) -> bool:
        """可拖拽区域：形象与米饭图标，从图标上按下也能拖动整个桌宠。"""
        return self._hit_avatar(pos) or self._hit_rice(pos)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._hit_drag_area(event.position().toPoint()):
            return
        self._press_pos = event.globalPosition().toPoint()
        self._moved = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.globalPosition().toPoint() - self._press_pos
            if delta.manhattanLength() > 4:
                self._moved = True
                self.move(self.pos() + delta)
                self._press_pos = event.globalPosition().toPoint()
                # 气泡与角标都是独立浮层：拖拽时同步跟随，并保持在桌宠窗口之上
                self._position_bubble()
                self.bubble.raise_()
                self._position_status_badge()
            return
        # 悬停在用量入口上时换成手型，弥补图标接收不到鼠标事件、无法用 tooltip 的不足
        over_rice = self._hit_rice(event.position().toPoint())
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if over_rice else Qt.CursorShape.ArrowCursor
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press_pos is None:
            return
        if not self._moved:
            pos = event.position().toPoint()
            if self._hit_rice(pos):
                self._show_usage_dialog()
            elif self._hit_avatar(pos):
                self.toggle_input()
        self._press_pos = None
        self._moved = False

    def _show_usage_dialog(self) -> None:
        """打开用量窗口；延迟导入避免启动时加载未用到的对话框模块。"""
        from .usage_dialog import UsageDialog

        dialog = getattr(self, "_usage_dialog", None)
        if dialog is not None:
            dialog.close()
        self._usage_dialog = UsageDialog(self.settings, self.usage_store, self)
        self._usage_dialog.llm_config_changed.connect(self._rebuild_llm)
        try:
            self._usage_dialog.exec()
        finally:
            self._usage_dialog = None

    def _rebuild_llm(self) -> None:
        """用户改了推理用的 key 或地址后重建客户端；进行中的对话仍用旧客户端跑完。"""
        self.llm = LLMClient(
            create_chat_provider(self.settings, on_usage=self.usage_store.record_usage)
        )

    def toggle_input(self) -> None:
        if self.input.isVisible():
            self.input.hide()
        else:
            self.input.show()
            self.input.focus_input()
        # 输入框显隐改变形象下方的占用情况，气泡需要重新让位
        self._position_bubble()

    # ---------- 更换形象 / 切换人设 ----------
    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if not self._hit_avatar(event.pos()):
            return
        menu = QMenu(self)
        populate_menu(menu, self._build_commands())
        menu.exec(event.globalPos())

    def _build_commands(
        self, include_hide_to_tray: bool = True, include_quit: bool = True
    ) -> list[Command]:
        """按固定顺序组装命令表；托盘菜单复用同表，但不含「隐藏至托盘」。

        include_quit 为 False 时把「退出」留给调用者追加，供托盘把自启勾选项排在
        它之前、让「退出」始终落在菜单最下方。
        """
        commands: list[Command] = []

        if include_hide_to_tray:
            commands.append(
                Command(
                    "隐藏至托盘",
                    self.hide_to_tray,
                    enabled=lambda: self.settings.tray_enabled,
                )
            )
        commands.append(Command("切换图片…", self._choose_image))
        commands.append(Submenu(self._build_persona_menu()))
        commands.append(Command("设置语音快捷键…", self._set_voice_hotkey))
        commands.append(
            Command(
                "语音输出",
                self._toggle_voice,
                checkable=True,
                checked=lambda: self.settings.enable_voice,
            )
        )
        commands.append(
            Command(
                "监控 Claude",
                self._toggle_claude_monitor,
                checkable=True,
                checked=lambda: self.settings.monitor_claude,
            )
        )
        commands.append(
            Command(
                "监控 Codex",
                self._toggle_codex_monitor,
                checkable=True,
                checked=lambda: self.settings.monitor_codex,
            )
        )
        commands.append(
            Command(
                "显示状态角标",
                self._toggle_status_badges,
                checkable=True,
                checked=lambda: getattr(self, "_status_badges_visible", True),
            )
        )
        commands.append(Command("测试后端连接", self._debug_backend))
        if include_quit:
            commands.append(self._quit_command())
        return commands

    def _quit_command(self) -> Command:
        """「退出」命令：桌宠与托盘共用同一定义，且始终排在菜单最下方。"""
        return Command("退出", self._quit)

    def _build_persona_menu(self) -> QMenu:
        """组装「切换人设」子菜单：逐项包装人设切换调用。"""
        menu = QMenu("切换人设", self)
        commands: list[Command] = []
        for name in self.settings.personas:
            commands.append(Command(name, lambda n=name: self._switch_persona(n)))
        populate_menu(menu, commands)
        menu.addSeparator()
        menu.addAction("添加人设…").triggered.connect(self._add_persona)
        return menu

    def _switch_persona(self, name: str) -> None:
        """切换人设，并清空旧人设对话避免语气/身份残留。"""
        if not self.settings.switch_persona(name):
            return
        self.memory.set_system(build_system_prompt(self.settings))
        self.memory.clear_history()  # 清空旧人设对话，避免语气/身份残留
        self.setWindowTitle(self.settings.pet_name)
        self.bubble.set_text(f"人设已切换为「{name}」")

    def _add_persona(self) -> None:
        name, ok = QInputDialog.getText(self, "添加人设", "人设名字：")
        if not ok or not name.strip():
            return
        personality, ok = QInputDialog.getMultiLineText(self, "添加人设", f"「{name}」的性格描述：")
        if not ok:
            return
        tone, ok = QInputDialog.getMultiLineText(self, "添加人设", f"「{name}」的说话语气：")
        if not ok:
            return
        if self.settings.add_persona(name, personality, tone):
            self._switch_persona(name)

    def _choose_image(self) -> None:
        """弹出图片选择框并更换形象。"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择桌宠形象",
            "",
            "图片 (*.png *.jpg *.jpeg *.gif *.webp *.bmp)",
        )
        if not path:
            return
        self._apply_image(Path(path))

    def _apply_image(self, src: Path) -> None:
        """更换形象：用图片/动图精灵引擎显示所选图片。"""
        # 先释放当前形象对图片文件的占用，避免覆盖正在显示的图片时锁文件崩溃
        self.avatar.clear()
        dest = normalize_image(src, self.settings.assets_dir)
        self.settings.update_frames([dest.name])
        self.avatar.set_appearance(dest, self.settings.sprite_size)
        self._size_and_position()

    # ---------- 文本/聊天 ----------
    def send_text(self, text: str) -> None:
        self.memory.add_user(text)
        self.input.hide()
        self.bubble.clear()
        self._start_chat(self.memory.get_messages())

    def _start_chat(self, messages: list[dict]) -> None:
        if self.chat_worker is not None and self.chat_worker.isRunning():
            return
        self.input.set_busy(True)
        self._tool_status_active = False
        self.chat_worker = ChatWorker(self.llm, messages, tools=self.tools, parent=self)
        self.chat_worker.chunk.connect(self._on_chunk)
        self.chat_worker.status.connect(self._on_tool_status)
        self.chat_worker.done.connect(self._on_chat_done)
        self.chat_worker.error.connect(self._on_chat_error)
        self.chat_worker.start()

    def _on_chunk(self, chunk: str) -> None:
        """收到流式增量；若此前显示过工具状态，先清空再开始打字机。"""
        if self._tool_status_active:
            self.bubble.clear()
            self._tool_status_active = False
        self.bubble.append_chunk(chunk)

    def _on_tool_status(self, text: str) -> None:
        """工具执行中：在气泡显示进行状态（首块回复到达时被替换）。"""
        self._tool_status_active = True
        self.bubble.set_text(text)

    def _on_chat_done(self, text: str) -> None:
        self.input.set_busy(False)
        if text:
            self.memory.add_assistant(text)
            self.memory.save()
            if _is_confused_reply(text):
                self.avatar.react("confused")  # 没听懂用户提问
            if self.settings.enable_voice:
                self._speak(text)
        else:
            # 空回复 = 无法回答，露出「疑惑」（圈圈眼 + 问号）
            self.avatar.react("confused")
            self.bubble.set_text("嗯…这个我答不上来…")

    def _on_chat_error(self, msg: str) -> None:
        self.input.set_busy(False)
        self.avatar.react("confused")
        self.bubble.set_text(f"呜…出错了：{msg}")

    # ---------- 语音合成 ----------
    def _toggle_voice(self) -> None:
        """切换语音输出开关并持久化；关闭时立即停止当前播放。"""
        enabled = not self.settings.enable_voice
        self.settings.update_voice_enabled(enabled)
        if not enabled:
            self._stop_voice()
        self.bubble.set_text("语音输出已开启" if enabled else "语音输出已关闭")

    def _stop_voice(self) -> None:
        """停止当前语音播放并清理临时文件。"""
        self.player.stop()
        self.player.setSource(QUrl())
        self._cleanup_tts_tmp()

    def _speak(self, text: str) -> None:
        if not self.settings.enable_voice:
            return
        self.tts_worker = TTSWorker(self.tts_engine, text, parent=self)
        self.tts_worker.ready.connect(self._play_voice)
        self.tts_worker.error.connect(lambda e: print(f"[TTS] {e}"))
        self.tts_worker.start()

    def _play_voice(self, path: str) -> None:
        if not self.settings.enable_voice:
            # 合成期间被关闭：丢弃已生成的文件，避免继续播放或泄漏临时文件
            try:
                os.remove(path)
            except OSError:
                pass
            return
        self._tts_tmp = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self.avatar.react("speak")

    def _on_media_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setSource(QUrl())
            self._cleanup_tts_tmp()

    def _cleanup_tts_tmp(self) -> None:
        if self._tts_tmp:
            try:
                os.remove(self._tts_tmp)
            except OSError:
                pass
            self._tts_tmp = None

    # ---------- 语音识别 ----------
    def on_mic_toggled(self, listening: bool) -> None:
        if listening:
            self.avatar.react("voice")  # 语音输入时随机换表情
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        if self.asr_worker is not None and self.asr_worker.isRunning():
            return
        self.asr_worker = ASRWorker(self.asr_engine, self.settings.max_record_secs, parent=self)
        self.asr_worker.text.connect(self._on_asr_text)
        self.asr_worker.error.connect(self._on_asr_error)
        self.asr_worker.start()

    def _stop_recording(self) -> None:
        if self.asr_worker is not None and self.asr_worker.isRunning():
            self.asr_worker.request_stop()

    def _on_asr_text(self, text: str) -> None:
        self.input.set_listening(False)
        if text:
            self.input.edit.setText(text)
            self.send_text(text)
        else:
            self.bubble.set_text("没听清，再说一次嘛～")

    def _on_asr_error(self, msg: str) -> None:
        self.input.set_listening(False)
        self.bubble.set_text(f"听不到声音：{msg}")

    # ---------- Claude Code 状态监控 ----------
    def _init_claude_monitor(self) -> None:
        """创建状态角标与监控器；按配置决定是否立即开始轮询。"""
        self.status_badge = StatusBadge(self)
        self.codex_status_badge = StatusBadge(self, agent_name="Codex")
        # 双击角标复位其手动位置，回到自动摆位
        self.status_badge.position_reset.connect(self._position_status_badge)
        self.codex_status_badge.position_reset.connect(self._position_status_badge)
        # 角标显隐是独立于桌宠的用户开关：启动时按配置恢复
        self._status_badges_visible = self.settings.status_badges_visible
        self.status_badge.set_user_visible(self._status_badges_visible)
        self.codex_status_badge.set_user_visible(self._status_badges_visible)
        # 状态音效与角标右键菜单：两者都只依赖窗口，不参与轮询
        self.sfx = AgentSfx(self.settings.assets_dir, parent=self)
        for badge in (self.status_badge, self.codex_status_badge):
            badge.context_menu_requested.connect(self._show_badge_menu)
        self.agent_status = AgentStatusMonitor(self.settings.agent_status_path, parent=self)
        self.agent_status.state_changed.connect(self._on_agent_status)
        codex_status_path = self.settings.agent_status_path.with_name("codex-agent-status.json")
        self.codex_agent_status = AgentStatusMonitor(codex_status_path, parent=self)
        self.codex_agent_status.state_changed.connect(self._on_codex_status)
        if self.settings.monitor_claude:
            self.agent_status.start()
        if self.settings.monitor_codex:
            self.codex_agent_status.start()

    def _monitor_install_failed(self, tool: str, exc: Exception) -> None:
        """钩子安装失败：气泡说明原因（截断超长路径），监控保持关闭。"""
        reason = " ".join(str(exc).split()) or type(exc).__name__
        if len(reason) > 60:
            reason = reason[:57] + "…"
        self.bubble.set_text(f"{tool} 监控开启失败：钩子安装失败（{reason}）")

    def _toggle_claude_monitor(self) -> None:
        """右键菜单开关：开启时先确保状态钩子已写入，再轮询状态文件。"""
        enabled = not self.settings.monitor_claude
        if enabled:
            try:
                added = ensure_claude_hooks()
            except (ImportError, OSError, ValueError) as exc:
                self.settings.update_monitor_claude(False)
                self._monitor_install_failed("Claude Code", exc)
                return
            self.settings.update_monitor_claude(True)
            self.agent_status.start()
            if added:
                if claude_code_installed():
                    self.bubble.set_text("已装好 Claude Code 状态钩子，重启 Claude Code 后生效～")
                else:
                    self.bubble.set_text(
                        "未检测到 Claude Code 安装；钩子已写好，安装后重启即可生效～"
                    )
            else:
                self.bubble.set_text("开始监控 Claude Code 啦～")
            return
        self.settings.update_monitor_claude(False)
        self.agent_status.stop()
        self.status_badge.set_state("idle")
        self.bubble.set_text("已关闭 Claude Code 监控")

    def _on_agent_status(self, state: str) -> None:
        self.status_badge.set_state(state)
        self.sfx.play(state)
        self._position_status_badge()

    def _show_badge_menu(self, global_pos) -> None:
        """角标右键菜单：只放与监控相关的项，末尾仍以「退出」收尾。"""
        menu = QMenu(self)
        populate_menu(menu, self._badge_commands())
        menu.exec(global_pos)

    def _badge_commands(self) -> list[Command]:
        """角标右键的命令表：顺序固定，与桌宠右键菜单共享同一批方法。"""
        return [
            Command(
                "监控 Claude",
                self._toggle_claude_monitor,
                checkable=True,
                checked=lambda: self.settings.monitor_claude,
            ),
            Command(
                "监控 Codex",
                self._toggle_codex_monitor,
                checkable=True,
                checked=lambda: self.settings.monitor_codex,
            ),
            Command(
                "显示状态角标",
                self._toggle_status_badges,
                checkable=True,
                checked=lambda: getattr(self, "_status_badges_visible", True),
            ),
            Command("查看余额", self._show_usage_dialog),
            self._quit_command(),
        ]

    def _toggle_codex_monitor(self) -> None:
        """开关独立的 Codex hook 状态轮询；开启时先确保钩子已写入。"""
        enabled = not self.settings.monitor_codex
        if enabled:
            try:
                added = ensure_codex_hooks()
            except (ImportError, OSError, ValueError) as exc:
                self.settings.update_monitor_codex(False)
                self._monitor_install_failed("Codex", exc)
                self._position_status_badge()
                return
            self.settings.update_monitor_codex(True)
            self.codex_agent_status.start()
            if added:
                if codex_installed():
                    self.bubble.set_text("已写好 Codex 状态钩子，在 Codex 中信任并重启后生效～")
                else:
                    self.bubble.set_text(
                        "未检测到 Codex 安装；钩子已写好，安装后信任并重启即可生效～"
                    )
            else:
                self.bubble.set_text("开始监控 Codex 啦～")
        else:
            self.settings.update_monitor_codex(False)
            self.codex_agent_status.stop()
            self.codex_status_badge.set_state("idle")
            self.bubble.set_text("已关闭 Codex 监控")
        self._position_status_badge()

    def _toggle_status_badges(self) -> None:
        """用户级开关：独立于桌宠与监控，控制两个状态角标是否显示。"""
        enabled = not getattr(self, "_status_badges_visible", True)
        self._status_badges_visible = enabled
        self.settings.update_status_badges_visible(enabled)
        self.status_badge.set_user_visible(enabled)
        self.codex_status_badge.set_user_visible(enabled)
        self._position_status_badge()

    def _on_codex_status(self, state: str) -> None:
        self.codex_status_badge.set_state(state)
        self.sfx.play(state)
        self._position_status_badge()

    def _position_status_badge(self) -> None:
        """角标是独立浮层，复用气泡的屏幕方位规则贴住桌宠窗口。

        窗口在下半屏时角标放上方、上半屏时放下方，水平偏向屏幕中心并夹在可用
        区域内，避免桌宠靠边时角标被遮住或出屏。气泡可见时让角标叠到气泡
        外侧，保证状态文字不遮挡对话内容。
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        if geo is None:
            return
        rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        badges = [
            badge
            for badge in (self.status_badge, self.codex_status_badge)
            if not badge.isHidden() and not badge.is_manually_positioned
        ]
        if not badges:
            return
        total_height = sum(badge.height() for badge in badges) + _GAP * (len(badges) - 1)
        bubble_rect = (
            QRect(self.bubble.pos(), self.bubble.size()) if self.bubble.isVisible() else None
        )
        x, y = badge_placement(
            rect,
            geo,
            max(badge.width() for badge in badges),
            total_height,
            _GAP,
            bubble_rect,
        )
        for badge in badges:
            badge.move(x, y)
            badge.raise_()
            y += badge.height() + _GAP

    # ---------- 全局语音快捷键 ----------
    def _init_hotkey(self) -> None:
        """启动全局语音快捷键（长按说话）；pynput 未安装时优雅降级。"""
        self.hotkey = None
        try:
            from .hotkey import HotkeyManager
        except ImportError:
            print("[hotkey] pynput 未安装，全局语音快捷键不可用")
            return
        self.hotkey = HotkeyManager(self.settings.voice_hotkey, parent=self)
        self.hotkey.pressed.connect(self._on_hotkey_pressed, Qt.ConnectionType.QueuedConnection)
        self.hotkey.released.connect(self._on_hotkey_released, Qt.ConnectionType.QueuedConnection)
        self.hotkey.start()

    def _on_hotkey_pressed(self) -> None:
        """长按快捷键：开始录音。"""
        self.input.set_listening(True)
        self._start_recording()

    def _on_hotkey_released(self) -> None:
        """松开快捷键：停止录音并识别。"""
        self._stop_recording()

    # ---------- 健康关怀 ----------
    def _init_health(self) -> None:
        """启动久坐检测（按 config.json 的 health_enabled 开关）。"""
        self.health = HealthMonitor(self.settings, parent=self)
        self.health.sedentary_due.connect(self._on_sedentary_due)
        self.health.start()

    def _on_sedentary_due(self) -> None:
        self._remind_health("坐太久啦，起来喝口水、活动一下吧～")

    def _remind_health(self, text: str) -> None:
        self.show_hint(text)
        self.avatar.react("poke")
        if self.settings.enable_voice:
            self._speak(text)

    # ---------- 后端实时事件 ----------
    def _on_backend_event(self, event: dict) -> None:
        """验证信封并去重；缓存跟随窗口，断线重连不重复显示或播报。"""
        etype = event.get("type")
        event_id = event.get("event_id")
        data = event.get("data")
        if (
            event.get("version") != 1
            or etype not in {"reminder.due", "task.created", "course.created"}
            or not isinstance(event_id, str)
            or not 1 <= len(event_id) <= 128
            or not isinstance(data, dict)
            or type(data.get("id")) is not int
            or data["id"] <= 0
        ):
            return
        if self._recent_events.contains(event_id):
            return
        if etype == "reminder.due":
            self._remind_health(self._reminder_text(data["id"]))
        elif etype == "task.created":
            self.show_hint("收到新日程啦，需要我帮你看看吗～")
        elif etype == "course.created":
            self.show_hint("课表有更新啦～")
        self._recent_events.remember(event_id)

    def _reminder_text(self, reminder_id) -> str:
        """按事件里的资源 ID 用 REST 校正提醒正文；失败给兜底文案。"""
        try:
            for r in self.backend.list_reminders():
                if r.get("id") == reminder_id:
                    text = f"⏰ {r.get('title') or ''} {r.get('body') or ''}".strip()
                    return text or "有提醒到啦～"
        except Exception:  # noqa: BLE001 - 拉取失败用兜底文案
            pass
        return "有提醒到啦～"

    def _set_voice_hotkey(self) -> None:
        """弹出设置语音快捷键对话框，保存后重启监听。"""
        from .hotkey_dialog import HotkeyDialog

        dialog = HotkeyDialog(self.settings.voice_hotkey, self)
        if not dialog.exec() or not dialog.hotkey:
            return
        if dialog.hotkey == self.settings.voice_hotkey:
            return
        self.settings.update_voice_hotkey(dialog.hotkey)
        self._restart_hotkey()
        self.bubble.set_text(f"语音快捷键已设为「{dialog.hotkey}」♪")

    def _restart_hotkey(self) -> None:
        """停止旧监听并按新快捷键重建。"""
        if self.hotkey is not None:
            self.hotkey.stop()
            self.hotkey.deleteLater()
            self.hotkey = None
        self._init_hotkey()

    # ---------- 其它 ----------
    def showEvent(self, event) -> None:  # noqa: N802
        """窗口显示后校正气泡与角标位置。

        启动时状态文件可能残留非 idle 状态，监控器会在窗口 show() 之前同步
        触发角标显示；而 showEvent 触发时平台窗口也尚未落到最终位置，
        mapToGlobal 仍返回系统默认坐标，顶层浮窗会停在屏幕中心。这里先摆一次，
        再在事件循环处理完显示后延迟校正一次，确保用最终几何定位。
        """
        super().showEvent(event)
        self._reposition_overlays()
        QTimer.singleShot(0, self._reposition_overlays)

    def _reposition_overlays(self) -> None:
        """按窗口当前几何重摆气泡与角标（两者都是独立顶层浮窗）。"""
        self._position_bubble()
        self._position_status_badge()

    def show_hint(self, text: str) -> None:
        self.bubble.set_text(text)

    def _debug_backend(self) -> None:
        """临时调试入口：拉取后端课表/日程，在气泡显示（A1 验收）。"""
        try:
            courses = self.backend.list_courses()
            tasks = self.backend.list_tasks()
        except Exception as exc:  # noqa: BLE001 - 调试入口，直接反馈给用户
            self.show_hint(f"后端不可用：{exc}")
            return
        self.show_hint(f"后端正常～课表 {len(courses)} 条、日程 {len(tasks)} 条")

    def _quit(self) -> None:
        """真正退出：置标志后走 closeEvent 的收尾路径。"""
        self._quitting = True
        self.close()

    def _shutdown_usage(self) -> None:
        """退出时收敛用量窗口与余额线程，避免残留顶层窗口或线程随进程销毁。"""
        dialog = getattr(self, "_usage_dialog", None)
        if dialog is not None:
            # 模态窗口还开着时先关掉，否则嵌套事件循环不会随 closeEvent 结束
            dialog.close()
            dialog.shutdown()

    def hide_to_tray(self) -> None:
        """隐藏桌宠与气泡；状态角标由独立开关控制，不随桌宠隐藏。"""
        if self.isVisible():
            # 记录气泡隐藏前的状态，恢复时不要把原本已收起的气泡强行弹出
            self._bubble_visible_before_tray = self.bubble.isVisible()
        self.bubble.hide()
        self.hide()

    def show_from_tray(self) -> None:
        """从托盘恢复桌宠与气泡；角标按自身状态与用户开关独立显示。"""
        self.show()
        self.raise_()
        if getattr(self, "_bubble_visible_before_tray", False):
            self.bubble.show()
            self.bubble.raise_()
        self._reposition_overlays()

    def toggle_tray_visibility(self) -> None:
        """托盘左键：可见则隐藏，不可见则恢复。"""
        if self.isVisible():
            self.hide_to_tray()
        else:
            self.show_from_tray()

    def closeEvent(self, event) -> None:  # noqa: N802
        # 托盘启用时关闭只是隐藏；只有「退出」命令置 _quitting 后才真正收尾
        if self.settings.tray_enabled and not getattr(self, "_quitting", False):
            self.hide_to_tray()
            event.ignore()
            return
        if self.hotkey is not None:
            self.hotkey.stop()
        self.health.stop()
        self.ws.request_stop()
        self.ws.wait(2000)
        self.agent_status.stop()
        self.codex_agent_status.stop()
        # 角标与气泡是独立顶层浮窗；不关闭的话，桌宠窗口消失后仍有可见顶层
        # 窗口，Qt 不会退出事件循环，启动脚本的控制台也会一直挂着。
        self.status_badge.close()
        self.codex_status_badge.close()
        self.bubble.close()
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        self._shutdown_usage()
        self.memory.save()
        self._cleanup_tts_tmp()
        super().closeEvent(event)
        # 主窗口带 Qt.Tool 标志，不计入 quitOnLastWindowClosed，仅靠关闭窗口
        # 不会结束事件循环；不显式退出的话，启动脚本的控制台会一直挂着。
        app = QApplication.instance()
        if app is not None:
            app.quit()
