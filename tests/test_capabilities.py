"""Testes da camada de portabilidade.

Rodar na raiz do projeto:
    PYTHONDONTWRITEBYTECODE=1 python -B -m unittest tests.test_capabilities -v

Nao precisa de PySide6, Waydroid, Phantom, sudo nem dispositivos reais.
Todas as fontes sao simuladas para provar que a logica nao depende de uma
maquina especifica.
"""
import json
import unittest

from linuxdroid.services import capabilities as cap


def make_snapshot(**overrides):
    base = dict(
        distro="Distro Teste",
        kernel="6.0-test",
        arch="x86_64",
        session_type="wayland",
        compositor="wm-teste",
        wayland_display="wayland-9",
        cpu_model="CPU Generica",
        cpu_count=4,
        memory_kib=8 * 1024 * 1024,
        gpus=[cap.GpuInfo(vendor="Intel", driver="i915")],
        input_devices=["/dev/input/event0"],
        input_readable=True,
        uinput_available=True,
        tools={
            "waydroid": "/usr/bin/waydroid",
            "adb": "/usr/bin/adb",
            "phantom": "",
            "phantom-gui": "",
            "wayland-info": "",
            "glxinfo": "",
            "vulkaninfo": "",
        },
        waydroid_version="1.6.3",
        protocols=[],
    )
    base.update(overrides)
    return cap.CapabilitySnapshot(**base)


def caps_by_name(caps):
    return {c.name: c for c in caps}


