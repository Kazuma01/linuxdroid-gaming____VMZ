"""Testes da resolução de executáveis, sem PySide6 e sem Waydroid instalado."""
import os
import tempfile
import unittest
from pathlib import Path

from linuxdroid.services.command_paths import resolve_command, system_python


class CommandPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        self.waydroid = self._fake_executable(self.bindir / "waydroid")
        self.python = self._fake_executable(self.bindir / "system-python")
        self.fake = self._fake_executable(self.bindir / "fake-tool")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _fake_executable(path):
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_waydroid_uses_resolved_python_and_binary(self):
        exe, args = resolve_command(
            "waydroid",
            ["status"],
            path_env=str(self.bindir),
            environ={"PATH": str(self.bindir)},
            system_python_override=self.python,
        )
        self.assertEqual(exe, self.python)
        self.assertEqual(args, [self.waydroid, "status"])

    def test_absolute_waydroid_path_is_respected(self):
        exe, args = resolve_command(
            self.waydroid,
            ["--version"],
            path_env="",
            environ={"PATH": ""},
            system_python_override=self.python,
        )
        self.assertEqual(exe, self.python)
        self.assertEqual(args, [self.waydroid, "--version"])

    def test_missing_waydroid_returns_no_executable(self):
        exe, args = resolve_command(
            "waydroid",
            ["status"],
            path_env=str(self.root / "vazio"),
            environ={"PATH": str(self.root / "vazio")},
            system_python_override=self.python,
        )
        self.assertIsNone(exe)
        self.assertEqual(args, ["waydroid", "status"])

    def test_regular_program_uses_path(self):
        exe, args = resolve_command(
            "fake-tool", ["--ok"], path_env=str(self.bindir), environ={"PATH": str(self.bindir)}
        )
        self.assertEqual(exe, self.fake)
        self.assertEqual(args, ["--ok"])

    def test_system_python_honours_explicit_environment_override(self):
        chosen = system_python(
            path_env=str(self.bindir),
            environ={"PATH": str(self.bindir), "LINUXDROID_SYSTEM_PYTHON": self.python},
        )
        self.assertEqual(chosen, self.python)


if __name__ == "__main__":
    unittest.main()
