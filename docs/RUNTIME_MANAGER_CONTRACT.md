# Contrato do Runtime Manager — LinuxDroid Gaming

**Versão:** 1.3
**Data:** 19/11/2026
**Base Git:** `a4c06ac` (mudanças locais preservadas)
**Estado:** núcleo implementado e testado; integração das operações auxiliares principal concluída

---

## 1. Camadas

```
LinuxDroid UI
      │  (eventos + OperationResult + RuntimeSnapshot)
      ▼
RuntimeManager
      │  (OperationContext: timeout, cancelamento cooperativo)
      ▼
RuntimeBackend  ──► FakeRuntimeBackend   (testes, sem E/S)
      │             WaydroidRuntimeBackend (CLI + D-Bus injetados)
      │             [futuros adaptadores]
      ▼
Android Runtime (Waydroid hoje)
```

| Camada | Responsabilidade | **Não** faz |
|---|---|---|
| **UI** | Exibir `RuntimeSnapshot`, enviar intenções ao manager, reagir a eventos | Executar `waydroid`, `adb`, `busctl` ou qualquer subprocesso |
| **RuntimeManager** | Orquestrar, validar transições e argumentos, serializar operações mutantes e auxiliares, aplicar timeout/cancelamento, gerar eventos, histórico e erros estruturados, recuperar de falha | Conhecer flags do Waydroid, abrir subprocesso, tocar em D-Bus, importar Qt |
| **RuntimeBackend** | Traduzir a intenção em comandos do runtime; consultar sessão e container **separadamente**; declarar capacidades reais | Tomar decisão de negócio, esconder erro, fingir operação não implementada |
| **Android Runtime** | Executar sessão/container e apps | — |

**Regra de ouro:** nenhuma chamada de shell é espalhada pela aplicação. O único lugar que conhece `waydroid status`, `session start/stop` e o barramento D-Bus é `linuxdroid/runtime/waydroid_backend.py`.

---

## 2. Modelos públicos

Todos em `linuxdroid/runtime/models.py`, sem Qt e sem efeito colateral.

### 2.1 `RuntimeSnapshot` — sessão e container separados

```python
@dataclass(frozen=True)
class RuntimeSnapshot:
    session_state: RuntimeState
    container_state: RuntimeState
    runtime_availability: RuntimeAvailability
    active_operation: RuntimeOperation | None
    last_error: RuntimeFailure | None
    capabilities: RuntimeCapabilities
    taken_at: float
    details: dict
```

**Estado válido e real deste host:** `session_state=RUNNING`, `container_state=FROZEN`.
O campo `effective_state` existe **somente para exibição**; decisões de transição usam os dois campos brutos.

| `RuntimeState` | Uso |
|---|---|
| `NOT_INSTALLED`, `NOT_INITIALIZED`, `STOPPED`, `STARTING`, `RUNNING`, `FREEZING`, `FROZEN`, `STOPPING`, `ERROR`, `UNKNOWN` | Valores normalizados das saídas do runtime |

`RuntimeAvailability` é independente: `AVAILABLE`, `NOT_FOUND`, `PERMISSION_DENIED`, `SERVICE_UNAVAILABLE`, `NOT_INITIALIZED`, `UNKNOWN`.

### 2.2 `RuntimeCapabilities`

```python
RuntimeCapabilities(
    backend="waydroid",
    supported=frozenset({...}),   # somente operações existentes de fato
    experimental=frozenset(),
    notes="..."
)
```

O adaptador Waydroid **não anuncia** `FREEZE`/`UNFREEZE` quando nenhum cliente D-Bus foi injetado. Isso transforma uma falha obscura em `UNSUPPORTED_OPERATION`, sem comando executado.

### 2.3 `OperationResult`, `RuntimeFailure`, `RuntimeEvent`, `OperationRecord`

