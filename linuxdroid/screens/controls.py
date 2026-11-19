"""Editor visual de controles com exportação de perfis compatíveis com Phantom."""
from __future__ import annotations

import json
import re
import math
import shutil
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF, QByteArray, QMimeData
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QPixmap, QDrag
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QDoubleSpinBox,
    QVBoxLayout, QWidget, QSplitter, QGroupBox, QCheckBox, QScrollArea, QFrame,
)

from .. import storage
from ..controls.model import POSITION_FIELDS, ControlProfileV2, ProfileError
from ..input import BindingEditor
from ..input.editor_model import binding_from_text
from ..input.profile_bridge import (
    legacy_payload_to_profile,
    normalize_legacy_slots,
    validate_editor_payload,
)
from ..input.qt_bridge import (
    binding_from_qt_key,
    binding_from_qt_mouse,
    canonical_for_qt_key,
)
from ..models import GameEntry
from ..services.phantom_service import PhantomService
from ..widgets.common import label, panel, title_row

NODE_MIME = "application/x-linuxdroid-node-id"

NODE_LABELS = {
    "tap": "Ponto de toque",
    "toggle_tap": "Toque alternado",
    "joystick": "D-pad / joystick",
    "drag": "Arrastar / deslizar",
    "aim": "Mira, pan e tiro",
    "repeat_tap": "Toque repetido",
    "wheel": "Rolagem / zoom",
    "macro": "Macro / combo",
    "layer_shift": "Troca de camada",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower() or "game"


def _node_pos(node: dict) -> dict:
    if node.get("type") == "macro":
        sequence = node.get("sequence", [])
        if sequence and isinstance(sequence[0], dict):
            return sequence[0].get("pos", {"x": 0.5, "y": 0.5})
    return (node.get("pos") or node.get("anchor") or node.get("start")
            or node.get("up_pos") or {"x": 0.5, "y": 0.5})


def _binding_from_qt_event(event) -> object:
    """Identidade local a partir de codigos Qt, nunca de texto digitado."""
    canonical = canonical_for_qt_key(event.key(), event.nativeVirtualKey())
    flags = (
        (Qt.KeyboardModifier.ShiftModifier, "LeftShift"),
        (Qt.KeyboardModifier.ControlModifier, "LeftCtrl"),
        (Qt.KeyboardModifier.AltModifier, "LeftAlt"),
        (Qt.KeyboardModifier.MetaModifier, "LeftMeta"),
    )
    # O modificador que e a propria tecla nao entra como modificador duplicado.
    modifiers = [
        name for flag, name in flags
        if event.modifiers() & flag and name != canonical
    ]
    return binding_from_qt_key(
        event.key(),
        native_scan_code=event.nativeScanCode(),
        native_virtual_key=event.nativeVirtualKey(),
        modifiers=modifiers,
    )


class MappingCanvas(QWidget):
    """Área 16:9 para posicionar e mover os pontos de toque do perfil."""
    selection_changed = Signal(int)
    position_changed = Signal(int)
    add_point = Signal(float, float)
    node_dropped = Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes: list[dict] = []
        self.selected = -1
        self.add_mode = False
        self.dragging = False
        self.active_handle = "start"
        self.background = QPixmap()
        self.screen_width = 1280
        self.screen_height = 720
        self.setMinimumSize(460, 260)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAcceptDrops(True)

    def set_nodes(self, nodes: list[dict]):
        self.nodes = nodes
        self.update()

    def set_background(self, path: str = ""):
        self.background = QPixmap(path) if path else QPixmap()
        self.update()

    def set_screen_size(self, width: int, height: int):
        self.screen_width = max(1, int(width))
        self.screen_height = max(1, int(height))
        self.update()

    def _screen_rect(self):
        margin = 18
        available = self.rect().adjusted(margin, margin, -margin, -margin)
        target_ratio = self.screen_width / max(1, self.screen_height)
        w, h = available.width(), available.height()
        if w / max(1, h) > target_ratio:
            w = int(h * target_ratio)
        else:
            h = int(w / target_ratio)
        return available.x() + (available.width() - w) // 2, available.y() + (available.height() - h) // 2, w, h

    def _to_pixel(self, pos):
        x, y, w, h = self._screen_rect()
        return QPointF(x + float(pos.get("x", 0.5)) * w, y + float(pos.get("y", 0.5)) * h)

    def _to_relative(self, point):
        x, y, w, h = self._screen_rect()
        return max(0.0, min(1.0, (point.x() - x) / max(1, w))), max(0.0, min(1.0, (point.y() - y) / max(1, h)))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b0e16"))
        x, y, w, h = self._screen_rect()
        painter.setPen(QPen(QColor("#45405e"), 1.5))
        painter.setBrush(QBrush(QColor("#141a29")))
        painter.drawRoundedRect(x, y, w, h, 13, 13)
        if not self.background.isNull():
            painter.save()
            painter.setClipRect(x + 1, y + 1, max(1, w - 2), max(1, h - 2))
            painter.drawPixmap(x, y, w, h, self.background)
            painter.fillRect(x, y, w, h, QColor(5, 7, 14, 42))
            painter.restore()
        # Grade discreta para orientar o posicionamento.
        painter.setPen(QPen(QColor(130, 140, 170, 35), 1, Qt.PenStyle.DashLine))
        for fraction in (0.25, 0.5, 0.75):
            gx, gy = x + int(w * fraction), y + int(h * fraction)
            painter.drawLine(gx, y + 8, gx, y + h - 8)
            painter.drawLine(x + 8, gy, x + w - 8, gy)
        painter.setPen(QPen(QColor("#7c8298"), 1))
        painter.setFont(QFont("Inter", 8))
        painter.drawText(x + 10, y + 18, f"TELA ANDROID • {self.screen_width} × {self.screen_height}")
        layer_nodes = [node for node in self.nodes if node.get("type") == "layer_shift"]
        if layer_nodes:
            layer_text = "  |  ".join(f"{node.get('key', '?')} → {node.get('layer_name', 'combat')}" for node in layer_nodes)
            painter.setPen(QPen(QColor("#f4b942"), 1))
            painter.drawText(x + 160, y + 18, f"CAMADAS: {layer_text}")
        for index, node in enumerate(self.nodes):
            if node.get("type") == "layer_shift":
                continue
            pos = _node_pos(node)
            point = self._to_pixel(pos)
            selected = index == self.selected
            color = QColor("#b18cff" if selected else "#63d5ff")
            if node.get("type") == "joystick":
                radius = max(20, int(float(node.get("radius", 0.07)) * w))
                painter.setPen(QPen(color, 2))
                painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 35)))
                painter.drawEllipse(point, radius, radius)
                # Quatro direções do D-pad/joystick.
                painter.setPen(QPen(color, 2))
                painter.drawLine(point.x(), point.y() - radius + 8, point.x(), point.y() - 14)
                painter.drawLine(point.x(), point.y() + radius - 8, point.x(), point.y() + 14)
                painter.drawLine(point.x() - radius + 8, point.y(), point.x() - 14, point.y())
                painter.drawLine(point.x() + radius - 8, point.y(), point.x() + 14, point.y())
            elif node.get("type") == "drag":
                end = self._to_pixel(node.get("end", {"x": min(1.0, pos.get("x", .5) + .18), "y": pos.get("y", .5)}))
                painter.setPen(QPen(QColor("#f4b942"), 3))
                painter.drawLine(point, end)
                angle = math.atan2(end.y() - point.y(), end.x() - point.x())
                arrow_len = 12
                left = QPointF(end.x() - arrow_len * math.cos(angle - math.pi / 6), end.y() - arrow_len * math.sin(angle - math.pi / 6))
                right = QPointF(end.x() - arrow_len * math.cos(angle + math.pi / 6), end.y() - arrow_len * math.sin(angle + math.pi / 6))
                painter.drawLine(end, left)
                painter.drawLine(end, right)
                painter.setBrush(QBrush(QColor("#f4b942")))
                painter.drawEllipse(end, 10, 10)
                painter.setPen(QPen(QColor("#16120a"), 1))
                painter.setFont(QFont("Inter", 7, QFont.Weight.Bold))
                painter.drawText(int(end.x()) - 4, int(end.y()) + 3, "F")
            elif node.get("type") == "aim":
                painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                painter.drawEllipse(point, 28, 28)
            else:
                painter.setPen(QPen(color, 2))
                painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 70)))
                painter.drawEllipse(point, 17, 17)
            painter.setPen(QPen(QColor("#10121a"), 1))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(int(point.x()) - 13, int(point.y()) - 12, 26, 23, 7, 7)
            key = node.get("key") or ("WASD" if node.get("type") == "joystick" else "MOUSE")
            painter.setPen(QPen(QColor("#11131b")))
            painter.setFont(QFont("Inter", 7, QFont.Weight.Bold))
            painter.drawText(int(point.x()) - 12, int(point.y()) + 4, key[:5])
            if node.get("type") == "wheel":
                down = self._to_pixel(node.get("down_pos", {"x": pos.get("x", .5), "y": min(.95, pos.get("y", .5) + .15)}))
                painter.setPen(QPen(QColor("#0b0e16"), 1))
                painter.setBrush(QBrush(QColor("#f4b942")))
                painter.drawEllipse(down, 12, 12)
                painter.setPen(QPen(QColor("#11131b")))
                painter.drawText(int(down.x()) - 4, int(down.y()) + 4, "↓")
        painter.end()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(NODE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(NODE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        raw = event.mimeData().data(NODE_MIME).data()
        if not raw:
            event.ignore()
            return
        node_id = bytes(raw).decode("utf-8", errors="replace")
        rx, ry = self._to_relative(event.position())
        self.node_dropped.emit(node_id, rx, ry)
        event.acceptProposedAction()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.add_mode:
            rx, ry = self._to_relative(event.position())
            self.add_point.emit(rx, ry)
            self.add_mode = False
            self.unsetCursor()
            return
        point = event.position()
        nearest, distance, handle = -1, 30, "start"
        for index, node in enumerate(self.nodes):
            if node.get("type") == "layer_shift":
                continue
            candidates = [(self._to_pixel(_node_pos(node)), "start")]
            if node.get("type") == "drag":
                candidates.append((self._to_pixel(node.get("end", {"x": .5, "y": .5})), "end"))
            elif node.get("type") == "wheel":
                candidates.append((self._to_pixel(node.get("down_pos", {"x": .5, "y": .65})), "down"))
            for candidate, candidate_handle in candidates:
                d = ((candidate.x() - point.x()) ** 2 + (candidate.y() - point.y()) ** 2) ** 0.5
                if d < distance:
                    nearest, distance, handle = index, d, candidate_handle
        self.selected = nearest
        self.active_handle = handle
        self.selection_changed.emit(nearest)
        self.dragging = nearest >= 0
        self.update()

    def mouseMoveEvent(self, event):
        if self.dragging and self.selected >= 0 and event.buttons() & Qt.MouseButton.LeftButton:
            rx, ry = self._to_relative(event.position())
            node = self.nodes[self.selected]
            kind = node.get("type")
            if kind == "aim":
                key = "anchor"
            elif kind == "drag":
                node.setdefault("start", {"x": rx, "y": ry})
                node.setdefault("end", {"x": min(1.0, rx + .18), "y": ry})
                if self.active_handle == "end":
                    node["end"] = {"x": round(rx, 4), "y": round(ry, 4)}
                else:
                    old_start = node["start"]
                    old_end = node["end"]
                    dx = rx - float(old_start.get("x", rx))
                    dy = ry - float(old_start.get("y", ry))
                    node["start"] = {"x": round(rx, 4), "y": round(ry, 4)}
                    node["end"] = {"x": round(max(0.0, min(1.0, float(old_end.get("x", rx)) + dx)), 4),
                                   "y": round(max(0.0, min(1.0, float(old_end.get("y", ry)) + dy)), 4)}
                key = None
            elif kind == "macro":
                sequence = node.setdefault("sequence", [])
                if not sequence:
                    sequence.extend([{"action": "down", "slot": 0, "pos": {}}, {"action": "up", "slot": 0, "delay_ms": 60}])
                sequence[0].setdefault("pos", {})["x"] = round(rx, 4)
                sequence[0]["pos"]["y"] = round(ry, 4)
                key = None
            elif kind == "wheel":
                if self.active_handle == "down":
                    node["down_pos"] = {"x": round(rx, 4), "y": round(ry, 4)}
                else:
                    old = node.get("up_pos", {"x": rx, "y": ry})
                    dx, dy = rx - float(old.get("x", rx)), ry - float(old.get("y", ry))
                    node["up_pos"] = {"x": round(rx, 4), "y": round(ry, 4)}
                    down = node.setdefault("down_pos", {"x": rx, "y": min(1.0, ry + .15)})
                    down["x"] = round(max(0.0, min(1.0, float(down.get("x", rx)) + dx)), 4)
                    down["y"] = round(max(0.0, min(1.0, float(down.get("y", ry)) + dy)), 4)
                key = None
            else:
                key = "pos"
            if key:
                node.setdefault(key, {})["x"] = round(rx, 4)
                node.setdefault(key, {})["y"] = round(ry, 4)
            self.position_changed.emit(self.selected)
            self.update()

    def mouseReleaseEvent(self, _event):
        self.dragging = False

    def set_add_mode(self, active: bool):
        self.add_mode = active
        self.setCursor(Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor)


class MappingListWidget(QListWidget):
    """Lista que arrasta o identificador estavel do controle para o canvas."""

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item is None:
            return
        node_id = item.data(Qt.ItemDataRole.UserRole)
        if not node_id:
            return
        mime = QMimeData()
        mime.setData(NODE_MIME, QByteArray(str(node_id).encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions)


class KeyCaptureEdit(QLineEdit):
    """Captura local de teclado sem usar texto digitado como identidade."""
    captured = Signal(str)
    binding_captured = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Clique e pressione uma tecla")
        self.setReadOnly(False)

    def keyPressEvent(self, event):
        binding = _binding_from_qt_event(event)
        canonical = getattr(binding, "canonical_name", "")
        if canonical:
            self.setText(canonical)
            self.captured.emit(canonical)
            self.binding_captured.emit(binding)
        event.accept()


class ControlsScreen(QWidget):
    """Editor de perfis por jogo, com exportação Phantom e controle opcional do daemon."""
    def __init__(self, games: list[GameEntry]):
        super().__init__()
        self.games = games
        self.nodes: list[dict] = []
        self.selected_index = -1
        self.editor: BindingEditor | None = None
        self._captured_text: dict[tuple[str, str], str] = {}
        self._captured_bindings: dict[tuple[str, str], object] = {}
        self._pending_binding: tuple[str, object] | None = None
        self._redo_selection_id: str = ""
        self.phantom = PhantomService(self)
        self.phantom.log_line.connect(self._log_phantom)
        self.phantom.status_ready.connect(self._phantom_status)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 20, 26, 18)
        outer.setSpacing(12)
        outer.addWidget(title_row("Editor de controles", "Crie layouts por jogo: toque, joystick, mira, atalhos e gestos."))
        outer.addWidget(label("Importe uma captura do jogo para alinhar os pontos ao HUD. A resolução do perfil precisa ser idêntica à tela definida no Phantom (config.toml).", "muted"))

        top = QHBoxLayout()
        self.game_combo = QComboBox()
        for game in games:
            self.game_combo.addItem(f"{game.name}  ·  {game.package_id or 'sem package ID'}", game.package_id or f"local:{game.name}")
        if not games:
            self.game_combo.addItem("Nenhum jogo cadastrado", "local:default")
        top.addWidget(label("Jogo:", "h2"))
        top.addWidget(self.game_combo, 1)
        top.addWidget(label("Resolução do perfil:"))
        self.width_spin = QSpinBox(); self.width_spin.setRange(320, 7680); self.width_spin.setValue(1280); self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox(); self.height_spin.setRange(320, 4320); self.height_spin.setValue(720); self.height_spin.setSuffix(" px")
        top.addWidget(self.width_spin); top.addWidget(self.height_spin)
        top.addWidget(label("Sensibilidade global:"))
        self.global_sensitivity = QDoubleSpinBox()
        self.global_sensitivity.setRange(0.1, 5.0)
        self.global_sensitivity.setSingleStep(0.1)
        self.global_sensitivity.setValue(1.0)
        top.addWidget(self.global_sensitivity)
        outer.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = MappingCanvas()
        self.canvas.selection_changed.connect(self.select_node)
        self.canvas.position_changed.connect(self._canvas_position_changed)
        self.canvas.add_point.connect(self.create_node_at)
        self.canvas.node_dropped.connect(self.reposition_node_by_id)
        map_panel = QWidget()
        map_layout = QVBoxLayout(map_panel)
        map_layout.setContentsMargins(0, 0, 8, 0)
        map_layout.setSpacing(8)
        map_layout.addWidget(label("MAPA DA TELA ANDROID", "h2"))
        map_layout.addWidget(self.canvas, 1)
        reference_row = QHBoxLayout()
        self.reference_btn = QPushButton("Importar screenshot do jogo")
        self.clear_reference_btn = QPushButton("Remover imagem")
        reference_row.addWidget(self.reference_btn)
        reference_row.addWidget(self.clear_reference_btn)
        reference_row.addStretch()
        map_layout.addLayout(reference_row)
        self.reference_btn.clicked.connect(self.import_reference_image)
        self.clear_reference_btn.clicked.connect(self.clear_reference_image)
        split.addWidget(map_panel)

        side = QWidget()
        side.setMinimumWidth(300)
        side.setMaximumWidth(390)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(8, 0, 0, 0)
        side_layout.setSpacing(9)
        side_layout.addWidget(label("MAPEAMENTOS", "h2"))
        self.node_list = MappingListWidget()
        self.node_list.setMinimumHeight(135)
        self.node_list.setDragEnabled(True)
        self.node_list.currentRowChanged.connect(self.select_node)
        side_layout.addWidget(self.node_list, 1)

        edit = QGroupBox("Ação selecionada")
        form = QFormLayout(edit)
        self.type_combo = QComboBox()
        for key, title in NODE_LABELS.items():
            self.type_combo.addItem(title, key)
        self.key_edit = KeyCaptureEdit()
        self.key_edit.setText("E")
        mouse_widget = QWidget()
        mouse_layout = QHBoxLayout(mouse_widget)
        mouse_layout.setContentsMargins(0, 0, 0, 0)
        self.mouse_left_btn = QPushButton("Esq.")
        self.mouse_right_btn = QPushButton("Dir.")
        self.mouse_middle_btn = QPushButton("Meio")
        for mouse_button in (self.mouse_left_btn, self.mouse_right_btn, self.mouse_middle_btn):
            mouse_layout.addWidget(mouse_button)
        self.mouse_left_btn.clicked.connect(lambda: self.apply_captured_binding(binding_from_qt_mouse(1), "key"))
        self.mouse_right_btn.clicked.connect(lambda: self.apply_captured_binding(binding_from_qt_mouse(2), "key"))
        self.mouse_middle_btn.clicked.connect(lambda: self.apply_captured_binding(binding_from_qt_mouse(4), "key"))
        self.up_edit = KeyCaptureEdit(); self.up_edit.setText("W")
        self.down_edit = KeyCaptureEdit(); self.down_edit.setText("S")
        self.left_edit = KeyCaptureEdit(); self.left_edit.setText("A")
        self.right_edit = KeyCaptureEdit(); self.right_edit.setText("D")
        self.radius_spin = QDoubleSpinBox(); self.radius_spin.setRange(0.01, 0.5); self.radius_spin.setSingleStep(0.01); self.radius_spin.setValue(0.075)
        self.sensitivity_spin = QDoubleSpinBox(); self.sensitivity_spin.setRange(0.1, 5.0); self.sensitivity_spin.setSingleStep(0.1); self.sensitivity_spin.setValue(1.0)
        self.reach_spin = QDoubleSpinBox(); self.reach_spin.setRange(0.01, 0.8); self.reach_spin.setSingleStep(0.01); self.reach_spin.setValue(0.18)
        self.aim_curve = QComboBox()
        self.aim_curve.addItem("Equilibrada", "balanced")
        self.aim_curve.addItem("Precisão", "precision")
        self.aim_curve.addItem("Linear", "linear")
        self.aim_mode = QComboBox()
        self.aim_mode.addItem("Segurar botão", "while_held")
        self.aim_mode.addItem("Alternar", "toggle")
        self.aim_mode.addItem("Sempre ativa", "always_on")
        self.interval_spin = QSpinBox(); self.interval_spin.setRange(10, 5000); self.interval_spin.setValue(100); self.interval_spin.setSuffix(" ms")
        self.duration_spin = QSpinBox(); self.duration_spin.setRange(10, 5000); self.duration_spin.setValue(90); self.duration_spin.setSuffix(" ms")
        self.invert_y = QCheckBox("Inverter eixo vertical da mira")
        self.layer_edit = QLineEdit("combat")
        self.node_layer_edit = QLineEdit()
        self.node_layer_edit.setPlaceholderText("vazio = camada base")
        self.layer_mode = QComboBox(); self.layer_mode.addItem("Enquanto pressionada", "hold"); self.layer_mode.addItem("Alternar", "toggle")
        self.suspend_base = QCheckBox("Suspender comandos da camada base"); self.suspend_base.setChecked(True)
        form.addRow("Tipo", self.type_combo)
        form.addRow("Tecla / botão", self.key_edit)
        form.addRow("Mouse", mouse_widget)
        form.addRow("Joystick ↑", self.up_edit)
        form.addRow("Joystick ↓", self.down_edit)
        form.addRow("Joystick ←", self.left_edit)
        form.addRow("Joystick →", self.right_edit)
        form.addRow("Raio do joystick", self.radius_spin)
        form.addRow("Sensibilidade da mira", self.sensitivity_spin)
        form.addRow("Alcance da mira", self.reach_spin)
        form.addRow("Curva da mira", self.aim_curve)
        form.addRow("Ativação da mira", self.aim_mode)
        form.addRow("Intervalo do toque", self.interval_spin)
        form.addRow("Duração do gesto", self.duration_spin)
        form.addRow("Camada", self.layer_edit)
        form.addRow("Camada da ação", self.node_layer_edit)
        form.addRow("Modo da camada", self.layer_mode)
        form.addRow("", self.suspend_base)
        form.addRow("", self.invert_y)
        side_layout.addWidget(edit)

        addrow = QHBoxLayout()
        self.add_btn = QPushButton("＋ Posicionar no mapa")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self.arm_add_node)
        self.remove_btn = QPushButton("Remover")
        self.remove_btn.clicked.connect(self.remove_node)
        addrow.addWidget(self.add_btn, 1); addrow.addWidget(self.remove_btn)
        side_layout.addLayout(addrow)

        binding_row = QHBoxLayout()
        self.capture_binding_btn = QPushButton("Capturar tecla")
        self.capture_binding_btn.clicked.connect(self.start_binding_capture)
        self.clear_binding_btn = QPushButton("Limpar binding")
        self.clear_binding_btn.clicked.connect(self.clear_selected_binding)
        binding_row.addWidget(self.capture_binding_btn)
        binding_row.addWidget(self.clear_binding_btn)
        side_layout.addLayout(binding_row)

        history_row = QHBoxLayout()
        self.undo_btn = QPushButton("↶ Desfazer")
        self.undo_btn.clicked.connect(self.undo_editor_change)
        self.redo_btn = QPushButton("↷ Refazer")
        self.redo_btn.clicked.connect(self.redo_editor_change)
        self.duplicate_btn = QPushButton("Duplicar")
        self.duplicate_btn.clicked.connect(self.duplicate_selected)
        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.clicked.connect(self.copy_selected)
        self.paste_btn = QPushButton("Colar")
        self.paste_btn.clicked.connect(self.paste_mapping)
        for button in (self.undo_btn, self.redo_btn, self.duplicate_btn,
                       self.copy_btn, self.paste_btn):
            history_row.addWidget(button)
        side_layout.addLayout(history_row)
        self.editor_status = label("Pronto.", "muted")
        side_layout.addWidget(self.editor_status)
        self.preset_btn = QPushButton("Criar layout inicial de tiro")
        self.preset_btn.clicked.connect(self.create_shooter_preset)
        side_layout.addWidget(self.preset_btn)
        self.runner_preset_btn = QPushButton("Preset: Runner / Subway Surfers")
        self.runner_preset_btn.clicked.connect(self.create_runner_preset)
        side_layout.addWidget(self.runner_preset_btn)
        self.racing_preset_btn = QPushButton("Preset: Corrida")
        self.racing_preset_btn.clicked.connect(self.create_racing_preset)
        side_layout.addWidget(self.racing_preset_btn)
        self.casual_preset_btn = QPushButton("Preset: Jogo de toque")
        self.casual_preset_btn.clicked.connect(self.create_casual_preset)
        side_layout.addWidget(self.casual_preset_btn)
        self.geometry_preset_btn = QPushButton("Preset: Geometry Dash Lite")
        self.geometry_preset_btn.clicked.connect(self.create_geometry_dash_preset)
        side_layout.addWidget(self.geometry_preset_btn)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setWidget(side)
        split.addWidget(side_scroll)
        split.setSizes([760, 360])
        outer.addWidget(split, 1)

        bottom = QVBoxLayout()
        bottom_top = QHBoxLayout()
        bottom_bottom = QHBoxLayout()
        self.save_btn = QPushButton("Salvar perfil")
        self.save_btn.setObjectName("primary")
        self.export_btn = QPushButton("Exportar JSON Phantom")
        self.import_btn = QPushButton("Importar JSON")
        self.load_btn = QPushButton("Carregar no Phantom")
        self.phantom_gui_btn = QPushButton("Abrir editor Phantom")
        self.capture_btn = QPushButton("Ativar captura")
        self.stop_capture_btn = QPushButton("Desativar captura")
        self.aim_btn = QPushButton("Alternar mira (F1)")
        for button in (self.save_btn, self.export_btn, self.import_btn, self.load_btn):
            bottom_top.addWidget(button)
        for button in (self.phantom_gui_btn, self.capture_btn, self.stop_capture_btn, self.aim_btn):
            bottom_bottom.addWidget(button)
        bottom.addLayout(bottom_top)
        bottom.addLayout(bottom_bottom)
        outer.addLayout(bottom)
        self.phantom_status = label("Phantom: verificando instalação…", "muted")
        outer.addWidget(self.phantom_status)
        self.log = label("Dica: posicione os pontos na imagem. Arraste um marcador para ajustar sua posição.", "muted")
        outer.addWidget(self.log)

        self.game_combo.currentIndexChanged.connect(self.load_current_profile)
        self.width_spin.valueChanged.connect(self._screen_size_changed)
        self.height_spin.valueChanged.connect(self._screen_size_changed)
        self.global_sensitivity.valueChanged.connect(self._sensitivity_changed)
        self.save_btn.clicked.connect(self.save_profile)
        self.export_btn.clicked.connect(self.export_profile)
        self.import_btn.clicked.connect(self.import_profile)
        self.load_btn.clicked.connect(self.load_into_phantom)
        self.phantom_gui_btn.clicked.connect(self.phantom.open_gui)
        self.capture_btn.clicked.connect(self.phantom.enter_capture)
        self.stop_capture_btn.clicked.connect(self.phantom.exit_capture)
        self.aim_btn.clicked.connect(self.phantom.toggle_mouse)
        self.type_combo.currentIndexChanged.connect(self.update_selected_properties)
        self.type_combo.currentIndexChanged.connect(self.prepare_new_node_defaults)
        self.type_combo.currentIndexChanged.connect(lambda *_: self._update_editor_fields(self.type_combo.currentData()))
        self.key_edit.textChanged.connect(self.update_selected_properties)
        self.key_edit.binding_captured.connect(lambda binding: self.apply_captured_binding(binding))
        for field, role in (
            (self.up_edit, "up"), (self.down_edit, "down"),
            (self.left_edit, "left"), (self.right_edit, "right"),
        ):
            field.textChanged.connect(self.update_selected_properties)
            field.binding_captured.connect(
                lambda binding, role=role: self.apply_captured_binding(binding, role)
            )
        self.radius_spin.valueChanged.connect(self.update_selected_properties)
        self.sensitivity_spin.valueChanged.connect(self.update_selected_properties)
        self.reach_spin.valueChanged.connect(self.update_selected_properties)
        self.aim_curve.currentIndexChanged.connect(self.update_selected_properties)
        self.aim_mode.currentIndexChanged.connect(self.update_selected_properties)
        self.interval_spin.valueChanged.connect(self.update_selected_properties)
        self.duration_spin.valueChanged.connect(self.update_selected_properties)
        self.invert_y.toggled.connect(self.update_selected_properties)
        self.layer_edit.textChanged.connect(self.update_selected_properties)
        self.node_layer_edit.textChanged.connect(self.update_selected_properties)
        self.layer_mode.currentIndexChanged.connect(self.update_selected_properties)
        self.suspend_base.toggled.connect(self.update_selected_properties)
        self.phantom.status()
        self.load_current_profile()

    def set_games(self, games: list[GameEntry]):
        current = self.game_combo.currentData()
        self.games = games
        self.game_combo.blockSignals(True)
        self.game_combo.clear()
        for game in games:
            self.game_combo.addItem(f"{game.name}  ·  {game.package_id or 'sem package ID'}", game.package_id or f"local:{game.name}")
        if not games:
            self.game_combo.addItem("Nenhum jogo cadastrado", "local:default")
        index = self.game_combo.findData(current)
        self.game_combo.setCurrentIndex(index if index >= 0 else 0)
        self.game_combo.blockSignals(False)
        self.load_current_profile()

    def _package_key(self):
        return self.game_combo.currentData() or "local:default"

    def _game_name(self) -> str:
        game_index = self.game_combo.currentIndex()
        if 0 <= game_index < len(self.games):
            return self.games[game_index].name
        return "Perfil personalizado"

    def _profile(self):
        """Payload legacy usado pelo canvas/Phantom, derivado de ControlProfileV2."""
        if self.editor is not None:
            payload = self.editor.to_payload()
            if not payload.get("name"):
                payload["name"] = self._game_name()
            return payload
        return {
            "name": self._game_name(),
            "version": 1,
            "screen": {"width": self.width_spin.value(), "height": self.height_spin.value()},
            "global_sensitivity": self.global_sensitivity.value(),
            "nodes": self.nodes,
        }

    # -- integracao com BindingEditor ---------------------------------------

    def _current_node_id(self) -> str:
        if 0 <= self.selected_index < len(self.nodes):
            return str(self.nodes[self.selected_index].get("id", "") or "")
        return ""

    def _set_screen_fields(self, profile: ControlProfileV2) -> None:
        screen = profile.screen_contract
        width = screen.width or 1280
        height = screen.height or 720
        for widget in (self.width_spin, self.height_spin, self.global_sensitivity):
            widget.blockSignals(True)
        self.width_spin.setValue(int(width))
        self.height_spin.setValue(int(height))
        self.global_sensitivity.setValue(float(profile.cursor_model.sensitivity))
        for widget in (self.width_spin, self.height_spin, self.global_sensitivity):
            widget.blockSignals(False)
        self.canvas.set_screen_size(int(width), int(height))

    def _screen_size_changed(self, *_args):
        self.canvas.set_screen_size(self.width_spin.value(), self.height_spin.value())
        if self.editor is not None:
            self.editor.set_screen(self.width_spin.value(), self.height_spin.value())
            self._update_editor_status()

    def _sensitivity_changed(self, value):
        if self.editor is not None:
            self.editor.set_sensitivity(float(value))
            self._update_editor_status()

    def _update_editor_status(self) -> list:
        if self.editor is None:
            self.editor_status.setText("Editor indisponível.")
            return []
        issues = self.editor.conflicts()
        errors = [issue for issue in issues if issue.severity == "error"]
        warnings = [issue for issue in issues if issue.severity == "warning"]
        state = "Alterações não salvas" if self.editor.dirty else "Salvo"
        self.editor_status.setText(
            f"{state} · {len(errors)} erro(s) · {len(warnings)} aviso(s)"
        )
        return errors

    def _after_editor_change(self, preferred_id: str | None = None):
        if self.editor is None:
            return
        previous_id = preferred_id if preferred_id is not None else self._current_node_id()
        self.nodes = self.editor.to_payload()["nodes"]
        self.selected_index = next(
            (index for index, node in enumerate(self.nodes)
             if str(node.get("id", "")) == previous_id),
            -1,
        )
        self._update_editor_status()
        self.refresh_node_list()
        self._redo_selection_id = ""

    def _load_profile_object(self, profile: ControlProfileV2, message: str) -> None:
        if self.editor is None:
            self.editor = BindingEditor(profile)
        else:
            self.editor.restore_default(profile)
        self._captured_text.clear()
        self._captured_bindings.clear()
        self._pending_binding = None
        self._set_screen_fields(profile)
        self.nodes = self.editor.to_payload()["nodes"]
        self.selected_index = 0 if self.nodes else -1
        self._after_editor_change(self.nodes[0]["id"] if self.nodes else "")
        self.log.setText(message)

    def _load_payload_into_editor(self, payload: dict, message: str) -> None:
        normalized, warnings = normalize_legacy_slots(payload)
        profile = legacy_payload_to_profile(
            normalized,
            game_package=self._package_key(),
            screen_source="imported",
        )
        suffix = f" Ajustes automáticos: {'; '.join(warnings)}" if warnings else ""
        self._load_profile_object(profile, message + suffix)

    def load_current_profile(self, *_args):
        package = self._package_key()
        profile: ControlProfileV2 | None = None
        source = "novo"
        try:
            profile = storage.load_control_profile(package)
            if profile is not None:
                source = "V2"
        except storage.StorageError as error:
            self.log.setText(f"Perfil V2 ilegível; usando o legado sem apagá-lo. {error}"[:500])

        if profile is None:
            legacy = storage.load_game_controls(package)
            if legacy:
                normalized, warnings = normalize_legacy_slots(legacy)
                profile = legacy_payload_to_profile(
                    normalized, game_package=package, screen_source="imported"
                )
                source = "V1"
                if warnings:
                    self.log.setText("Perfil V1 ajustado em memória: " + "; ".join(warnings))

        if profile is None:
            profile = legacy_payload_to_profile({
                "version": 1,
                "name": self._game_name(),
                "screen": {"width": 1280, "height": 720},
                "global_sensitivity": 1.0,
                "nodes": [],
            }, game_package=package, screen_source="default")

        if not profile.name:
            profile.name = self._game_name()
        self.editor = BindingEditor(profile)
        self._captured_text.clear()
        self._captured_bindings.clear()
        self._pending_binding = None
        self._set_screen_fields(profile)
        self.nodes = self.editor.to_payload()["nodes"]
        self.selected_index = 0 if self.nodes else -1
        self._load_reference_for_current_game()
        self._update_editor_fields(self.type_combo.currentData())
        self._after_editor_change(self.nodes[0]["id"] if self.nodes else "")
        if not self.log.text().startswith("Perfil V1 ajustado") and not self.log.text().startswith("Perfil V2 ilegível"):
            self.log.setText(f"Perfil {source} carregado para {self._game_name()}.")

    def refresh_node_list(self, *_args):
        self.node_list.blockSignals(True)
        self.node_list.clear()
        for node in self.nodes:
            kind = NODE_LABELS.get(node.get("type"), node.get("type", "Ação"))
            key = node.get("key") or ("WASD" if node.get("type") == "joystick" else node.get("activation_key", "—"))
            if node.get("type") == "layer_shift":
                key = f"{key} → {node.get('layer_name', 'combat')}"
            elif node.get("type") == "wheel":
                key = "Wheel ↑ / ↓"
            if node.get("layer"):
                key += f"  [{node['layer']}]"
            item = QListWidgetItem(f"{kind}   ·   {key}")
            item.setData(Qt.ItemDataRole.UserRole, str(node.get("id", "")))
            self.node_list.addItem(item)
        self.node_list.setCurrentRow(self.selected_index)
        self.node_list.blockSignals(False)
        self.canvas.selected = self.selected_index
        self.canvas.set_nodes(self.nodes)

    def _canvas_position_changed(self, index: int):
        if self.editor is None or not (0 <= index < len(self.nodes)):
            self.refresh_node_list()
            return
        node = self.nodes[index]
        node_id = str(node.get("id", ""))
        profile_node = next(
            (item for item in self.editor.profile.nodes if item.id == node_id), None
        )
        if profile_node is None:
            self.refresh_node_list()
            return
        positions: dict[str, tuple[float, float]] = {}
        for name in POSITION_FIELDS:
            current = node.get(name)
            if not isinstance(current, dict) or "x" not in current or "y" not in current:
                continue
            if profile_node.geometry.get(name) != current:
                positions[name] = (current["x"], current["y"])
        sequence_positions: dict[int, tuple[float, float]] = {}
        for step_index, step in enumerate(node.get("sequence", [])):
            if not isinstance(step, dict) or not isinstance(step.get("pos"), dict):
                continue
            current = step["pos"]
            previous = (profile_node.sequence[step_index].get("pos")
                        if step_index < len(profile_node.sequence) else None)
            if previous != current:
                sequence_positions[step_index] = (current["x"], current["y"])
        if positions or sequence_positions:
            self.editor.update_node_geometry(
                node_id, positions, sequence_positions=sequence_positions
            )
            self._after_editor_change(node_id)

    def reposition_node_by_id(self, node_id: str, x: float, y: float):
        """Arrastar um item da lista para o canvas reposiciona o controle."""
        if self.editor is None:
            return
        node = next((item for item in self.nodes if str(item.get("id", "")) == node_id), None)
        if node is None:
            return
        kind = node.get("type")
        positions: dict[str, tuple[float, float]] = {}
        sequence_positions: dict[int, tuple[float, float]] = {}
        if kind == "drag":
            start = node.get("start", {"x": x, "y": y})
            end = node.get("end", {"x": x, "y": y})
            dx, dy = x - float(start.get("x", x)), y - float(start.get("y", y))
            positions = {
                "start": (x, y),
                "end": (float(end.get("x", x)) + dx, float(end.get("y", y)) + dy),
            }
        elif kind == "wheel":
            up = node.get("up_pos", {"x": x, "y": y})
            down = node.get("down_pos", {"x": x, "y": y})
            dx, dy = x - float(up.get("x", x)), y - float(up.get("y", y))
            positions = {
                "up_pos": (x, y),
                "down_pos": (float(down.get("x", x)) + dx, float(down.get("y", y)) + dy),
            }
        elif kind == "macro":
            sequence_positions = {0: (x, y)}
        else:
            positions = {"anchor" if kind == "aim" else "pos": (x, y)}
        self.editor.update_node_geometry(
            node_id, positions, sequence_positions=sequence_positions
        )
        self._after_editor_change(node_id)
        self.log.setText(f"Controle reposicionado em {x:.2f}, {y:.2f}.")

    def _role_for_key_field(self, node: dict, role: str | None = None) -> str:
        if node.get("type") == "aim" and role in (None, "key"):
            return "activation_key"
        if role:
            return role
        return "key"

    def _binding_for_text(self, node_id: str, role: str, text: str):
        key = (node_id, role)
        if self._captured_text.get(key) == text and key in self._captured_bindings:
            return self._captured_bindings[key]
        self._captured_text.pop(key, None)
        self._captured_bindings.pop(key, None)
        return binding_from_text(text)

    def apply_captured_binding(self, binding, role: str | None = None):
        """Aplica uma identidade capturada localmente ao controle selecionado."""
        if self.editor is None or not getattr(binding, "canonical_name", ""):
            return
        if self.selected_index < 0 or self.selected_index >= len(self.nodes):
            self._pending_binding = (role or "key", binding)
            self.log.setText("Binding capturado. Selecione ou crie um controle para aplicá-lo.")
            return
        node = self.nodes[self.selected_index]
        node_id = str(node.get("id", ""))
        resolved_role = self._role_for_key_field(node, role)
        self.editor.start_capture(node_id, resolved_role)
        self.editor.finish_capture(binding)
        text = binding.canonical_name
        self._captured_text[(node_id, resolved_role)] = text
        self._captured_bindings[(node_id, resolved_role)] = binding
        field = (self.up_edit if resolved_role == "up" else
                 self.down_edit if resolved_role == "down" else
                 self.left_edit if resolved_role == "left" else
                 self.right_edit if resolved_role == "right" else self.key_edit)
        field.blockSignals(True)
        field.setText(text)
        field.blockSignals(False)
        self._after_editor_change(node_id)
        self.log.setText(f"Binding local trocado: {text} (sem captura global).")

    def start_binding_capture(self):
        if self.editor is None or self.selected_index < 0:
            self.log.setText("Selecione um controle antes de capturar um binding.")
            return
        node_id = self._current_node_id()
        node = self.nodes[self.selected_index]
        role = self._role_for_key_field(node)
        self.editor.start_capture(node_id, role)
        self.key_edit.setFocus()
        self.log.setText("Pressione a tecla desejada; o nome não será lido do texto digitado.")

    def clear_selected_binding(self):
        if self.editor is None or self.selected_index < 0:
            return
        node_id = self._current_node_id()
        node = self.nodes[self.selected_index]
        roles = ["up", "down", "left", "right"] if node.get("type") == "joystick" else [
            self._role_for_key_field(node)
        ]
        for role in roles:
            self.editor.remove_binding(node_id, role)
            self._captured_text.pop((node_id, role), None)
            self._captured_bindings.pop((node_id, role), None)
        self._after_editor_change(node_id)
        self.log.setText("Binding removido do controle selecionado.")

    def undo_editor_change(self):
        selected_id = self._current_node_id()
        if self.editor is not None and self.editor.undo():
            self._after_editor_change(selected_id)
            if self.selected_index < 0 and selected_id:
                self._redo_selection_id = selected_id
            self.log.setText("Desfazer aplicado.")

    def redo_editor_change(self):
        selected_id = self._current_node_id() or self._redo_selection_id
        if self.editor is not None and self.editor.redo():
            self._after_editor_change(selected_id)
            self.log.setText("Refazer aplicado.")

    def duplicate_selected(self):
        if self.editor is not None and self._current_node_id():
            new_id = self.editor.duplicate_node(self._current_node_id())
            self._after_editor_change(new_id)
            self.log.setText("Controle duplicado; ajuste a posição se necessário.")

    def copy_selected(self):
        if self.editor is not None and self._current_node_id():
            self.editor.copy_node(self._current_node_id())
            self.log.setText("Controle copiado.")

    def paste_mapping(self):
        if self.editor is None:
            return
        new_id = self.editor.paste_node()
        if new_id:
            self._after_editor_change(new_id)
            self.log.setText("Controle colado com novos ID e slot.")

    def select_node(self, index: int):
        if index < -1 or index >= len(self.nodes):
            return
        self.selected_index = index
        self.canvas.selected = index
        if index >= 0:
            node = self.nodes[index]
            type_index = self.type_combo.findData(node.get("type", "tap"))
            self.type_combo.blockSignals(True)
            self.type_combo.setCurrentIndex(max(0, type_index))
            self.type_combo.blockSignals(False)
            self.key_edit.blockSignals(True)
            self.key_edit.setText(node.get("key") or node.get("activation_key", ""))
            self.key_edit.blockSignals(False)
            keys = node.get("keys", {})
            for field, key in ((self.up_edit, "up"), (self.down_edit, "down"), (self.left_edit, "left"), (self.right_edit, "right")):
                field.blockSignals(True); field.setText(keys.get(key, "")); field.blockSignals(False)
            for field, value in (
                (self.radius_spin, node.get("radius", 0.075)),
                (self.sensitivity_spin, node.get("sensitivity", 1.0)),
                (self.reach_spin, node.get("reach", 0.18)),
                (self.interval_spin, node.get("interval_ms", 100)),
                (self.duration_spin, node.get("duration_ms", 90)),
            ):
                field.blockSignals(True); field.setValue(value); field.blockSignals(False)
            self.invert_y.blockSignals(True); self.invert_y.setChecked(bool(node.get("invert_y", False))); self.invert_y.blockSignals(False)
            self.aim_curve.blockSignals(True); self.aim_curve.setCurrentIndex(max(0, self.aim_curve.findData(node.get("curve", "balanced")))); self.aim_curve.blockSignals(False)
            self.aim_mode.blockSignals(True); self.aim_mode.setCurrentIndex(max(0, self.aim_mode.findData(node.get("activation_mode", "while_held")))); self.aim_mode.blockSignals(False)
            self.layer_edit.blockSignals(True); self.layer_edit.setText(node.get("layer_name", "combat")); self.layer_edit.blockSignals(False)
            self.node_layer_edit.blockSignals(True); self.node_layer_edit.setText(node.get("layer", "")); self.node_layer_edit.blockSignals(False)
            self.layer_mode.blockSignals(True); self.layer_mode.setCurrentIndex(max(0, self.layer_mode.findData(node.get("mode", "hold")))); self.layer_mode.blockSignals(False)
            self.suspend_base.blockSignals(True); self.suspend_base.setChecked(bool(node.get("suspend_base", True))); self.suspend_base.blockSignals(False)
        self._update_editor_fields(node.get("type", "tap") if index >= 0 else self.type_combo.currentData())
        self.refresh_node_list()

    def _update_editor_fields(self, kind):
        """Deixa ativos apenas os ajustes relevantes ao tipo de controle selecionado."""
        kind = kind or "tap"
        key_enabled = kind in ("tap", "toggle_tap", "repeat_tap", "drag", "macro", "layer_shift", "aim")
        for widget in (self.key_edit, self.mouse_left_btn, self.mouse_right_btn, self.mouse_middle_btn):
            widget.setEnabled(key_enabled)
        for widget in (self.up_edit, self.down_edit, self.left_edit, self.right_edit, self.radius_spin):
            widget.setEnabled(kind == "joystick")
        for widget in (self.sensitivity_spin, self.reach_spin, self.aim_curve, self.aim_mode, self.invert_y):
            widget.setEnabled(kind == "aim")
        self.interval_spin.setEnabled(kind == "repeat_tap")
        self.duration_spin.setEnabled(kind == "drag")
        for widget in (self.layer_edit, self.layer_mode, self.suspend_base):
            widget.setEnabled(kind == "layer_shift")
        self.node_layer_edit.setEnabled(kind not in ("layer_shift", "wheel"))

    def arm_add_node(self):
        # Ao criar um novo ponto, separa o tipo novo do controle que estava selecionado.
        self.selected_index = -1
        self.node_list.setCurrentRow(-1)
        self.canvas.selected = -1
        self.canvas.update()
        self.canvas.set_add_mode(True)
        kind = self.type_combo.currentData() or "tap"
        self._update_editor_fields(kind)
        if kind == "layer_shift":
            self.log.setText("Clique em qualquer ponto da tela para adicionar a troca de camada (ela aparece no topo do mapa).")
        else:
            self.log.setText("Clique na posição desejada dentro da tela Android para adicionar o controle.")

    def prepare_new_node_defaults(self, *_args):
        if self.selected_index >= 0:
            return
        kind = self.type_combo.currentData()
        if kind == "aim" and self.key_edit.text().strip() in ("", "E"):
            self.key_edit.setText("MouseRight")
        elif kind == "wheel":
            self.key_edit.clear()
        elif kind in ("tap", "toggle_tap", "repeat_tap", "drag", "macro", "layer_shift") and not self.key_edit.text().strip():
            self.key_edit.setText("E")

    def create_node_at(self, x: float, y: float):
        if self.editor is None:
            return
        kind = self.type_combo.currentData() or "tap"
        used_slots: set[int] = set()
        for existing in self.editor.profile.nodes:
            for value in (existing.slot, existing.up_slot, existing.down_slot):
                if value is not None:
                    used_slots.add(int(value))
            for step in existing.sequence:
                if isinstance(step, dict) and step.get("slot") is not None:
                    used_slots.add(int(step["slot"]))
        slot = next(candidate for candidate in range(255) if candidate not in used_slots)
        down_slot = next(
            candidate for candidate in range(255)
            if candidate not in used_slots and candidate != slot
        )
        key = self.key_edit.text().strip() or "E"
        existing_ids = {str(node.get("id", "")) for node in self.nodes}
        number = 1
        while f"control_{number}" in existing_ids:
            number += 1
        node_id = f"control_{number}"
        if kind == "joystick":
            node = {"id": node_id, "type": kind, "slot": slot, "pos": {"x": x, "y": y}, "radius": self.radius_spin.value(),
                    "keys": {"up": self.up_edit.text() or "W", "down": self.down_edit.text() or "S",
                             "left": self.left_edit.text() or "A", "right": self.right_edit.text() or "D"}}
        elif kind == "aim":
            activation_key = key if key and key != "E" else "MouseRight"
            activation_mode = self.aim_mode.currentData() or "while_held"
            node = {"id": node_id, "type": kind, "slot": slot, "anchor": {"x": x, "y": y}, "reach": self.reach_spin.value(),
                    "sensitivity": self.sensitivity_spin.value(), "curve": self.aim_curve.currentData() or "balanced",
                    "activation_mode": activation_mode, "invert_y": self.invert_y.isChecked()}
            if activation_mode != "always_on":
                node["activation_key"] = activation_key
        elif kind == "drag":
            node = {"id": node_id, "type": kind, "slot": slot, "start": {"x": x, "y": y},
                    "end": {"x": min(1.0, x + 0.18), "y": y}, "key": key, "duration_ms": self.duration_spin.value()}
        elif kind == "repeat_tap":
            node = {"id": node_id, "type": kind, "slot": slot, "pos": {"x": x, "y": y}, "key": key, "interval_ms": self.interval_spin.value()}
        elif kind == "wheel":
            node = {"id": node_id, "type": kind, "up_slot": slot, "up_pos": {"x": x, "y": y},
                    "down_slot": down_slot, "down_pos": {"x": x, "y": min(1.0, y + 0.15)}}
        elif kind == "macro":
            node = {"id": node_id, "type": kind, "key": key, "mode": "one_shot",
                    "sequence": [{"action": "down", "pos": {"x": x, "y": y}, "slot": slot},
                                 {"action": "up", "slot": slot, "delay_ms": 60}]}
        elif kind == "layer_shift":
            node = {"id": node_id, "type": kind, "key": key,
                    "layer_name": self.layer_edit.text().strip() or "combat",
                    "mode": self.layer_mode.currentData() or "hold",
                    "suspend_base": self.suspend_base.isChecked()}
        else:
            node = {"id": node_id, "type": kind, "slot": slot, "pos": {"x": x, "y": y}, "key": key}
        node_id = self.editor.add_node(node)
        if self._pending_binding is not None:
            pending_role, pending_binding = self._pending_binding
            resolved = self._role_for_key_field(node, pending_role)
            self.editor.start_capture(node_id, resolved)
            self.editor.finish_capture(pending_binding)
            text = pending_binding.canonical_name
            self._captured_text[(node_id, resolved)] = text
            self._captured_bindings[(node_id, resolved)] = pending_binding
            self._pending_binding = None
        self._after_editor_change(node_id)
        self._update_editor_fields(kind)
        self.log.setText(
            f"Controle adicionado em {x:.2f}, {y:.2f}. Arraste os marcadores "
            "ou arraste um item da lista para reposicionar."
        )

    def update_selected_properties(self, *_args):
        if self.editor is None or self.selected_index < 0 or self.selected_index >= len(self.nodes):
            return
        node = self.nodes[self.selected_index]
        node_id = str(node.get("id", ""))
        new_type = self.type_combo.currentData()
        if new_type and new_type != node.get("type"):
            # O seletor também define o tipo do próximo marcador; não altera o nó atual.
            self.selected_index = -1
            self.canvas.selected = -1
            self.canvas.update()
            self.node_list.setCurrentRow(-1)
            self.log.setText("Novo tipo selecionado. Clique em ‘Posicionar no mapa’ e escolha onde ele ficará.")
            return

        kind = node.get("type")
        parameters: dict = {}
        bindings: dict[str, object] = {}
        layer: str | None = None

        if kind == "aim":
            mode = self.aim_mode.currentData() or "while_held"
            parameters.update({
                "activation_mode": mode,
                "sensitivity": self.sensitivity_spin.value(),
                "reach": self.reach_spin.value(),
                "curve": self.aim_curve.currentData() or "balanced",
                "invert_y": self.invert_y.isChecked(),
            })
            if mode == "always_on":
                self.editor.remove_binding(node_id, "activation_key")
                self._captured_text.pop((node_id, "activation_key"), None)
                self._captured_bindings.pop((node_id, "activation_key"), None)
            else:
                text = self.key_edit.text().strip() or "MouseRight"
                bindings["activation_key"] = self._binding_for_text(node_id, "activation_key", text)
        elif kind not in ("joystick", "wheel"):
            text = self.key_edit.text().strip() or "E"
            bindings["key"] = self._binding_for_text(node_id, "key", text)

        if kind != "layer_shift":
            layer = self.node_layer_edit.text().strip()

        if kind == "joystick":
            parameters["radius"] = self.radius_spin.value()
            for field, role in ((self.up_edit, "up"), (self.down_edit, "down"),
                                (self.left_edit, "left"), (self.right_edit, "right")):
                text = field.text().strip() or {
                    "up": "W", "down": "S", "left": "A", "right": "D"
                }[role]
                bindings[role] = self._binding_for_text(node_id, role, text)
        elif kind == "repeat_tap":
            parameters["interval_ms"] = self.interval_spin.value()
        elif kind == "drag":
            parameters["duration_ms"] = self.duration_spin.value()
        elif kind == "layer_shift":
            parameters.update({
                "layer_name": self.layer_edit.text().strip() or "combat",
                "mode": self.layer_mode.currentData() or "hold",
                "suspend_base": self.suspend_base.isChecked(),
            })

        for role, binding in bindings.items():
            self.editor.set_binding(node_id, role, binding)
        if parameters or layer is not None:
            self.editor.update_node_properties(node_id, parameters=parameters, layer=layer)
        self._after_editor_change(node_id)

    def remove_node(self):
        if self.editor is None or self.selected_index < 0:
            return
        node_id = self._current_node_id()
        if not node_id:
            return
        self.editor.remove_node(node_id)
        self._after_editor_change("")
        self.log.setText("Controle removido.")

    def _set_preset_nodes(self, nodes: list[dict], message: str):
        payload = self._profile()
        payload["nodes"] = nodes
        self._load_payload_into_editor(payload, message)

    def create_shooter_preset(self):
        nodes = [
            {"id": "move", "type": "joystick", "slot": 0, "pos": {"x": 0.17, "y": 0.76}, "radius": 0.075,
             "keys": {"up": "W", "down": "S", "left": "A", "right": "D"}},
            {"id": "camera", "type": "aim", "slot": 1, "anchor": {"x": 0.68, "y": 0.48}, "reach": 0.18,
             "sensitivity": 1.0, "curve": "balanced", "activation_mode": "while_held", "activation_key": "MouseRight", "invert_y": False},
            {"id": "fire", "type": "tap", "slot": 2, "pos": {"x": 0.91, "y": 0.76}, "key": "MouseLeft"},
            {"id": "jump", "type": "tap", "slot": 3, "pos": {"x": 0.79, "y": 0.84}, "key": "Space"},
        ]
        self._set_preset_nodes(
            nodes,
            "Layout base criado. Ajuste os pontos para a interface do jogo antes de exportar/ativar.",
        )

    def create_runner_preset(self):
        nodes = [
            {"id": "swipe_up", "type": "drag", "slot": 0, "start": {"x": .50, "y": .78},
             "end": {"x": .50, "y": .34}, "key": "W", "duration_ms": 90},
            {"id": "swipe_down", "type": "drag", "slot": 1, "start": {"x": .50, "y": .34},
             "end": {"x": .50, "y": .78}, "key": "S", "duration_ms": 90},
            {"id": "swipe_left", "type": "drag", "slot": 2, "start": {"x": .70, "y": .60},
             "end": {"x": .28, "y": .60}, "key": "A", "duration_ms": 90},
            {"id": "swipe_right", "type": "drag", "slot": 3, "start": {"x": .28, "y": .60},
             "end": {"x": .70, "y": .60}, "key": "D", "duration_ms": 90},
        ]
        self._set_preset_nodes(
            nodes,
            "Preset Runner criado. Ajuste as quatro áreas de gesto conforme o jogo.",
        )

    def create_racing_preset(self):
        nodes = [
            {"id": "steer", "type": "joystick", "slot": 0, "pos": {"x": .18, "y": .78}, "radius": .10,
             "keys": {"up": "W", "down": "S", "left": "A", "right": "D"}},
            {"id": "accelerate", "type": "tap", "slot": 1, "pos": {"x": .88, "y": .78}, "key": "Space"},
            {"id": "brake", "type": "tap", "slot": 2, "pos": {"x": .72, "y": .80}, "key": "LeftShift"},
        ]
        self._set_preset_nodes(
            nodes,
            "Preset de corrida criado. Ajuste aceleração, freio e direção para o HUD do jogo.",
        )

    def create_casual_preset(self):
        nodes = [
            {"id": "primary", "type": "tap", "slot": 0, "pos": {"x": .50, "y": .72}, "key": "Space"},
            {"id": "secondary", "type": "tap", "slot": 1, "pos": {"x": .82, "y": .78}, "key": "MouseLeft"},
        ]
        self._set_preset_nodes(
            nodes,
            "Preset de jogo casual criado. Arraste os pontos para os botões da tela.",
        )

    def create_geometry_dash_preset(self):
        nodes = [
            {"id": "jump", "type": "tap", "slot": 0, "pos": {"x": .50, "y": .78}, "key": "Space"},
        ]
        self._set_preset_nodes(
            nodes,
            "Preset de Geometry Dash Lite criado. Ajuste o ponto para a área de toque e salve o perfil.",
        )

    def _reference_path(self):
        folder = storage.DATA_DIR / "mapping_backgrounds"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{_slug(self._package_key())}"

    def _load_reference_for_current_game(self):
        base = self._reference_path()
        match = next((path for path in base.parent.glob(base.name + ".*") if path.is_file()), None)
        self.canvas.set_background(str(match) if match else "")
        self.clear_reference_btn.setEnabled(match is not None)

    def import_reference_image(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Escolher screenshot do jogo", str(Path.home() / "Pictures"),
            "Imagens (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not filename:
            return
        pixmap = QPixmap(filename)
        if pixmap.isNull():
            QMessageBox.warning(self, "Imagem inválida", "Não foi possível abrir essa imagem.")
            return
        if pixmap.width() < 320 or pixmap.height() < 320 or pixmap.width() > 7680 or pixmap.height() > 4320:
            QMessageBox.warning(self, "Dimensões inválidas", "Use uma imagem entre 320 × 320 e 7680 × 4320 pixels.")
            return
        base = self._reference_path()
        for old in base.parent.glob(base.name + ".*"):
            try:
                old.unlink()
            except OSError:
                pass
        suffix = Path(filename).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            suffix = ".png"
        destination = base.with_suffix(suffix)
        try:
            shutil.copy2(filename, destination)
        except OSError as error:
            QMessageBox.warning(self, "Imagem de referência", str(error))
            return
        self.width_spin.setValue(pixmap.width())
        self.height_spin.setValue(pixmap.height())
        self.canvas.set_screen_size(pixmap.width(), pixmap.height())
        self.canvas.set_background(str(destination))
        self.clear_reference_btn.setEnabled(True)
        self.log.setText(
            f"Imagem carregada ({pixmap.width()} × {pixmap.height()}). A resolução do perfil foi ajustada; "
            "confirme que a tela configurada no Waydroid/Phantom usa as mesmas dimensões."
        )

    def clear_reference_image(self):
        base = self._reference_path()
        for old in base.parent.glob(base.name + ".*"):
            try:
                old.unlink()
            except OSError:
                pass
        self.canvas.set_background("")
        self.clear_reference_btn.setEnabled(False)
        self.log.setText("Imagem de referência removida. Os pontos do perfil foram mantidos.")

    def import_profile(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Importar perfil de controles", str(Path.home() / "Downloads"), "Perfil JSON (*.json)"
        )
        if not filename:
            return
        try:
            raw = json.loads(Path(filename).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("O arquivo precisa conter um objeto JSON.")

            if raw.get("schema_version") == 2:
                profile = ControlProfileV2.from_dict(raw)
                self._load_profile_object(
                    profile,
                    "Perfil V2 importado. A proveniência dos bindings foi preservada.",
                )
                return

            if raw.get("version") != 1:
                raise ValueError("O arquivo não é um perfil V1 nem V2 suportado.")
            errors = validate_editor_payload(raw)
            if errors:
                raise ValueError("; ".join(errors))
            screen = raw.get("screen")
            nodes = raw.get("nodes")
            if any(not isinstance(node, dict) or node.get("type") not in NODE_LABELS for node in nodes):
                raise ValueError("O perfil contém um tipo de controle desconhecido.")
            sensitivity = float(raw.get("global_sensitivity", 1.0))
            if not math.isfinite(sensitivity) or sensitivity <= 0:
                raise ValueError("A sensibilidade global precisa ser maior que zero.")
            used_slots: list[int] = []
            for node in nodes:
                used_slots.extend(int(node[key]) for key in ("slot", "up_slot", "down_slot") if key in node)
                # Passos down/up de uma mesma macro podem reutilizar o mesmo slot.
                macro_slots = {int(step["slot"]) for step in node.get("sequence", [])
                               if isinstance(step, dict) and "slot" in step}
                used_slots.extend(macro_slots)
            if len(used_slots) != len(set(used_slots)):
                raise ValueError("O perfil usa o mesmo slot de toque em mais de um controle.")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError,
                OverflowError, ProfileError) as error:
            QMessageBox.warning(self, "Perfil inválido", str(error))
            return
        self._load_payload_into_editor(
            raw, "Perfil V1 importado para edição. Salve para criar a versão atômica V2."
        )

    def save_profile(self):
        if self.editor is None:
            QMessageBox.warning(self, "Salvar perfil", "Nenhum perfil V2 foi carregado.")
            return
        errors = self._update_editor_status()
        if errors:
            QMessageBox.warning(
                self, "Perfil inválido",
                "Nada foi gravado. " + "; ".join(issue.message for issue in errors[:5]),
            )
            return
        package = self._package_key()
        try:
            storage.save_control_profile(package, self.editor.profile)
        except storage.StorageError as error:
            QMessageBox.warning(self, "Salvar perfil V2", str(error))
            return
        if not storage.save_game_controls(package, self._profile()):
            QMessageBox.warning(
                self, "Salvar compatibilidade V1",
                "O perfil V2 foi gravado, mas não foi possível atualizar a cópia legada.",
            )
            return
        self.editor.mark_saved()
        self._update_editor_status()
        self.log.setText("Perfil salvo: V2 atômico e cópia legada V1 atualizada.")

    def export_profile(self):
        profile = self._profile()
        filename, _ = QFileDialog.getSaveFileName(self, "Exportar perfil Phantom", f"{_slug(profile['name'])}.json", "Perfil JSON (*.json)")
        if not filename:
            return
        try:
            storage.atomic_write_json(Path(filename), profile)
            self.log.setText(f"Perfil exportado: {filename}")
        except (OSError, storage.StorageError) as error:
            QMessageBox.warning(self, "Exportar perfil", str(error))

    def _saved_profile_path(self):
        profile = self._profile()
        folder = storage.DATA_DIR / "phantom_profiles"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{_slug(profile['name'])}.json"
        storage.atomic_write_json(path, profile)
        return path

    def activate_profile_for_game(self, package_id: str, callback):
        """Carrega o perfil salvo para o jogo antes de iniciar; retorna se tentou ativar."""
        if not package_id or not self.phantom.available():
            return False
        if self._package_key() == package_id:
            self.save_profile()
        profile = storage.load_game_controls(package_id)
        if not profile or not profile.get("nodes"):
            return False
        try:
            folder = storage.DATA_DIR / "phantom_profiles"
            folder.mkdir(parents=True, exist_ok=True)
            game_name = profile.get("name", package_id.rsplit(".", 1)[-1])
            path = folder / f"{_slug(game_name)}.json"
            path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            self._log_phantom(f"Não foi possível preparar o perfil de controle: {error}")
            return False

        def audit_done(result):
            if not result.ok:
                self._log_phantom(result.text or "Phantom rejeitou o perfil deste jogo.")
                callback(False)
                return
            self.phantom.load_profile(path, lambda loaded: callback(bool(loaded.ok)))

        self.phantom.audit_profile(path, audit_done)
        return True

    def load_into_phantom(self):
        if not self.phantom.available():
            QMessageBox.information(self, "Phantom não instalado", "Instale o Phantom para ativar o mapeamento real. O perfil pode ser exportado em JSON mesmo sem ele.")
            return
        try:
            self.save_profile()
            path = self._saved_profile_path()
            self.phantom.audit_profile(path, lambda result: self._phantom_audit_done(result, path))
        except OSError as error:
            QMessageBox.warning(self, "Phantom", str(error))

    def _phantom_audit_done(self, result, path):
        if result.ok:
            self.phantom.load_profile(path)
        else:
            self.log.setText((result.text or "Phantom rejeitou o perfil.")[:500])
            QMessageBox.warning(self, "Perfil incompatível", "O Phantom não aprovou este perfil. Confira a resolução e os detalhes no log.")

    def _log_phantom(self, text: str):
        self.log.setText(text[:500])

    def _phantom_status(self, text: str, ok: bool):
        self.phantom_status.setText(("Phantom ativo: " if ok else "Phantom: ") + text[:220])

    def shutdown(self):
        self.phantom.shutdown()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