class DetectionTests(unittest.TestCase):
    def test_distro_from_os_release(self):
        text = 'NAME="X"\nPRETTY_NAME="Distro de Teste 42"\nID=x\n'
        self.assertEqual(cap.detect_distro(lambda _: text), "Distro de Teste 42")
        self.assertEqual(cap.detect_distro(lambda _: ""), "unknown")

    def test_kernel_arch_cpu_memory_injected(self):
        self.assertEqual(cap.detect_kernel("5.10-outro"), "5.10-outro")
        self.assertEqual(cap.detect_arch("aarch64"), "aarch64")
        self.assertEqual(cap.detect_cpu_count(12), 12)

        meminfo = "MemTotal:       16000000 kB\nMemFree:        1000000 kB\n"
        self.assertEqual(cap.detect_memory_kib(lambda _: meminfo), 16000000)
        self.assertEqual(cap.detect_memory_kib(lambda _: "lixo"), 0)

    def test_cpu_model_intel_arm_and_unknown(self):
        x86 = "processor : 0\nmodel name : CPU X86 Teste\n"
        arm = "processor : 0\nHardware : SOC ARM Teste\n"
        self.assertEqual(cap.detect_cpu_model(lambda _: x86), "CPU X86 Teste")
        self.assertEqual(cap.detect_cpu_model(lambda _: arm), "SOC ARM Teste")
        self.assertEqual(cap.detect_cpu_model(lambda _: ""), "unknown")

    def test_gpu_discovery_is_vendor_agnostic(self):
        paths = [
            "/sys/class/drm/card0/device/vendor",
            "/sys/class/drm/card1/device/vendor",
            "/sys/class/drm/card2/device/vendor",
        ]
        vendors = {
            paths[0]: "0x8086",
            paths[1]: "0x1002",
            paths[2]: "0xabcd",  # fabricante desconhecido na tabela
        }
        devices = {
            "/sys/class/drm/card0/device/device": "0x46b3",
            "/sys/class/drm/card1/device/device": "0x699f",
            "/sys/class/drm/card2/device/device": "0x0001",
        }

        def read(path):
            return vendors.get(path) or devices.get(path, "")

        def readlink(path):
            return "/sys/bus/pci/drivers/" + (
                "i915" if "card0" in path else "amdgpu" if "card1" in path else "generic"
            )

        gpus = cap.detect_gpus(lambda _: paths, read, readlink)
        self.assertEqual([g.vendor for g in gpus], ["Intel", "AMD", "unknown"])
        self.assertEqual(gpus[0].driver, "i915")
        self.assertEqual(gpus[1].driver, "amdgpu")
        self.assertEqual(gpus[2].vendor_id, "0xabcd")

    def test_session_variants(self):
        self.assertEqual(
            cap.detect_session({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "niri"}),
            ("wayland", "niri", ""),
        )
        self.assertEqual(
            cap.detect_session({"XDG_SESSION_TYPE": "x11", "DESKTOP_SESSION": "xfce", "WAYLAND_DISPLAY": "wayland-2"}),
            ("x11", "xfce", "wayland-2"),
        )
        self.assertEqual(cap.detect_session({}), ("unknown", "unknown", ""))

    def test_input_uinput_and_access(self):
        events = ["/dev/input/event12", "/dev/input/event3"]
        self.assertEqual(cap.detect_input_devices(lambda _: events), events)
        self.assertTrue(cap.detect_uinput(lambda p: p == "/dev/uinput"))
        self.assertFalse(cap.detect_uinput(lambda _: False))
        self.assertTrue(cap.detect_input_access(events, lambda p, m: p == "/dev/input/event3"))
        self.assertFalse(cap.detect_input_access([], lambda p, m: True))

    def test_tools_and_waydroid_version_without_running_real_command(self):
        def which(name):
            return "/usr/bin/" + name if name in ("waydroid", "adb") else None

        tools = cap.detect_tools(which)
        self.assertEqual(tools["waydroid"], "/usr/bin/waydroid")
        self.assertEqual(tools["phantom"], "")

        seen = {}

        def runner(cmd, timeout):
            seen["cmd"] = cmd
            seen["timeout"] = timeout
            return "Waydroid 1.6.3\n"

        self.assertEqual(cap.detect_waydroid_version("/usr/bin/waydroid", runner), "Waydroid 1.6.3")
        self.assertEqual(seen["cmd"], ["/usr/bin/waydroid", "--version"])
        self.assertEqual(cap.detect_waydroid_version("", runner), "unknown")
        self.assertEqual(
            cap.detect_waydroid_version("/x", lambda c, t: (_ for _ in ()).throw(OSError())),
            "unknown",
        )

    def test_parse_wayland_protocols(self):
        text = (
            "zwp_relative_pointer_manager_v1 (version 1)\n"
            "zwp_pointer_constraints_v1; other_protocol\n"
            "zwp_relative_pointer_manager_v1 (duplicado)\n"
        )
        quoted = "'zwp_pointer_constraints_v1', 'generic_pointer_v9'"
        parsed = cap.parse_wayland_protocols(text + "\n" + quoted)
        self.assertIn("zwp_relative_pointer_manager_v1", parsed)
        self.assertIn("generic_pointer_v9", parsed)
        self.assertIn("zwp_pointer_constraints_v1", parsed)
        self.assertEqual(len(parsed), 3)

    def test_collect_with_injected_sources(self):
        os_release = 'PRETTY_NAME="Sistema Ficticio"\n'
        cpuinfo = "model name : CPU de Teste\n"
        meminfo = "MemTotal:       12345678 kB\n"
        vendor_paths = ["/sys/class/drm/card0/device/vendor"]

        def read(path):
            if path == "/etc/os-release":
                return os_release
            if path == "/proc/cpuinfo":
                return cpuinfo
            if path == "/proc/meminfo":
                return meminfo
            if path == vendor_paths[0]:
                return "0x1002"
            if path == "/sys/class/drm/card0/device/device":
                return "0x699f"
            return ""

        def glob_fn(pattern):
            if "drm" in pattern:
                return vendor_paths
            return ["/dev/input/event7"]

        snapshot = cap.collect(
            env={"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "outro-wm"},
            read=read,
            glob_fn=glob_fn,
            readlink=lambda _: "/sys/bus/pci/drivers/amdgpu",
            exists=lambda p: p == "/dev/uinput",
            access=lambda p, m: True,
            which=lambda n: "/usr/bin/" + n if n in ("waydroid", "adb") else None,
            release="7.0-custom",
            machine="riscv64",
            cpu_count=16,
            version_runner=lambda c, t: "1.2.3",
            protocol_text="zwp_relative_pointer_manager_v1",
        )
        self.assertEqual(snapshot.distro, "Sistema Ficticio")
        self.assertEqual(snapshot.kernel, "7.0-custom")
        self.assertEqual(snapshot.arch, "riscv64")
        self.assertEqual(snapshot.compositor, "outro-wm")
        self.assertEqual(snapshot.cpu_model, "CPU de Teste")
        self.assertEqual(snapshot.memory_kib, 12345678)
        self.assertEqual(snapshot.gpus[0].vendor, "AMD")
        self.assertEqual(snapshot.input_devices, ["/dev/input/event7"])
        self.assertTrue(snapshot.uinput_available)
        self.assertEqual(snapshot.waydroid_version, "1.2.3")
        self.assertEqual(snapshot.protocols, ["zwp_relative_pointer_manager_v1"])

    def test_snapshot_is_json_serializable(self):
        doc = json.loads(make_snapshot().to_json())
        self.assertEqual(doc["session_type"], "wayland")
        self.assertEqual(doc["gpus"][0]["vendor"], "Intel")


class CapabilityEvaluationTests(unittest.TestCase):
    def test_evdev_states(self):
        supported = caps_by_name(cap.build_capabilities(make_snapshot()))
        self.assertEqual(supported["Captura evdev"].support, cap.Support.SUPPORTED)

        sem_leitura = caps_by_name(
            cap.build_capabilities(make_snapshot(input_readable=False))
        )
        self.assertEqual(sem_leitura["Captura evdev"].support, cap.Support.PARTIAL)

        sem_device = caps_by_name(
            cap.build_capabilities(make_snapshot(input_devices=[], input_readable=False))
        )
        self.assertEqual(sem_device["Captura evdev"].support, cap.Support.UNSUPPORTED)

    def test_protocol_states(self):
        unknown = caps_by_name(cap.build_capabilities(make_snapshot()))
        self.assertEqual(unknown["Protocolos de ponteiro"].support, cap.Support.UNKNOWN)

        parcial = caps_by_name(
            cap.build_capabilities(make_snapshot(), protocols=["zwp_relative_pointer_manager_v1"])
        )
        self.assertEqual(parcial["Protocolos de ponteiro"].support, cap.Support.PARTIAL)

        completo = caps_by_name(
            cap.build_capabilities(
                make_snapshot(),
                protocols=["zwp_relative_pointer_manager_v1", "zwp_pointer_constraints_v1"],
            )
        )
        self.assertEqual(completo["Protocolos de ponteiro"].support, cap.Support.SUPPORTED)

    def test_session_and_gpu_are_descriptive_not_prescriptive(self):
        x11 = caps_by_name(cap.build_capabilities(make_snapshot(session_type="x11", compositor="xfce")))
        self.assertEqual(x11["Sessao grafica"].support, cap.Support.PARTIAL)

        amd = caps_by_name(
            cap.build_capabilities(
                make_snapshot(gpus=[cap.GpuInfo(vendor="AMD", driver="amdgpu")])
            )
        )
        self.assertEqual(amd["Aceleracao grafica"].support, cap.Support.SUPPORTED)
        self.assertIn("AMD", amd["Aceleracao grafica"].detail)

    def test_no_fixed_resolution_assumption(self):
        for resolucao in ("1280x720", "1920x1080", "800x600"):
            snap = make_snapshot()
            caps = caps_by_name(cap.build_capabilities(snap))
            self.assertEqual(caps["Contrato de resolucao"].support, cap.Support.UNKNOWN)
            self.assertNotIn(resolucao, caps["Contrato de resolucao"].detail)

    def test_select_backend_auto_prefers_existing_phantom(self):
        tools = dict(make_snapshot().tools)
        tools["phantom"] = "/usr/local/bin/phantom"
        escolha = cap.select_backend(make_snapshot(tools=tools))
        self.assertEqual(escolha.name, "phantom")
        self.assertIn("Phantom disponivel", escolha.reason)

    def test_select_backend_native_without_phantom(self):
        escolha = cap.select_backend(make_snapshot())
        self.assertEqual(escolha.name, "native")

    def test_select_backend_native_via_android_socket_without_uinput(self):
        snap = make_snapshot(uinput_available=False)
        escolha = cap.select_backend(snap)
        self.assertEqual(escolha.name, "native")
        self.assertIn("injecao disponiveis", escolha.reason)

    def test_select_backend_unsupported_reports_blockers(self):
        snap = make_snapshot(
            input_devices=[],
            input_readable=False,
            uinput_available=False,
            tools={k: "" for k in make_snapshot().tools},
        )
        escolha = cap.select_backend(snap)
        self.assertEqual(escolha.name, "unsupported")
        self.assertIn("Captura evdev", escolha.reason)
        self.assertIn("unsupported", escolha.reason)

    def test_preferred_backend_is_not_forced_when_unavailable(self):
        escolha = cap.select_backend(make_snapshot(), preferred="phantom")
        self.assertEqual(escolha.name, "unsupported")
        self.assertIn("Nenhum backend", escolha.reason)

        snap = make_snapshot(uinput_available=False)
        escolha = cap.select_backend(snap, preferred="native")
        self.assertEqual(escolha.name, "native")


class InterfaceTests(unittest.TestCase):
    def test_abstract_interfaces_cannot_be_instantiated_incomplete(self):
        for cls in (cap.InputCaptureBackend, cap.TouchInjectBackend, cap.CursorModel):
            with self.assertRaises(TypeError):
                cls()

    def test_virtual_cursor_is_resolution_independent(self):
        cursor = cap.VirtualCursor()
        cursor.set_viewport(1280, 720)
        self.assertEqual(cursor.position(), (0.5, 0.5))

        cursor.apply_relative(1280, 720)
        self.assertEqual(cursor.position(), (1.0, 1.0))

        cursor.apply_relative(-99999, -99999)
        self.assertEqual(cursor.position(), (0.0, 0.0))

        outro = cap.VirtualCursor()
        outro.set_viewport(1920, 1080)
        outro.apply_relative(1920, 540)
        self.assertEqual(outro.position(), (1.0, 1.0))

        outro.reset()
        self.assertEqual(outro.position(), (0.5, 0.5))

    def test_unsupported_backend_fails_loudly(self):
        backend = cap.UnsupportedBackend("Waydroid ausente")
        self.assertEqual(backend.max_concurrent_touches(), 0)
        self.assertEqual(backend.describe().support, cap.Support.UNSUPPORTED)
        for acao in (
            lambda: backend.down(0.5, 0.5),
            lambda: backend.move(0.5, 0.5),
            backend.up,
            backend.release_all,
        ):
            with self.assertRaises(NotImplementedError):
                acao()


if __name__ == "__main__":
    unittest.main()