- `OperationResult`: `operation`, `ok`, `message`, `failure`, `snapshot`, `data`, `started_at`, `duration_ms`, `skipped`.
- `RuntimeFailure`: `code`, `message`, `operation`, `detail`, `retryable` — a UI traduz o código; nunca recebe exceção crua.
- `RuntimeEvent`: `kind`, `timestamp`, `operation`, `message`, `failure`, `snapshot`.
- `OperationRecord`: histórico com `OperationStatus` (`SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELED`, `SKIPPED`).

Códigos de erro: `NOT_FOUND`, `PERMISSION_DENIED`, `SERVICE_UNAVAILABLE`, `NOT_INITIALIZED`, `TIMEOUT`, `INVALID_RESPONSE`, `UNSUPPORTED_OPERATION`, `INVALID_TRANSITION`, `DUPLICATE_OPERATION`, `INVALID_ARGUMENT`, `CANCELED`, `NOT_IMPLEMENTED`, `BACKEND_ERROR`, `UNKNOWN`.

---

## 3. Contrato do `RuntimeBackend`

```python
class RuntimeBackend(FutureRuntimeOperations, ABC):
    name: str
    def status(self, *, context: OperationContext | None = None) -> RuntimeSnapshot: ...
    def start(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def stop(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def restart(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def freeze(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def unfreeze(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def list_apps(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def launch_app(self, package_id: str, *, context: OperationContext | None = None) -> OperationResult: ...
    def install_app(self, package_path: str, *, context: OperationContext | None = None) -> OperationResult: ...
    def remove_app(self, package_id: str, *, context: OperationContext | None = None) -> OperationResult: ...
    def get_property(self, key: str, *, context: OperationContext | None = None) -> OperationResult: ...
    def set_property(self, key: str, value: str, *, context: OperationContext | None = None) -> OperationResult: ...
    def adb_connect(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def show_full_ui(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def diagnostics(self, *, context: OperationContext | None = None) -> OperationResult: ...
    def capabilities(self) -> RuntimeCapabilities: ...
```

`OperationContext` carrega `operation`, `timeout`, `cancel_event`, `remaining()` e `raise_if_cancelled()`. É cooperativo: nenhum processo é morto pelo manager.

### Extensões previstas (`FutureRuntimeOperations`)

`create_instance()`, `clone_instance()`, `backup()`, `restore()`.

A implementação padrão levanta `RuntimeFailureError(NOT_IMPLEMENTED)`. Isso é uma extensão explícita, não uma funcionalidade falsa: nenhum adaptador anuncia essas capacidades. `install_app()`, `launch_app()`, `list_apps()`, `remove_app()`, `get_property()`, `set_property()`, `adb_connect()`, `show_full_ui()` e `diagnostics()` foram promovidas a operações reais (vide §4.3) e são anunciadas por `AUXILIARY_FEATURES` apenas quando implementadas no adaptador.

---

## 4. Contrato do `RuntimeManager`

```python
manager = RuntimeManager(backend, default_timeout=30.0)

manager.status()        # OperationResult; atualiza manager.snapshot
manager.start()         # OperationResult
manager.stop()
manager.restart()
manager.freeze()
manager.unfreeze()
manager.list_apps()     # OperationResult com data={"apps": [...]}
manager.launch_app("com.dts.freefireth")
manager.install_app("/caminho/jogo.apk")  # APK único; XAPK usa services/installer.py
manager.remove_app("com.dts.freefireth")
manager.get_property("persist.waydroid.multi_windows")
manager.set_property("persist.waydroid.multi_windows", "false")
manager.adb_connect()   # solicita conexão; autorização no Android ainda é necessária
manager.show_full_ui()  # traz a superfície à frente; não altera resolução
manager.diagnostics()   # OperationResult com data somente leitura
manager.capabilities()  # RuntimeCapabilities
manager.snapshot        # RuntimeSnapshot (sem E/S)
manager.last_error      # RuntimeFailure | None
manager.is_busy         # bool
manager.cancel(operation=None) -> bool
manager.clear_error() -> None
manager.recover()       # OperationResult (limpa erro e reconulta)
manager.subscribe(listener) -> callable   # unsubscribe
manager.events(since=0.0) -> tuple[RuntimeEvent, ...]
manager.history(limit=None) -> tuple[OperationRecord, ...]
manager.shutdown(wait=False)
```

