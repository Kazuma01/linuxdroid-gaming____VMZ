"""Modelos de dados simples (sem logica de interface)."""
from dataclasses import dataclass, field, asdict
from enum import Enum


class WaydroidState(Enum):
    NOT_INSTALLED = "Não instalado"
    STOPPED = "Parado"
    STARTING = "Iniciando"
    RUNNING = "Ativo"
    FROZEN = "Congelado"
    ERROR = "Erro"
    UNKNOWN = "Desconhecido"
    NOT_INITIALIZED = "Não inicializado"


@dataclass
class GameEntry:
    name: str
    package_id: str = ""
    icon_path: str = ""
    architecture: str = "unknown"      # unknown / x86_64 / arm64 / multi
    launch_method: str = "waydroid"
    notes: str = ""
    installed_status: str = "unknown"  # unknown / installed / missing
    favorite: bool = False
    category: str = ""
    # Registro do último comando de lançamento aceito — não prova jogo aberto.
    last_launched_at: str = ""
    launch_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ControlProfile:
    name: str
    keys: dict = field(default_factory=dict)  # ex.: {"Mover": "W A S D"}


@dataclass
class Settings:
    start_waydroid_with_launcher: bool = False   # opcao futura
    minimize_to_tray: bool = False               # opcional / futuro
    notifications: bool = True
    theme: str = "Dark"
    language: str = "Português (Brasil)"


@dataclass
class WaydroidStatus:
    state: WaydroidState = WaydroidState.UNKNOWN
    session: str = ""
    container: str = ""
    ip: str = ""
    message: str = ""


@dataclass
class AdbDevice:
    serial: str
    state: str
    model: str = ""
    product: str = ""


@dataclass
class CommandResult:
    program: str
    args: list = field(default_factory=list)
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return not self.error and self.exit_code == 0

    @property
    def text(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()
