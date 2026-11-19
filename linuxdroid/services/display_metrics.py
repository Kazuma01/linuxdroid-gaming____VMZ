"""Leitura da superfície Android real, sem Qt e sem alterar o sistema.

Este módulo existe para substituir o `1280x720` fixo que hoje aparece em
`MainWindow` e `ControlsScreen`. Usar a resolução errada no editor gera perfis
de controle com coordenadas normalizadas corretas, mas dimensionadas para uma
tela que não existe — o botão acaba em outro lugar.

Regras:

* somente leitura: nenhum comando altera o container, o Android ou o host;
* nenhuma dependência de PySide6;
* entrada sempre injetada (texto ou callable), para ser testável;
* se não houver medição, o resultado é marcado como NÃO MEDIDO — nunca é
  inventado um valor "parecido" e apresentado como real;

A medição em si depende de um container ativo. Congelar/descongelar é uma
operação do Runtime Manager e exige decisão explícita; este módulo apenas
interpreta a saída que recebe.
"""
from dataclasses import dataclass
import re

# Valores observados nesta máquina em medição autorizada anterior.
# São documentação, NÃO fallback silencioso: só podem ser usados se o chamador
# optar explicitamente por eles e o resultado continuar marcado como não medido.
DOCUMENTED_REFERENCE = (1920, 1034, 180, 60.0)

