"""Resolução portátil de executáveis usados pelo launcher.

Este módulo não depende de PySide6 para poder ser testado isoladamente.
A política continua a mesma do ProcessRunner: sem shell e sem elevação
automática de privilégio.
"""
import os
import shutil
import sys


def _executable(path):
    return bool(path and os.path.isfile(path) and os.access(path, os.X_OK))


def _without_venv(path_value):
    """Remove entradas de virtualenv de um PATH, mantendo a ordem."""
    if not path_value:
        return path_value
    keep = []
    for entry in path_value.split(os.pathsep):
        normalized = entry.replace("\\", "/")
        if "/.venv/" in f"/{normalized}/" or "/venv/" in f"/{normalized}/":
            continue
        keep.append(entry)
    return os.pathsep.join(keep)


def _first_executable(candidates):
    for candidate in candidates:
        if _executable(candidate):
            return candidate
    return None


def system_python(path_env=None, environ=None, override=None):
    """Escolhe um interpretador do sistema, nunca um Python de .venv por padrão."""
    env = os.environ if environ is None else environ
    candidates = [
        override,
        env.get("LINUXDROID_SYSTEM_PYTHON"),
        "/usr/bin/python3",
        "/usr/bin/python",
    ]
    chosen = _first_executable(candidates)
    if chosen:
        return chosen
    return shutil.which("python3", path=_without_venv(path_env or env.get("PATH"))) or sys.executable


def resolve_command(program, args=(), *, path_env=None, environ=None, system_python_override=None):
    """Devolve ``(executable, args)``. ``executable`` é None quando não encontrado."""
    env = os.environ if environ is None else environ
    search_path = path_env if path_env is not None else env.get("PATH")
    program = str(program)
    arguments = [str(arg) for arg in args]

    if program.rsplit("/", 1)[-1] == "waydroid":
        if program == "waydroid":
            waydroid = shutil.which("waydroid", path=search_path)
        else:
            waydroid = program if _executable(program) else None
        if not waydroid:
            return None, [program, *arguments]
        python = system_python(
            path_env=search_path,
            environ=env,
            override=system_python_override,
        )
        return python, [waydroid, *arguments]

    if program.startswith("/") or os.altsep and program.startswith(os.altsep):
        executable = program if _executable(program) else None
    else:
        executable = shutil.which(program, path=search_path)
    return executable, arguments