### 4.1 Máquina de estados (validação antes de executar)

| Operação | Pré-condição | Comportamento especial |
|---|---|---|
| `status` | sempre permitida | consulta sessão e container em campos distintos |
| `start` | sessão `STOPPED`/`UNKNOWN` | `FROZEN` → `INVALID_TRANSITION` com dica de **reativar**; `STARTING`/`STOPPING` recusado |
| `stop` | sessão ativa | `STOPPED`/`STOPPING` → `INVALID_TRANSITION` |
| `restart` | sessão ativa ou parada | `STARTING`/`STOPPING` recusado |
| `freeze` | container `RUNNING`/`UNKNOWN` | já `FROZEN` → `OK` com `skipped=True` (idempotente) |
| `unfreeze` | container `FROZEN` | já `RUNNING`/`STARTING` → `OK` com `skipped=True` (idempotente) |

Toda operação mutante, `launch_app` e `install_app` fazem uma **consulta prévia de estado** antes de validar, para não agir sobre uma foto antiga. Operação mutante ou auxiliar duplicada (outra em andamento) → `DUPLICATE_OPERATION` sem tocar no backend.

### 4.3 Operações auxiliares reais

| Operação | Validação | Efeito | Capacidade |
|---|---|---|---|
| `list_apps` | disponibilidade do runtime | `waydroid app list`, parser puro; não altera sessão/container | `LIST_APPS` |
| `launch_app` | package ID válido + sessão **e** container `RUNNING` | `waydroid app launch`; **não** afirma que o jogo abriu ou chegou ao lobby | `LAUNCH_APP` |
| `install_app` | arquivo `.apk` existente + sessão **e** container `RUNNING` | `waydroid app install`; aceito pelo comando ≠ instalado pelo Android | `INSTALL_APP` |
| `remove_app` | package ID válido + sessão **e** container `RUNNING` | `waydroid app remove`; operação destrutiva, exige confirmação explícita na UI | `REMOVE_APP` |
| `get_property` | chave válida + sessão `RUNNING` + container **não** `FROZEN`/`FREEZING` | `waydroid prop get`; valor devolvido em `data["value"]` e em `stdout` do adaptador antigo | `GET_PROPERTY` |
| `set_property` | chave/valor válidos + sessão `RUNNING` + container **não** `FROZEN` | `waydroid prop set`; nunca edita arquivos do Android diretamente | `SET_PROPERTY` |
| `adb_connect` | sessão **e** container `RUNNING` | `waydroid adb connect`; não depende de IP manual; autorização no Android ainda é necessária | `ADB_CONNECT` |
| `show_full_ui` | sessão **e** container `RUNNING` | `waydroid show-full-ui`; traz a superfície à frente, não altera resolução | `SHOW_FULL_UI` |
| `diagnostics` | disponibilidade do runtime | `waydroid status` somente leitura; nunca altera props | `DIAGNOSTICS` |

Todas usam `AUXILIARY_OPERATIONS` (serialização), eventos, histórico, timeout e cancelamento. O manager recusa com `INVALID_ARGUMENT`/`INVALID_TRANSITION` antes de qualquer subprocesso e com `UNSUPPORTED_OPERATION` se o adaptador não anunciar a capacidade. **Regra preservada:** `prop get/set` não é executado com container congelado; a consulta prévia de estado usa `status()` e gera `INVALID_TRANSITION` retryable. A ponte Qt aceita argumentos nomeados (`package_id`, `package_path`, `key`, `value`) sem quebrar chamadas antigas.

### 4.2 Concorrência, timeout, cancelamento, recuperação

