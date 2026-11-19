"""Testes do parser de estado do Waydroid, sem PySide6 e sem Waydroid instalado."""
import unittest

from linuxdroid.models import WaydroidState
from linuxdroid.services.parsing import waydroid_status


class WaydroidStatusTests(unittest.TestCase):
    def test_frozen_container_is_not_running(self):
        status = waydroid_status(
            "Session:\tRUNNING\nContainer:\tFROZEN\nVendor type:\tMAINLINE\n"
        )
        self.assertIs(status.state, WaydroidState.FROZEN)
        self.assertEqual(status.session, "RUNNING")
        self.assertEqual(status.container, "FROZEN")
        self.assertIn("congelado", status.message.lower())

    def test_running_session_without_frozen_container(self):
        status = waydroid_status(
            "Session:\tRUNNING\nContainer:\tRUNNING\nVendor type:\tMAINLINE\n"
        )
        self.assertIs(status.state, WaydroidState.RUNNING)

    def test_stopped_session(self):
        status = waydroid_status("Session:\tSTOPPED\nContainer:\tSTOPPED\n")
        self.assertIs(status.state, WaydroidState.STOPPED)

    def test_not_initialized_takes_precedence(self):
        status = waydroid_status("Waydroid is not initialized\n")
        self.assertIs(status.state, WaydroidState.NOT_INITIALIZED)


if __name__ == "__main__":
    unittest.main()
