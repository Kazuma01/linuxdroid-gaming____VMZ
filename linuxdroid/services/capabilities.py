"""Descoberta de capacidades em tempo de execucao e interfaces abstratas.

Modulo puro: nao usa Qt, nao altera arquivos, nao executa comandos
privilegiados e NAO assume hardware, resolucao, compositor, dispositivo de
entrada, endereco IP ou caminho de instalacao. Todas as fontes de informacao
sao injetaveis para que a logica seja testavel em qualquer maquina.

Uso previsto:
    snapshot = collect()
    caps = build_capabilities(snapshot, snapshot.tools, snapshot.protocols)
    escolha = select_backend(snapshot, snapshot.tools, snapshot.protocols)

A escolha de backend e feita por capacidade observada, nunca por nome de
maquina, fabricante de GPU ou resolucao fixa.
"""
from __future__ import annotations

import glob as _glob
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable


class Support(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


# Apenas identificadores PCI genericos. Nenhuma destas entradas e usada para
# decidir comportamento: servem somente para descrever o hardware descoberto.
PCI_VENDORS = {
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x8086": "Intel",
    "0x1af4": "VirtIO",
    "0x1234": "QEMU",
}


@dataclass
class Capability:
    name: str
    support: Support
    detail: str = ""
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "support": self.support.value,
            "detail": self.detail,
            "hint": self.hint,
        }


@dataclass
class GpuInfo:
    vendor_id: str = ""
    vendor: str = "unknown"
    device_id: str = ""
    driver: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "vendor_id": self.vendor_id,
            "vendor": self.vendor,
            "device_id": self.device_id,
            "driver": self.driver,
        }


@dataclass
class CapabilitySnapshot:
    """Retrato de uma maquina. Serializavel para a matriz de compatibilidade."""

    distro: str = "unknown"
    kernel: str = "unknown"
    arch: str = "unknown"
    session_type: str = "unknown"
    compositor: str = "unknown"
    wayland_display: str = ""
    cpu_model: str = "unknown"
    cpu_count: int = 0
    memory_kib: int = 0
    gpus: list[GpuInfo] = field(default_factory=list)
    input_devices: list[str] = field(default_factory=list)
    input_readable: bool = False
    uinput_available: bool = False
    tools: dict[str, str] = field(default_factory=dict)
    waydroid_version: str = "unknown"
    protocols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "distro": self.distro,
            "kernel": self.kernel,
            "arch": self.arch,
            "session_type": self.session_type,
            "compositor": self.compositor,
            "wayland_display": self.wayland_display,
            "cpu_model": self.cpu_model,
            "cpu_count": self.cpu_count,
            "memory_kib": self.memory_kib,
            "gpus": [g.to_dict() for g in self.gpus],
            "input_devices": list(self.input_devices),
            "input_readable": self.input_readable,
            "uinput_available": self.uinput_available,
            "tools": dict(self.tools),
            "waydroid_version": self.waydroid_version,
            "protocols": list(self.protocols),
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


@dataclass
class BackendChoice:
    name: str  # phantom | native | unsupported
    reason: str
    capabilities: list[Capability] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "reason": self.reason,
            "capabilities": [c.to_dict() for c in self.capabilities],
        }


# ---------------------------------------------------------------------------
# Fontes de informacao (injetaveis)
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def detect_distro(read: Callable[[str], str] = _read) -> str:
    for line in read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            value = line.split("=", 1)[1].strip().strip('"')
            return value or "unknown"
    return "unknown"


def detect_kernel(release: str | None = None) -> str:
    if release is None:
        try:
            release = os.uname().release
        except OSError:
            release = _read("/proc/sys/kernel/osrelease").strip()
    return release or "unknown"


def detect_arch(machine: str | None = None) -> str:
    if machine is None:
        try:
            machine = os.uname().machine
        except OSError:
            machine = ""
    return machine or "unknown"


def detect_cpu_model(read: Callable[[str], str] = _read) -> str:
    text = read("/proc/cpuinfo")
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip() or "unknown"
    # ARM e algumas SOCs nao trazem "model name".
    for key in ("Hardware", "Processor", "cpu model"):
        for line in text.splitlines():
            if line.lower().startswith(key.lower()):
                return line.split(":", 1)[1].strip() or "unknown"
    return "unknown"