- No máximo **uma** operação mutante ou auxiliar por vez; `status` pode rodar em paralelo.
- Execução em `ThreadPoolExecutor` injetável; `future.result(timeout)` produz `TIMEOUT` estruturado.
- Timeout sinaliza também o `cancel_event`, para que o adaptador interrompa uma espera.
- `cancel()` é cooperativo e por operação; resultado `CANCELED`, evento `OPERATION_CANCELED`, histórico `CANCELED`.
- `recover()` limpa `last_error`, reconcilia o estado e só reporta sucesso se o runtime responder; falha persistente continua falha.
- Falha de observadores de evento nunca derruba o manager.

---

## 5. Adaptadores

### 5.1 `FakeRuntimeBackend`

Sem subprocess, sem D-Bus. Permite `set_states()`, `queue_effect()`, `queue_failure()`, `queue_response()`, `set_delay()` e registra `calls`. É a base de todos os testes de manager.

### 5.2 `WaydroidRuntimeBackend`

Dependências injetadas:

```python
WaydroidRuntimeBackend(
    command_runner=...,   # .run(program, args, timeout=) -> CommandResult
    dbus=...,             # .call(bus, service, path, interface, method, args, timeout)
)
```

- CLI: `waydroid status`, `waydroid session start|stop`, `waydroid app list|launch|install|remove`, `waydroid prop get|set`, `waydroid adb connect`, `waydroid show-full-ui`.
- D-Bus oficial: serviço `id.waydro.Container`, objeto `/ContainerManager`, interface `id.waydro.ContainerManager`, métodos `Freeze`/`Unfreeze`.
- `SubprocessCommandRunner` usa `subprocess.run(..., shell=False)` e a resolução portátil de `command_paths.py`; bloqueia `sudo`/`su`/`pkexec` etc.
- `SystemBusDBusClient` recebe o barramento por injeção (por exemplo, `pydbus.SystemBus()`); nenhuma elevação de privilégio é tentada.

> **Nesta etapa nenhum `freeze`/`unfreeze` real foi executado.** Os testes usam `FakeDBus` e `FakeRunner`. O container real permanece `FROZEN` e a sessão `RUNNING`.

---

## 6. Cobertura de testes

`tests/test_runtime_manager.py`, `tests/test_waydroid_runtime_backend.py`, `tests/test_runtime_presentation.py`, `tests/test_runtime_qt_bridge.py`, `tests/test_runtime_auxiliary.py` (11 testes), `tests/test_runtime_properties.py` (9 testes) e `tests/test_auxiliary_qt_integration.py` (7 testes).

| Requisito | Teste |
|---|---|
| `RUNNING` + `RUNNING` | `test_running_and_running` |
| `RUNNING` + `FROZEN` | `test_running_and_frozen_are_independent` |
| `STOPPED` | `test_stopped` |
| `STARTING` | `test_starting` |
| `STOPPING` | `test_stopping` |
| `UNKNOWN` | `test_unknown` |
| Permissão negada | `test_permission_denied_on_start`, `test_dbus_permission_denied_is_structured` |
| Timeout | `test_timeout_is_structured_and_cancels_cooperatively` |
| Serviço inexistente | `test_service_not_found` |
| Resposta inválida | `test_invalid_response`, `test_invalid_mutation_response` |
| Operação duplicada | `test_duplicate_operation_is_rejected` |
| Freeze repetido | `test_repeated_freeze_is_skipped` |
| Unfreeze repetido | `test_repeated_unfreeze_is_skipped` |
| Recuperação após erro | `test_recovery_after_error` |
| Cancelamento | `test_explicit_cancel` |
| Contrato D-Bus oficial | `test_freeze_and_unfreeze_use_official_dbus_contract` |
| Sem capacidade falsa | `test_capabilities_without_dbus_do_not_advertise_freeze`, `test_unimplemented_extensions_fail_closed`, `test_auxiliary_operation_requires_advertised_capability` |
| Auxiliares: sucesso, validação, serialização, timeout | `test_list_apps_is_read_only_and_does_not_refresh_state`, `test_launch_app_registers_command_and_invalid_package_is_refused`, `test_install_requires_active_android_and_apk_suffix`, `test_diagnostics_is_read_only`, `test_auxiliary_operations_are_serialized`, `test_auxiliary_timeout_signals_cancellation` |
| Auxiliares no adaptador e na ponte Qt | `test_list_apps_uses_injected_cli_and_parses_output`, `test_install_rejects_non_apk_and_uses_same_cli_as_service`, `test_bridge_forwards_named_arguments_to_manager`, `test_service_install_uses_manager_with_named_path` |
| Remoção e propriedades | `test_remove_app_requires_valid_package_and_active_android`, `test_prop_get_is_refused_with_frozen_container`, `test_prop_set_is_refused_with_frozen_container`, `test_property_arguments_are_validated_before_execution`, `test_property_round_trip_records_history`, `test_cli_contract_for_remove_and_properties`, `test_service_get_multi_windows_keeps_value_in_stdout` |
| ADB e superfície | `test_adb_and_surface_require_active_android`, `test_injected_cli_contract` (em `test_runtime_properties.py`), `test_service_adb_and_surface_use_manager` |
| Remoção na interface | `test_remove_button_only_for_confirmed_installed_package`, `test_library_forwards_remove_request`, `test_decline_does_not_call_service`, `test_confirmed_removal_updates_local_record`, `test_frozen_container_refuses_removal` |
| Tradução para a UI sem perder `FROZEN` | `test_running_frozen_snapshot_becomes_frozen_status` |
| Contrato antigo de callbacks preservado | `test_operation_result_keeps_old_callback_contract`, `test_success_result` |
| UI → manager sem comando direto | `test_status_goes_through_manager_and_emits_snapshot`, `test_unfreeze_request_updates_snapshot_without_direct_command` |

