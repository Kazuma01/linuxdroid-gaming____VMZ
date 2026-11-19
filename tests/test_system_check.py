"""Testes da checagem de requisitos. Rodar na raiz do projeto:
    python -m unittest tests.test_system_check -v
Nao precisa de PySide6 nem de Waydroid instalado."""
import unittest

from linuxdroid.services import system_check as sc


class SystemCheckTests(unittest.TestCase):
    def test_wayland_ok(self):
        self.assertEqual(sc.check_session({"XDG_SESSION_TYPE": "wayland"}).status, sc.OK)

    def test_x11_warns(self):
        self.assertEqual(sc.check_session({"XDG_SESSION_TYPE": "x11"}).status, sc.WARN)

    def test_unknown_session_warns(self):
        self.assertEqual(sc.check_session({}).status, sc.WARN)

    def test_waydroid_missing_fails(self):
        self.assertEqual(sc.check_waydroid_installed(lambda _: None).status, sc.FAIL)

    def test_waydroid_found_ok(self):
        self.assertEqual(sc.check_waydroid_installed(lambda _: "/usr/bin/waydroid").status, sc.OK)

    def test_binder_module_loaded(self):
        r = sc.check_binder("binder_linux 262144 0 - Live 0x0\n", exists=lambda p: False)
        self.assertEqual(r.status, sc.OK)

    def test_binder_node_exists(self):
        r = sc.check_binder("", exists=lambda p: p == "/dev/binderfs/binder")
        self.assertEqual(r.status, sc.OK)

    def test_binder_absent_fails(self):
        r = sc.check_binder("", exists=lambda p: False)
        self.assertIn(r.status, (sc.FAIL, sc.WARN))

    def test_gpu_nvidia_only_warns(self):
        self.assertEqual(sc.check_gpu(["NVIDIA"]).status, sc.WARN)

    def test_gpu_amd_ok_and_intel_nvidia_ok(self):
        self.assertEqual(sc.check_gpu(["AMD"]).status, sc.OK)
        self.assertEqual(sc.check_gpu(["Intel", "NVIDIA"]).status, sc.OK)

    def test_gpu_none_warns(self):
        self.assertEqual(sc.check_gpu([]).status, sc.WARN)

    def test_memory(self):
        self.assertEqual(sc.check_memory("MemTotal:       16000000 kB\n").status, sc.OK)
        self.assertEqual(sc.check_memory("MemTotal:        2000000 kB\n").status, sc.WARN)
        self.assertEqual(sc.check_memory("lixo").status, sc.WARN)

    def test_cpu(self):
        self.assertEqual(sc.check_cpu(8).status, sc.OK)
        self.assertEqual(sc.check_cpu(1).status, sc.WARN)

    def test_input_no_devices(self):
        self.assertEqual(sc.check_input_access([]).status, sc.WARN)

    def test_input_denied_not_in_group(self):
        r = sc.check_input_access(["/dev/input/inexistente"], group_names=[])
        self.assertEqual(r.status, sc.WARN)
        self.assertIn("usermod", r.hint)

    def test_summarize_picks_worst(self):
        ok = sc.CheckResult("a", sc.OK, "")
        warn = sc.CheckResult("b", sc.WARN, "")
        fail = sc.CheckResult("c", sc.FAIL, "")
        self.assertEqual(sc.summarize([ok]), sc.OK)
        self.assertEqual(sc.summarize([ok, warn]), sc.WARN)
        self.assertEqual(sc.summarize([ok, warn, fail]), sc.FAIL)

    def test_run_all_does_not_crash(self):
        results = sc.run_all_checks()
        self.assertEqual(len(results), 7)
        for r in results:
            self.assertIn(r.status, (sc.OK, sc.WARN, sc.FAIL))


if __name__ == "__main__":
    unittest.main()
