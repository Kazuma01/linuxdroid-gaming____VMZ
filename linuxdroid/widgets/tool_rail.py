"""Barra lateral direita de ferramentas.

Regra de honestidade (docs/UI_DESIGN_SPEC.md §3.4): ferramenta sem backend
real aparece desabilitada e com tooltip que diz por quê. Este módulo não chama
Waydroid nem ADB: apenas emite a intenção ``tool_requested`` para a janela.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QPushButton, QVBoxLayout

from ..models import WaydroidState

__all__ = ["ToolRail", "TOOLS"]


# (chave, rótulo curto, grupo, descrição/estado)
TOOLS = (
    ("home", "Home", "Navegação", "NÃO IMPLEMENTADO: keycode depende de captura real validada."),
    ("back", "Voltar", "Navegação", "NÃO IMPLEMENTADO: keycode depende de captura real validada."),
    ("recents", "Recentes", "Navegação", "NÃO IMPLEMENTADO: keycode depende de captura real validada."),
    ("fullscreen", "Tela cheia", "Tela", "Traz a superfície Android para a frente; exige Android ativo."),
    ("lock_cursor", "Cursor", "Tela", "NÃO IMPLEMENTADO: captura real de ponteiro não foi validada."),
    ("screenshot", "Captura", "Mídia", "NÃO IMPLEMENTADO: captura de tela real não existe."),
    ("recording", "Gravar", "Mídia", "NÃO IMPLEMENTADO: gravação real não existe."),
    ("media_folder", "Mídia", "Mídia", "NÃO IMPLEMENTADO: pasta de mídia não foi integrada."),
    ("controls", "Controles", "Jogo", "Abre o editor de controles (implementado)."),
    ("macros", "Macro", "Jogo", "NÃO IMPLEMENTADO: macroRuntime está desabilitado."),
    ("performance", "FPS", "Jogo", "NÃO IMPLEMENTADO: medição de desempenho não existe."),
    ("restart_app", "Reabrir", "Jogo", "Reenvia o comando de abertura do último jogo aceito."),
    ("install", "Instalar", "Sistema", "Abre a Central Android para instalar APK/XAPK (implementado)."),
    ("volume", "Volume", "Sistema", "NÃO IMPLEMENTADO: controle de volume do Android não foi integrado."),
    ("airplane", "Avião", "Sistema", "NÃO IMPLEMENTADO: alternância de rede não foi integrada."),
    ("multi_instance", "Instâncias", "Sistema", "NÃO IMPLEMENTADO: prova de isolamento não foi feita."),
    ("eco", "Eco", "Sistema", "NÃO IMPLEMENTADO: modo Eco não foi integrado."),
    ("adb", "ADB", "Avançado", "Abre a Central Android (implementado; conexão exige autorização no Android)."),
    ("settings", "Ajustes", "Avançado", "Abre Configurações (implementado)."),
)

ALWAYS_DISABLED = frozenset(
    tool[0] for tool in TOOLS if tool[3].startswith("NÃO IMPLEMENTADO")
)
CONTEXT_DISABLED = frozenset({"fullscreen", "restart_app"})


class ToolRail(QFrame):
    """Trilho vertical com intenções de ferramenta; sem efeitos colaterais."""

    tool_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("toolRail")
        self.buttons: dict[str, QPushButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(5)
        last_group = None
        for key, text, group, description in TOOLS:
            if group != last_group:
                last_group = group
            button = QPushButton(text)
            button.setObjectName(f"tool_{key}")
            button.setToolTip(f"{group}: {description}")
            button.setEnabled(key not in ALWAYS_DISABLED and key not in CONTEXT_DISABLED)
            button.clicked.connect(lambda _checked=False, k=key: self.tool_requested.emit(k))
            self.buttons[key] = button
            layout.addWidget(button)
        layout.addStretch()
        self._state = WaydroidState.UNKNOWN
        self._has_last_game = False
        self._refresh()

    def set_runtime_state(self, state: WaydroidState) -> None:
        self._state = state
        self._refresh()

    def set_last_game(self, has_game: bool) -> None:
        self._has_last_game = bool(has_game)
        self._refresh()

    def _refresh(self) -> None:
        active = self._state is WaydroidState.RUNNING
        self.buttons["fullscreen"].setEnabled(active)
        self.buttons["restart_app"].setEnabled(active and self._has_last_game)