def detect_cpu_count(count: int | None = None) -> int:
    if count is None:
        count = os.cpu_count() or 0
    return int(count)


def detect_memory_kib(read: Callable[[str], str] = _read) -> int:
    for line in read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return 0
    return 0


def detect_gpus(
    glob_fn: Callable[[str], Iterable[str]] = _glob.glob,
    read: Callable[[str], str] = _read,
    readlink: Callable[[str], str] = os.readlink,
    vendors: dict[str, str] | None = None,
) -> list[GpuInfo]:
    """Descobre GPUs por sysfs. Nao usa lspci, sudo nem nomes fixos de device."""
    vendors = PCI_VENDORS if vendors is None else vendors
    found: list[GpuInfo] = []
    for vendor_path in sorted(glob_fn("/sys/class/drm/card[0-9]*/device/vendor")):
        # vendor_path termina em /device/vendor: o diretorio PCI e o proprio pai.
        pci_dir = vendor_path[: -len("vendor")]
        vendor_id = read(vendor_path).strip().lower()
        info = GpuInfo(
            vendor_id=vendor_id,
            vendor=vendors.get(vendor_id, "unknown"),
            device_id=read(pci_dir + "device").strip().lower(),
        )
        try:
            info.driver = os.path.basename(readlink(pci_dir + "driver"))
        except OSError:
            pass
        if info not in found:
            found.append(info)
    return found


def detect_session(env: dict[str, str] | None = None) -> tuple[str, str, str]:
    env = os.environ if env is None else env
    session = (env.get("XDG_SESSION_TYPE") or "unknown").lower()
    compositor = (
        env.get("XDG_CURRENT_DESKTOP")
        or env.get("DESKTOP_SESSION")
        or "unknown"
    ).lower()
    return session, compositor, (env.get("WAYLAND_DISPLAY") or "")


def detect_input_devices(glob_fn: Callable[[str], Iterable[str]] = _glob.glob) -> list[str]:
    return sorted(glob_fn("/dev/input/event*"))


def detect_uinput(exists: Callable[[str], bool] = os.path.exists) -> bool:
    return any(exists(path) for path in ("/dev/uinput", "/dev/input/uinput"))


def detect_input_access(
    event_paths: Iterable[str],
    access: Callable[[str, int], bool] = os.access,
) -> bool:
    return any(access(path, os.R_OK) for path in event_paths)


def detect_tools(which: Callable[[str], str | None] = shutil.which) -> dict[str, str]:
    names = ("waydroid", "adb", "phantom", "phantom-gui", "wayland-info", "glxinfo", "vulkaninfo")
    return {name: which(name) or "" for name in names}


def detect_waydroid_version(
    path: str,
    runner: Callable[[list[str], int], str] | None = None,
) -> str:
    """Executa somente `waydroid --version` (leitura, sem sudo e sem estado)."""
    if not path:
        return "unknown"

    def default_run(cmd: list[str], timeout: int) -> str:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (result.stdout or result.stderr).strip()

    fn = runner if runner is not None else default_run
    try:
        output = fn([path, "--version"], 5)
        return output.splitlines()[0] if output else "unknown"
    except Exception:
        return "unknown"


def parse_wayland_protocols(text: str) -> list[str]:
    """Extrai nomes de protocolos com 'pointer' de saida de wayland-info."""
    names: list[str] = []
    for line in text.splitlines():
        for token in line.replace(",", " ").split():
            name = token.strip().strip("'\"").rstrip(";,()")
            # O token generico "pointer" e a interface wl_pointer, nao um
            # protocolo de relative/constraints; nao deve poluir a descoberta.
            if "pointer" in name.lower() and name.lower() != "pointer" and name not in names:
                names.append(name)
    return names


