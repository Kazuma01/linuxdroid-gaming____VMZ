"""Integração real com PySide6, executada apenas quando o Qt está disponível.

O comando de testes padrão usa o Python do sistema, sem PySide6 nesta máquina.
Quando executado com o .venv do projeto, este arquivo valida a tela real em
modo offscreen, sem abrir janelas, dispositivos ou processos externos.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

from linuxdroid import storage
from linuxdroid.models import GameEntry

PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None
if PYSIDE_AVAILABLE:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from linuxdroid.input.qt_bridge import binding_from_qt_key
    from linuxdroid.screens.controls import ControlsScreen, _binding_from_qt_event


class _FakeKeyEvent:
    def __init__(self, key: int, scan: int, virtual: int, modifiers):
        self._key = key
        self._scan = scan
        self._virtual = virtual
        self._modifiers = modifiers

    def key(self):
        return self._key

    def nativeScanCode(self):
        return self._scan

    def nativeVirtualKey(self):
        return self._virtual

    def modifiers(self):
        return self._modifiers


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")
class EditorGuiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_data_dir = storage.DATA_DIR
        self.temp = tempfile.TemporaryDirectory()
        storage.DATA_DIR = Path(self.temp.name)
        self.screen = ControlsScreen([GameEntry("Jogo", "com.example.game")])

    def tearDown(self):
        self.screen.shutdown()
        storage.DATA_DIR = self.old_data_dir
        self.temp.cleanup()

    def test_create_capture_duplicate_undo_redo_remove_and_save(self):
        screen = self.screen
        self.assertEqual(len(screen.nodes), 0)
        screen.type_combo.setCurrentIndex(0)
        screen.create_node_at(0.3, 0.7)

        screen.apply_captured_binding(
            binding_from_qt_key(0x51, native_scan_code=0x11, native_virtual_key=0x51)
        )
        node_id = screen.nodes[0]["id"]
        ref = screen.editor.profile.nodes[0].binding_refs["key"]
        binding = screen.editor.profile.bindings[ref]
        self.assertEqual(binding.canonical_name, "Q")
        self.assertEqual(binding.code_space, "qt_native_scan_code")
        self.assertEqual(binding.provenance, "validated_by_vocabulary")

        screen.duplicate_selected()
        self.assertEqual(len(screen.nodes), 2)
        screen.undo_editor_change()
        self.assertEqual(len(screen.nodes), 1)
        screen.redo_editor_change()
        self.assertEqual(len(screen.nodes), 2)
        screen.remove_node()
        self.assertEqual(len(screen.nodes), 1)

        screen.canvas.node_dropped.emit(node_id, 0.42, 0.66)
        self.assertAlmostEqual(screen.nodes[0]["pos"]["x"], 0.42)

        screen.width_spin.setValue(1600)
        screen.global_sensitivity.setValue(1.4)
        screen.save_profile()
        loaded = storage.load_control_profile("com.example.game")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.screen_contract.width, 1600)
        self.assertEqual(loaded.cursor_model.sensitivity, 1.4)
        self.assertEqual(loaded.bindings[ref].canonical_name, "Q")
        self.assertFalse(screen.editor.dirty)

    def test_key_identity_uses_codes_and_modifiers_not_text(self):
        event = _FakeKeyEvent(
            0x51, 0x11, 0x51, Qt.KeyboardModifier.ControlModifier
        )
        binding = _binding_from_qt_event(event)
        self.assertEqual(binding.canonical_name, "Q")
        self.assertEqual(binding.code, 0x11)
        self.assertEqual(binding.code_space, "qt_native_scan_code")
        self.assertEqual(binding.modifiers, ("LeftCtrl",))
        self.assertFalse(binding.is_physically_captured())


if __name__ == "__main__":
    unittest.main()
