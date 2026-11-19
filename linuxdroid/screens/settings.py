"""Tela 5: Configuracoes (opcoes de UI; nada altera o sistema)."""
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QListWidget, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import storage, theme
from ..services import system_check
from ..widgets.common import label, panel, title_row

# Cor e rotulo de cada status da checagem (as cores vem do tema do app).
STATUS_STYLE = {
    system_check.OK: (theme.GREEN, "OK"),
    system_check.WARN: (theme.AMBER, "ATENÇÃO"),
    system_check.FAIL: (theme.RED, "PROBLEMA"),
}

CATEGORIES = ["Geral", "Desempenho", "Gráficos", "Controles", "Android/Waydroid", "Armazenamento", "Avançado"]


class SettingsScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = storage.load_settings()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 16)
        outer.setSpacing(14)
        outer.addWidget(title_row("Configurações", "Algumas opções ainda são apenas visuais.", demo=True))
        outer.addWidget(label(
            "Aviso: o launcher depende de Waydroid, ADB e do kernel do seu sistema. "
            "Ele não instala nem altera nada sem a sua confirmação.", "muted"))

        body = QHBoxLayout()
        self.menu = QListWidget()
        self.menu.addItems(CATEGORIES)
        self.menu.setFixedWidth(190)
        body.addWidget(self.menu)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        # A ordem de addWidget precisa seguir a ordem de CATEGORIES.
        self.pages.addWidget(self._general_page())
        self.pages.addWidget(self._performance_page())
        for name in CATEGORIES[2:]:
            self.pages.addWidget(self._placeholder_page(name))
        self.menu.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.menu.setCurrentRow(0)

    def _general_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        s = self.settings
        for text, attr in [
            ("Iniciar Waydroid junto com o launcher (opção futura)", "start_waydroid_with_launcher"),
            ("Minimizar para a bandeja (opcional, futuro)", "minimize_to_tray"),
            ("Notificações", "notifications"),
        ]:
            cb = QCheckBox(text)
            cb.setChecked(getattr(s, attr))
            cb.toggled.connect(lambda v, a=attr: self._set(a, v))
            lay.addWidget(cb)
        lay.addWidget(label("Tema: Dark   |   Idioma: Português (Brasil)", "muted"))
        lay.addStretch()
        return w

    def _performance_page(self) -> QWidget:
        """Pagina 'Desempenho': mostra se o seu sistema atende aos requisitos do Waydroid.

        So LE informacoes do sistema; nao altera nada.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Requisitos do sistema", "h2"))
        lay.addWidget(label(
            "Verifica se o seu Linux tem o que o Waydroid precisa. "
            "Apenas leitura: nada é instalado ou alterado.", "muted"))
        self.check_summary = label("", "h2")
        lay.addWidget(self.check_summary)
        # Os resultados ficam num container que e esvaziado e preenchido a cada verificacao.
        # A QScrollArea faz a lista rolar quando a janela e baixa, em vez de espremer as linhas.
        holder = QWidget()
        self.check_box = QVBoxLayout(holder)
        self.check_box.setContentsMargins(0, 0, 0, 0)
        self.check_box.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)
        btn = QPushButton("Verificar novamente")
        btn.setObjectName("primary")
        btn.clicked.connect(self.run_checks)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)
        self.run_checks()
        return w

    def run_checks(self):
        """Roda as checagens e redesenha a lista de resultados."""
        while self.check_box.count():
            item = self.check_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        results = system_check.run_all_checks()
        for r in results:
            self.check_box.addWidget(self._result_row(r))
        overall = system_check.summarize(results)
        color, _ = STATUS_STYLE[overall]
        texts = {
            system_check.OK: "Tudo certo para rodar o Waydroid.",
            system_check.WARN: "Pode funcionar, mas há pontos de atenção.",
            system_check.FAIL: "Há problemas que impedem o Waydroid de funcionar.",
        }
        self.check_summary.setText(texts[overall])
        self.check_summary.setStyleSheet(f"color: {color};")

    def _result_row(self, r) -> QWidget:
        color, tag = STATUS_STYLE[r.status]
        card = panel("panel")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.addWidget(label(r.name, "h2"))
        badge = label(tag)
        badge.setStyleSheet(f"color: {color}; font-weight: 800; font-size: 11px;")
        head.addStretch()
        head.addWidget(badge)
        lay.addLayout(head)
        lay.addWidget(label(r.detail))
        if r.hint:
            lay.addWidget(label(r.hint, "muted"))
        return card

    def _placeholder_page(self, name: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label(f"{name}: ainda não implementado. "
                            "Nenhum ajuste será prometido até existir integração validada.", "muted"))
        lay.addStretch()
        return w

    def _set(self, attr: str, value: bool):
        setattr(self.settings, attr, value)
        storage.save_settings(self.settings)