def collect(
    env: dict[str, str] | None = None,
    read: Callable[[str], str] = _read,
    glob_fn: Callable[[str], Iterable[str]] = _glob.glob,
    readlink: Callable[[str], str] = os.readlink,
    exists: Callable[[str], bool] = os.path.exists,
    access: Callable[[str, int], bool] = os.access,
    which: Callable[[str], str | None] = shutil.which,
    release: str | None = None,
    machine: str | None = None,
    cpu_count: int | None = None,
    version_runner: Callable[[list[str], int], str] | None = None,
    protocol_text: str | None = None,
) -> CapabilitySnapshot:
    """Coleta o que esta disponivel. Nunca lanca excecao por hardware ausente."""
    session, compositor, display = detect_session(env)
    tools = detect_tools(which)
    events = detect_input_devices(glob_fn)
    return CapabilitySnapshot(
        distro=detect_distro(read),
        kernel=detect_kernel(release),
        arch=detect_arch(machine),
        session_type=session,
        compositor=compositor,
        wayland_display=display,
        cpu_model=detect_cpu_model(read),
        cpu_count=detect_cpu_count(cpu_count),
        memory_kib=detect_memory_kib(read),
        gpus=detect_gpus(glob_fn, read, readlink),
        input_devices=list(events),
        input_readable=detect_input_access(events, access),
        uinput_available=detect_uinput(exists),
        tools=tools,
        waydroid_version=detect_waydroid_version(tools.get("waydroid", ""), version_runner),
        protocols=parse_wayland_protocols(protocol_text) if protocol_text is not None else [],
    )


# ---------------------------------------------------------------------------
# Avaliacao e selecao por capacidade
# ---------------------------------------------------------------------------


def build_capabilities(
    snapshot: CapabilitySnapshot,
    tools: dict[str, str] | None = None,
    protocols: Iterable[str] | None = None,
) -> list[Capability]:
    tools = snapshot.tools if tools is None else tools
    protocols = snapshot.protocols if protocols is None else list(protocols)
    caps: list[Capability] = []

    if snapshot.session_type == "wayland":
        caps.append(Capability("Sessao grafica", Support.SUPPORTED, "Wayland detectado."))
    elif snapshot.session_type == "x11":
        caps.append(
            Capability(
                "Sessao grafica", Support.PARTIAL, "X11 detectado.",
                "Waydroid prefere Wayland; use compositor Wayland aninhado.",
            )
        )
    else:
        caps.append(
            Capability(
                "Sessao grafica", Support.UNKNOWN, "Tipo de sessao nao identificado.",
                "Verifique XDG_SESSION_TYPE.",
            )
        )

    if snapshot.input_devices and snapshot.input_readable:
        caps.append(
            Capability(
                "Captura evdev", Support.SUPPORTED,
                f"{len(snapshot.input_devices)} dispositivo(s) event* legivel(is).",
            )
        )
    elif snapshot.input_devices:
        caps.append(
            Capability(
                "Captura evdev", Support.PARTIAL,
                "Dispositivos encontrados, leitura negada.",
                "Verifique permissoes/grupo na sessao atual; nao alterar sem autorizacao.",
            )
        )
    else:
        caps.append(
            Capability(
                "Captura evdev", Support.UNSUPPORTED,
                "Nenhum /dev/input/event* encontrado.",
                "Captura global exigira outro mecanismo.",
            )
        )

    if snapshot.uinput_available:
        caps.append(Capability("Dispositivo uinput", Support.SUPPORTED, "/dev/uinput disponivel."))
    else:
        caps.append(
            Capability(
                "Dispositivo uinput", Support.UNSUPPORTED,
                "/dev/uinput ausente.",
                "Backend uinput indisponivel nesta maquina.",
            )
        )

    if tools.get("waydroid") and tools.get("adb"):
        caps.append(
            Capability(
                "Injecao Android", Support.PARTIAL,
                "Waydroid e ADB presentes; servidor Android nao verificado.",
                "Validar servidor/jar antes de usar injecao real.",
            )
        )
    elif tools.get("waydroid"):
        caps.append(
            Capability(
                "Injecao Android", Support.PARTIAL,
                "Waydroid presente; ADB ausente.",
                "Instalar/ativar ADB pode ser necessario.",
            )
        )
    else:
        caps.append(
            Capability(
                "Injecao Android", Support.UNSUPPORTED,
                "Waydroid nao encontrado no PATH.",
                "Instale o Waydroid para injetar toques Android.",
            )
        )

    if tools.get("phantom"):
        caps.append(
            Capability(
                "Backend Phantom", Support.SUPPORTED,
                f"Phantom encontrado em {tools['phantom']}.",
            )
        )
    else:
        caps.append(
            Capability(
                "Backend Phantom", Support.UNSUPPORTED,
                "Phantom nao encontrado no PATH.",
                "Instale separadamente se desejar usar este backend.",
            )
        )

    if not protocols:
        caps.append(
            Capability(
                "Protocolos de ponteiro", Support.UNKNOWN,
                "Nao medidos nesta execucao.",
                "Medir com wayland-info na sessao real antes de decidir.",
            )
        )
    else:
        has_relative = any("relative" in p.lower() for p in protocols)
        has_constraint = any(
            "constraint" in p.lower() or "lock" in p.lower() for p in protocols
        )
        if has_relative and has_constraint:
            caps.append(
                Capability(
                    "Protocolos de ponteiro", Support.SUPPORTED,
                    "relative pointer e pointer constraints anunciados.",
                    "Ainda exige teste de foco no compositor real.",
                )
            )
        elif has_relative or has_constraint:
            caps.append(
                Capability(
                    "Protocolos de ponteiro", Support.PARTIAL,
                    "Apenas parte dos protocolos de ponteiro disponivel.",
                    "Comportamento de mira pode exigir evdev/uinput.",
                )
            )
        else:
            caps.append(
                Capability(
                    "Protocolos de ponteiro", Support.UNSUPPORTED,
                    "Sem protocolos relativos/constraints anunciados.",
                    "Mouse relativo dependera de evdev/uinput.",
                )
            )

    # Nenhuma resolucao e assumida pelo codigo. Esta capacidade existe para
    # impedir que um perfil de outra maquina seja ativado sem medicao.
    caps.append(
        Capability(
            "Contrato de resolucao", Support.UNKNOWN,
            "Nenhuma resolucao fixa e assumida pelo codigo.",
            "Medir a superficie Android antes de gerar toques.",
        )
    )

    known_gpus = [g for g in snapshot.gpus if g.vendor != "unknown"]
    if known_gpus:
        nomes = ", ".join(sorted({g.vendor for g in known_gpus}))
        caps.append(Capability("Aceleracao grafica", Support.SUPPORTED, f"GPU(s): {nomes}."))
    else:
        caps.append(
            Capability(
                "Aceleracao grafica", Support.UNKNOWN,
                "GPU nao identificada.",
                "Hint: renderizacao por software pode ser lenta.",
            )
        )

    return caps


