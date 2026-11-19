"""Sobre o projeto e suas integrações."""
from PySide6.QtWidgets import QVBoxLayout, QWidget
from ..widgets.common import label, title_row


class AboutScreen(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(10)
        layout.addWidget(title_row("Sobre o LinuxDroid Gaming", "Uma central de jogos Android para Linux, usando Waydroid."))
        layout.addWidget(label("Versão 0.3.1 — modo de emulador, editor visual aprimorado, screenshots de referência e perfis Phantom."))
        layout.addWidget(label("O Waydroid executa os aplicativos Android. O LinuxDroid organiza a biblioteca e controla a sessão; ele não é uma máquina virtual Android independente.", "muted"))
        layout.addWidget(label("O modo de janela única aproxima a experiência de um emulador, mas a superfície Android continua sendo uma janela do Waydroid, não um painel Qt incorporado dentro do launcher.", "muted"))
        layout.addWidget(label("O mapeamento real de teclado/mouse usa o Phantom como integração opcional. Sem o daemon ativo, o editor salva, importa e exporta perfis, mas não injeta comandos no Android.", "muted"))
        layout.addWidget(label("Compatibilidade com jogos, Google Play, Play Integrity, anti-cheat e gamepads varia conforme o jogo, a imagem Android e o hardware.", "muted"))
        layout.addStretch()