_SIZE_RE = re.compile(r"(\d{2,5})\s*[xX×]\s*(\d{2,5})")
_DENSITY_RE = re.compile(r"(?:density|dpi)\s*:?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_FPS_RE = re.compile(r"([\d.]+)\s*fps", re.IGNORECASE)
_REFRESH_RE = re.compile(r"refresh\s*rate\s*:?\s*([\d.]+)", re.IGNORECASE)
_WM_SIZE_RE = re.compile(
    r"(?:physical|override|real)\s+size:\s*(\d+)\s*[xX]\s*(\d+)", re.IGNORECASE
)
_WM_DENSITY_RE = re.compile(
    r"(?:physical|override|real)\s+density:\s*(\d+(?:\.\d+)?)", re.IGNORECASE
)

MIN_WIDTH, MAX_WIDTH = 320, 7680
MIN_HEIGHT, MAX_HEIGHT = 240, 4320


@dataclass(frozen=True)
class DisplayMetrics:
    """Geometria da superfície Android.

    `measured=True` significa que os valores vieram de uma saída de comando
    interpretada agora. `measured=False` significa referência documentada ou
    valor fornecido pelo usuário — a interface deve mostrar isso claramente.
    """

    width: int = 0
    height: int = 0
    dpi: int = 0
    refresh_hz: float = 0.0
    source: str = ""
    measured: bool = False
    note: str = ""

    @property
    def known(self) -> bool:
        return self.width > 0 and self.height > 0

    @property
    def label(self) -> str:
        if not self.known:
            return "resolução desconhecida"
        base = f"{self.width}×{self.height}"
        if self.refresh_hz:
            base += f" @{self.refresh_hz:g} Hz"
        if self.dpi:
            base += f", dpi {self.dpi}"
        return base

    @property
    def status_label(self) -> str:
        if not self.known:
            return "NÃO MEDIDA"
        return "MEDIDA" if self.measured else "REFERÊNCIA / MANUAL"

    def plausible(self) -> bool:
        """Faixa defensiva: livra a interface de valores absurdos."""
        return (
            MIN_WIDTH <= self.width <= MAX_WIDTH
            and MIN_HEIGHT <= self.height <= MAX_HEIGHT
        )


def _valid_size(width: int, height: int) -> bool:
    return MIN_WIDTH <= width <= MAX_WIDTH and MIN_HEIGHT <= height <= MAX_HEIGHT


def parse_wm_output(size_text: str = "", density_text: str = "") -> DisplayMetrics:
    """Interpreta `wm size` e `wm density`.

    Prefere linhas "Physical", aceita "Override"/"Real". Nunca devolve um
    tamanho inventado quando a saída não traz um par válido.
    """
    width = height = 0
    # "Override" é o valor efetivo quando existe; vem depois de "Physical" na
    # saída do `wm size`, então procurá-lo primeiro evita escolher o obsoleto.
    for keyword in ("override", "real", "physical"):
        match = re.search(
            rf"\b{keyword}\s+size:\s*(\d+)\s*[xX]\s*(\d+)", size_text or "", re.IGNORECASE
        )
        if match and _valid_size(int(match.group(1)), int(match.group(2))):
            width, height = int(match.group(1)), int(match.group(2))
            break
    if not _valid_size(width, height):
        # aceita também "1920x1034" solto, desde que passível de confiança
        loose = _SIZE_RE.search(size_text or "")
        if loose:
            width, height = int(loose.group(1)), int(loose.group(2))
    if not _valid_size(width, height):
        width = height = 0

    dpi = 0
    for keyword in ("override", "real", "physical"):
        match = re.search(
            rf"\b{keyword}\s+density:\s*(\d+(?:\.\d+)?)", density_text or "", re.IGNORECASE
        )
        if match:
            dpi = int(float(match.group(1)))
            break
    if not dpi:
        loose = re.search(r"(\d{2,3})\s*dpi", density_text or "", re.IGNORECASE)
        if loose:
            dpi = int(loose.group(1))

    return DisplayMetrics(
        width=width,
        height=height,
        dpi=dpi,
        source="wm size / wm density",
        measured=bool(width and height),
    )


def parse_dumpsys_display(text: str) -> DisplayMetrics:
    """Interpreta `dumpsys display` (DisplayDeviceInfo / DisplayInfo).

    Várias linhas podem conter resoluções diferentes (base, override, modo
    preferido). Preferimos `DisplayDeviceInfo`, que descreve a superfície
    realmente ativa; na ausência dela, usamos a primeira linha plausível.
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    candidates = []
    for index, line in enumerate(lines):
        if not _SIZE_RE.search(line):
            continue
        priority = 0
        low = line.lower()
        if "displaydeviceinfo" in low:
            priority = 3
        elif "moverridedisplayinfo" in low or "mbaseordefaultdisplayinfo" in low:
            priority = 2
        elif "displayinfo{" in low:
            priority = 1
        if priority == 0:
            continue
        size = _SIZE_RE.search(line)
        width, height = int(size.group(1)), int(size.group(2))
        if not _valid_size(width, height):
            continue
        # O dumpsys quebra linhas longas: density/fps podem estar nas linhas
        # seguintes. Procuramos adiante, mas paramos ao encontrar outro bloco
        # de DisplayInfo para não misturar atributos de telas diferentes.
        window = [line]
        for following in lines[index + 1 : index + 3]:
            candidate_low = following.lower()
            if "displaydeviceinfo" in candidate_low or "displayinfo{" in candidate_low:
                break
            window.append(following)
        context = " ".join(window)
        dpi_match = _DENSITY_RE.search(context)
        refresh_match = _FPS_RE.search(context) or _REFRESH_RE.search(context)
        dpi = int(float(dpi_match.group(1))) if dpi_match else 0
        refresh = float(refresh_match.group(1)) if refresh_match else 0.0
        candidates.append((priority, width, height, dpi, refresh, line))

    if not candidates:
        return DisplayMetrics(source="dumpsys display", note="nenhuma resolução plausível encontrada")

    # Ordena por prioridade; dentro da mesma prioridade, mantém a primeira
    # ocorrência (a ordem do dumpsys é estável entre inicializações).
    best = max(candidates, key=lambda item: item[0])
    _, width, height, dpi, refresh, _ = best
    return DisplayMetrics(
        width=width,
        height=height,
        dpi=dpi,
        refresh_hz=refresh,
        source="dumpsys display",
        measured=True,
    )


def documented_reference() -> DisplayMetrics:
    """Referência medida em 19/11/2026 nesta máquina — não é medição atual."""
    width, height, dpi, refresh = DOCUMENTED_REFERENCE
    return DisplayMetrics(
        width=width,
        height=height,
        dpi=dpi,
        refresh_hz=refresh,
        source="referência documentada (medição autorizada anterior)",
        measured=False,
        note="Valor histórico desta máquina. Não substitui medição atual.",
    )


def unknown(reason: str = "") -> DisplayMetrics:
    """Estado honesto quando não foi possível medir."""
    return DisplayMetrics(
        source="indisponível",
        measured=False,
        note=reason or "Superfície Android não medida; configure manualmente.",
    )


def merge(primary: DisplayMetrics, secondary: DisplayMetrics) -> DisplayMetrics:
    """Preenche campos ausentes da fonte principal com a secundária.

    Não promove a `measured` um valor ausente: se a principal não tem tamanho,
    o resultado herda o tamanho da secundária e o seu status de medição.
    """
    if not primary.known and secondary.known:
        return secondary
    return DisplayMetrics(
        width=primary.width or secondary.width,
        height=primary.height or secondary.height,
        dpi=primary.dpi or secondary.dpi,
        refresh_hz=primary.refresh_hz or secondary.refresh_hz,
        source=primary.source or secondary.source,
        measured=primary.measured,
        note=primary.note or secondary.note,
    )


def from_command_outputs(
    wm_size: str = "", wm_density: str = "", dumpsys_text: str = ""
) -> DisplayMetrics:
    """Compõe a geometria a partir das saídas de comandos **somente leitura**.

    `wm size`/`wm density` são a fonte primária; `dumpsys display` preenche
    campos ausentes (por exemplo, taxa de atualização). Se nenhuma saída traz
    um tamanho plausível, o resultado é `unknown()` — nunca um valor inventado.
    """
    primary = parse_wm_output(wm_size, wm_density)
    secondary = parse_dumpsys_display(dumpsys_text)
    result = merge(primary, secondary)
    if not result.known:
        return unknown("Nenhuma resolução plausível foi encontrada nas saídas dos comandos.")
    return result