def select_backend(
    snapshot: CapabilitySnapshot,
    tools: dict[str, str] | None = None,
    protocols: Iterable[str] | None = None,
    preferred: str = "auto",
) -> BackendChoice:
    """Escolhe backend por capacidade observada, nunca por identidade da maquina."""
    caps = build_capabilities(snapshot, tools, protocols)
    by_name = {cap.name.strip(): cap for cap in caps}

    phantom_ok = by_name["Backend Phantom"].support == Support.SUPPORTED
    capture_ok = by_name["Captura evdev"].support == Support.SUPPORTED
    uinput_ok = by_name["Dispositivo uinput"].support == Support.SUPPORTED
    android_ok = by_name["Injecao Android"].support in (Support.SUPPORTED, Support.PARTIAL)
    native_ok = capture_ok and (uinput_ok or android_ok)

    if preferred == "phantom" and phantom_ok:
        return BackendChoice("phantom", "Backend Phantom solicitado e disponivel.", caps)
    if preferred == "native" and native_ok:
        return BackendChoice("native", "Backend nativo solicitado e viavel.", caps)
    if preferred == "auto":
        if phantom_ok:
            return BackendChoice("phantom", "Phantom disponivel; manter backend existente.", caps)
        if native_ok:
            return BackendChoice("native", "Captura evdev e injecao disponiveis.", caps)

    bloqueios = [
        f"{cap.name}: {cap.support.value}"
        for cap in caps
        if cap.support in (Support.UNSUPPORTED, Support.UNKNOWN)
    ]
    return BackendChoice(
        "unsupported",
        "Nenhum backend atende aos requisitos nesta maquina. " + "; ".join(bloqueios),
        caps,
    )