Suíte completa: **333 testes OK** no `.venv` com PySide6; 333 testes no Python do sistema com 39 skips.

---

## 7. Estado da integração com a interface

**Implementado:**
- `linuxdroid/runtime/qt_bridge.py` — `RuntimeManagerBridge` com `QThread`, sinais `operation_done`, `snapshot_changed`, `event_occurred`, `log_line`, e callbacks executados na thread da interface.
- `linuxdroid/runtime/presentation.py` — converte `RuntimeSnapshot` → `WaydroidStatus` e `OperationResult` → `CommandResult`, preservando o contrato antigo de `status_changed` (`state/session/container/ip/message`) e dos callbacks (`.ok`, `.text`, `.error`).
- `services/waydroid_service.py` — `refresh/start/stop/restart/freeze/unfreeze`, `list_apps`, `launch_app`, `install_app`, `remove_app`, `get_property`, `set_property`, `adb_connect` e `show_full_ui` passam a ser intenções enviadas ao manager. O serviço não tem mais `ProcessRunner`: todo comando `waydroid` da interface passa pela ponte Qt. A tela continua com a mesma API pública; `MainWindow.play()` e `WaydroidScreen` não foram alterados. `operation_to_command_result` preserva o valor de `prop get` em `stdout`.
- Smoke test com `QApplication`: bridge criado, backend `waydroid`, `MainWindow` aberta e fechada sem erro, shutdown limpo.

**Pendente (próximo bloco):**
- Keycodes continuam no cliente ADB separado (`services/adb_service.py`), fora do RuntimeManager. Nenhuma funcionalidade falsa foi criada. A instalação passa por um planejador puro (`services/installer.py`) que verifica a identidade do assinante antes da execução; a execução real continua sendo uma ação explícita.
- Avaliar extração de ícone sem copiar recursos protegidos (sem AAPT no host; decisão atual: manter escolha explícita do usuário).
- Inspecionar as 128 imagens na etapa final, por decisão do usuário.

**Suíte:** `.venv` (PySide6 6.12.0): **333 testes OK, 0 skips**. Python do sistema (sem PySide6): 333 testes, **39 skips** (2 GUI pré-existentes, 3 do bridge, 3 do serviço de tela, 4 da integração do editor, 9 da integração da biblioteca, 7 dos auxiliares Qt, 5 da remoção na biblioteca e 6 da barra lateral).
