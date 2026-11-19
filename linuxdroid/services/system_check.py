"""Checagem dos requisitos do sistema para rodar o Waydroid.

Este modulo e "puro": nao usa Qt e so LE informacoes do sistema (arquivos em
/proc, /sys, /dev e variaveis de ambiente). Nada e alterado, e nenhum comando
com sudo e executado. Por nao depender da interface, ele pode ser testado sozinho.

Cada checagem devolve um CheckResult com um status:
  ok   - tudo certo
  warn - pode funcionar, mas ha um risco ou limitacao
  fail - muito provavelmente nao vai funcionar sem corrigir
"""
import glob
import grp
import os
import shutil
from dataclasses import dataclass

OK, WARN, FAIL = "ok", "warn", "fail"

# Vendor IDs PCI que aparecem em /sys/class/drm/card*/device/vendor
GPU_VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}

MIN_RAM_GB = 4.0
MIN_CPUS = 2


@dataclass
class CheckResult:
    name: str
    status: str          # ok / warn / fail
    detail: str          # o que foi encontrado
    hint: str = ""       # o que fazer para corrigir (vazio se esta ok)


def _read(path: str) -> str:
    """Le um arquivo de texto; devolve '' se nao existir ou nao der para ler."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def check_session(env=None) -> CheckResult:
    """O Waydroid foi feito para Wayland. Em X11 so funciona com gambiarras."""
    env = os.environ if env is None else env
    session = (env.get("XDG_SESSION_TYPE") or "").lower()
    if session == "wayland" or env.get("WAYLAND_DISPLAY"):
        return CheckResult("Sessão gráfica", OK, "Wayland detectado.")
    if session == "x11":
        return CheckResult(
            "Sessão gráfica", WARN, "Sessão X11 detectada.",
            "O Waydroid funciona melhor em Wayland. Em X11 é preciso um compositor "
            "Wayland aninhado (ex.: weston ou cage). Prefira entrar numa sessão Wayland.")
    return CheckResult("Sessão gráfica", WARN, "Não foi possível identificar a sessão.",
                       "Confira a variável XDG_SESSION_TYPE.")


def check_waydroid_installed(which=shutil.which) -> CheckResult:
    path = which("waydroid")
    if path:
        return CheckResult("Waydroid instalado", OK, f"Encontrado em {path}.")
    return CheckResult("Waydroid instalado", FAIL, "Comando 'waydroid' não encontrado no PATH.",
                       "Instale o Waydroid pela documentação oficial da sua distribuição.")


def check_binder(modules_text=None, exists=os.path.exists) -> CheckResult:
    """O Android precisa do 'binder' (comunicacao entre processos) no kernel.

    Ele pode vir como modulo (binder_linux), embutido no kernel, ou como
    binderfs montado em /dev/binderfs.
    """
    if modules_text is None:
        modules_text = _read("/proc/modules")
    filesystems = _read("/proc/filesystems")
    has_module = any(line.split()[0] == "binder_linux" for line in modules_text.splitlines() if line.strip())
    has_binderfs = "binder" in filesystems
    has_node = exists("/dev/binderfs/binder") or exists("/dev/binder")
    if has_module or has_node:
        return CheckResult("Kernel: binder", OK, "Suporte a binder ativo.")
    if has_binderfs or exists("/sys/module/binder_linux"):
        return CheckResult(
            "Kernel: binder", WARN, "O kernel tem suporte, mas o binder não está carregado.",
            "Carregue o módulo com: sudo modprobe binder_linux devices=binder,hwbinder,vndbinder")
    return CheckResult(
        "Kernel: binder", FAIL, "Binder não encontrado neste kernel.",
        "Use um kernel com binder (ex.: linux-zen ou linux-cachyos) ou instale o módulo binder_linux.")


def detect_gpus(drm_glob="/sys/class/drm/card[0-9]*/device/vendor") -> list:
    """Devolve a lista de fabricantes de GPU encontrados (sem repetir)."""
    found = []
    for path in sorted(glob.glob(drm_glob)):
        name = GPU_VENDORS.get(_read(path).strip().lower())
        if name and name not in found:
            found.append(name)
    return found


def check_gpu(vendors=None) -> CheckResult:
    vendors = detect_gpus() if vendors is None else vendors
    if not vendors:
        return CheckResult("GPU", WARN, "Não foi possível identificar a GPU.",
                           "Sem aceleração gráfica o Android roda por software, bem mais lento.")
    label = ", ".join(vendors)
    if vendors == ["NVIDIA"]:
        return CheckResult(
            "GPU", WARN, f"Apenas GPU {label}.",
            "O Waydroid tem suporte limitado a NVIDIA com driver proprietário. "
            "Se o vídeo falhar, ative a renderização por software (ro.hardware.gralloc=default).")
    return CheckResult("GPU", OK, f"{label} detectada(s).")


def check_memory(meminfo_text=None) -> CheckResult:
    text = _read("/proc/meminfo") if meminfo_text is None else meminfo_text
    total_kb = 0
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            try:
                total_kb = int(line.split()[1])
            except (IndexError, ValueError):
                pass
            break
    if not total_kb:
        return CheckResult("Memória RAM", WARN, "Não foi possível ler a RAM total.")
    gb = total_kb / 1024 / 1024
    if gb < MIN_RAM_GB:
        return CheckResult("Memória RAM", WARN, f"{gb:.1f} GB de RAM.",
                           f"Recomendado pelo menos {MIN_RAM_GB:.0f} GB para jogos.")
    return CheckResult("Memória RAM", OK, f"{gb:.1f} GB de RAM.")


def check_cpu(count=None) -> CheckResult:
    count = os.cpu_count() if count is None else count
    if not count:
        return CheckResult("Processador", WARN, "Não foi possível contar os núcleos.")
    if count < MIN_CPUS:
        return CheckResult("Processador", WARN, f"{count} núcleo(s) lógico(s).",
                           f"Recomendado pelo menos {MIN_CPUS} núcleos.")
    return CheckResult("Processador", OK, f"{count} núcleos lógicos.")


def check_input_access(event_paths=None, group_names=None) -> CheckResult:
    """O Phantom (mapeamento teclado/mouse) precisa ler /dev/input/event*."""
    if event_paths is None:
        event_paths = glob.glob("/dev/input/event*")
    if not event_paths:
        return CheckResult("Acesso a dispositivos de entrada", WARN, "Nenhum /dev/input/event* encontrado.",
                           "Só é necessário se for usar o mapeamento de controles (Phantom).")
    if any(os.access(p, os.R_OK) for p in event_paths):
        return CheckResult("Acesso a dispositivos de entrada", OK, "Leitura de /dev/input permitida.")
    if group_names is None:
        try:
            group_names = [grp.getgrgid(g).gr_name for g in os.getgroups()]
        except KeyError:
            group_names = []
    if "input" in group_names:
        return CheckResult("Acesso a dispositivos de entrada", WARN,
                           "Você está no grupo 'input', mas a leitura foi negada.",
                           "Saia e entre na sessão de novo, ou siga o procedimento do Phantom.")
    return CheckResult(
        "Acesso a dispositivos de entrada", WARN, "Sem permissão para ler /dev/input.",
        "Para o Phantom, adicione seu usuário ao grupo input (sudo usermod -aG input $USER) "
        "e reinicie a sessão. Não é necessário para só rodar jogos.")


def run_all_checks() -> list:
    """Roda todas as checagens na ordem em que aparecem na tela."""
    return [
        check_session(),
        check_waydroid_installed(),
        check_binder(),
        check_gpu(),
        check_memory(),
        check_cpu(),
        check_input_access(),
    ]


def summarize(results) -> str:
    """Resumo de uma linha: 'ok', 'warn' ou 'fail' (o pior status encontrado)."""
    statuses = {r.status for r in results}
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return OK