# ---------------------------------------------------------------------------
# Interfaces abstratas para componentes dependentes de hardware
# ---------------------------------------------------------------------------


class InputCaptureBackend(ABC):
    """Captura eventos fisicos. Implementacao concreta nao depende de evento fixo."""

    @abstractmethod
    def start(self) -> None:
        """Inicia a captura. Nao deve elevar privilegios automaticamente."""

    @abstractmethod
    def stop(self) -> None:
        """Libera a captura e todos os grabs."""

    @abstractmethod
    def read_events(self) -> Iterable[dict]:
        """Devolve eventos normalizados, nao crus, para desacoplar o runtime."""

    @abstractmethod
    def describe(self) -> Capability:
        """Descreve o que este backend consegue fazer agora."""


class TouchInjectBackend(ABC):
    """Injeta toques em coordenadas normalizadas 0..1."""

    @abstractmethod
    def down(self, x: float, y: float, slot: int = 0) -> None:
        ...

    @abstractmethod
    def move(self, x: float, y: float, slot: int = 0) -> None:
        ...

    @abstractmethod
    def up(self, slot: int = 0) -> None:
        ...

    @abstractmethod
    def release_all(self) -> None:
        ...

    @abstractmethod
    def max_concurrent_touches(self) -> int:
        ...

    @abstractmethod
    def describe(self) -> Capability:
        ...


class CursorModel(ABC):
    """Cursor virtual independente do ponteiro do compositor."""

    @abstractmethod
    def set_viewport(self, width: float, height: float) -> None:
        ...

    @abstractmethod
    def apply_relative(self, dx: float, dy: float, sensitivity: float = 1.0) -> None:
        ...

    @abstractmethod
    def position(self) -> tuple[float, float]:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...


class UnsupportedBackend(TouchInjectBackend):
    """Fallback explicito: falha com mensagem clara, nunca silenciosamente."""

    def __init__(self, reason: str):
        self.reason = reason

    def _fail(self) -> None:
        raise NotImplementedError(f"Backend de toque nao suportado: {self.reason}")

    def down(self, x: float, y: float, slot: int = 0) -> None:
        self._fail()

    def move(self, x: float, y: float, slot: int = 0) -> None:
        self._fail()

    def up(self, slot: int = 0) -> None:
        self._fail()

    def release_all(self) -> None:
        self._fail()

    def max_concurrent_touches(self) -> int:
        return 0

    def describe(self) -> Capability:
        return Capability("Backend de toque", Support.UNSUPPORTED, self.reason)


class BackendStage(str, Enum):
    """Estados separados: presenca nao implica funcionamento."""

    UNSUPPORTED = "unsupported"
    DETECTED = "detected"
    DEPENDENCIES_MISSING = "dependencies_missing"
    PREREQUISITES_MISSING = "prerequisites_missing"
    AVAILABLE = "available"
    TESTED = "tested"
    OPERATIONAL = "operational"


@dataclass
class BackendReadiness:
    """Retrato honesto de um backend candidato."""

    name: str
    stage: BackendStage
    detected: bool = False
    dependencies_available: bool = False
    prerequisites_met: bool = False
    initialization_possible: bool = False
    functional: bool = False
    tested: bool = False
    operational: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "stage": self.stage.value,
            "detected": self.detected,
            "dependencies_available": self.dependencies_available,
            "prerequisites_met": self.prerequisites_met,
            "initialization_possible": self.initialization_possible,
            "functional": self.functional,
            "tested": self.tested,
            "operational": self.operational,
            "reason": self.reason,
        }


@dataclass
class BackendDecision:
    """ Escolha de backend com prontidao explicita e mensagem ao usuario."""

    choice: BackendChoice
    readiness: BackendReadiness
    message: str

    def to_dict(self) -> dict:
        return {
            "choice": self.choice.to_dict(),
            "readiness": self.readiness.to_dict(),
            "message": self.message,
        }


def assess_backend(
    name: str,
    snapshot: CapabilitySnapshot,
    tools: dict[str, str] | None = None,
    protocols: Iterable[str] | None = None,
    *,
    tested: bool = False,
    operational: bool = False,
) -> BackendReadiness:
    """Avalia um backend sem transformar deteccao em funcionalidade."""
    tools = snapshot.tools if tools is None else tools
    if name == "phantom":
        detected = bool(tools.get("phantom"))
        dependencies = detected
        prerequisites = detected
    elif name == "native":
        caps = {cap.name: cap for cap in build_capabilities(snapshot, tools, protocols)}
        detected = caps["Captura evdev"].support != Support.UNSUPPORTED
        dependencies = caps["Dispositivo uinput"].support == Support.SUPPORTED or caps["Injecao Android"].support in (Support.SUPPORTED, Support.PARTIAL)
        prerequisites = detected and dependencies
    elif name == "recording":
        detected = True
        dependencies = True
        prerequisites = True
    else:
        return BackendReadiness(name, BackendStage.UNSUPPORTED, reason="Backend desconhecido.")

    if not detected:
        stage = BackendStage.UNSUPPORTED
        reason = "Backend nao detectado nesta maquina."
    elif not dependencies:
        stage = BackendStage.DEPENDENCIES_MISSING
        reason = "Dependencias ausentes; backend nao pode ser inicializado."
    elif not prerequisites:
        stage = BackendStage.PREREQUISITES_MISSING
        reason = "Pre-requisitos nao atendidos."
    elif operational and tested:
        stage = BackendStage.OPERATIONAL
        reason = "Backend testado e operacional em captura/injecao real."
    elif tested:
        stage = BackendStage.TESTED
        reason = "Backend testado; operacionalidade ainda nao confirmada."
    else:
        stage = BackendStage.AVAILABLE
        reason = "Inicializacao possivel; NADA foi testado ou injetado."

    return BackendReadiness(
        name=name,
        stage=stage,
        detected=detected,
        dependencies_available=dependencies,
        prerequisites_met=prerequisites,
        initialization_possible=prerequisites,
        functional=False,
        tested=bool(tested and prerequisites),
        operational=bool(operational and tested and prerequisites),
        reason=reason,
    )


def select_backend_detailed(
    snapshot: CapabilitySnapshot,
    tools: dict[str, str] | None = None,
    protocols: Iterable[str] | None = None,
    preferred: str = "auto",
    *,
    tested: bool = False,
    operational: bool = False,
) -> BackendDecision:
    """Seleciona candidato e informa explicitamente o que falta para uso real."""
    choice = select_backend(snapshot, tools, protocols, preferred)
    if choice.name == "unsupported":
        readiness = BackendReadiness(
            preferred,
            BackendStage.UNSUPPORTED,
            reason=choice.reason,
        )
        return BackendDecision(choice, readiness, choice.reason)

    readiness = assess_backend(
        choice.name, snapshot, tools, protocols, tested=tested, operational=operational
    )
    if readiness.stage == BackendStage.OPERATIONAL:
        message = f"{choice.name}: operacional apos teste real."
    elif readiness.stage == BackendStage.TESTED:
        message = f"{choice.name}: testado, mas ainda nao declarado operacional."
    else:
        message = (
            f"{choice.name}: candidato {readiness.stage.value}; "
            "captura/injecao reais NAO foram testadas nesta operacao."
        )
    return BackendDecision(choice, readiness, message)


@dataclass
class VirtualCursor(CursorModel):
    """Cursor virtual portatil: sempre normalizado, nunca ligado a uma resolucao."""

    width: float = 1.0
    height: float = 1.0
    x: float = field(default=0.5, init=False)
    y: float = field(default=0.5, init=False)

    def set_viewport(self, width: float, height: float) -> None:
        self.width = max(1e-6, float(width))
        self.height = max(1e-6, float(height))
        self.reset()

    def apply_relative(self, dx: float, dy: float, sensitivity: float = 1.0) -> None:
        step_x = (float(dx) * float(sensitivity)) / self.width
        step_y = (float(dy) * float(sensitivity)) / self.height
        self.x = min(1.0, max(0.0, self.x + step_x))
        self.y = min(1.0, max(0.0, self.y + step_y))

    def position(self) -> tuple[float, float]:
        return (self.x, self.y)

    def reset(self) -> None:
        self.x = 0.5
        self.y = 0.5
