# LinuxDroid Gaming — Matriz de Paridade com BlueStacks 5

**Versão do documento:** 1.1 — refinada com inventário de arquitetura (19/11/2026)
**Data:** 19/11/2026
**Base Git:** `a4c06ac`
**Evidência:** `git status`, leitura de código e suíte de 289 testes (289 OK no `.venv` com PySide6; 18 skips no Python do sistema)

> **Aviso de honestidade:** `IMPLEMENTADO E VALIDADO` significa que existe código coberto por testes nesta árvore. Código untracked com testes passando é reportado como tal, com a ressalva. Backend simulado, janela aberta, perfil salvo ou propriedade configurada **não** provam injeção/captura real. A verificação gráfica da GUI não pôde ser feita neste interpretador (PySide6 ausente).

## Legenda de status

| Rótulo | Significado |
|---|---|
| `IMPLEMENTADO E VALIDADO` | Existe e possui evidência/teste nesta árvore |
| `IMPLEMENTADO PARCIALMENTE` | Parte do recurso existe, com lacunas conhecidas |
| `SIMULADO` | Existe apenas em modo de teste/simulação — **não** é injeção/captura real |
| `EM DESENVOLVIMENTO` | Código em construção, untracked ou incompleto |
| `NÃO IMPLEMENTADO` | Não existe no repositório |
| `LIMITADO PELO WAYDROID` | O runtime atual impõe limitação estrutural |
| `NECESSITA OUTRO RUNTIME` | Depende de arquitetura além do Waydroid |
| `NÃO COMPATÍVEL` | Não deve ser implementado (segurança, termos ou arquitetura) |

---

## 1. Home, navegação e identidade visual

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Módulo / evidência | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|---|
| Home, navegação, janela | Home | **IMPLEMENTADO E VALIDADO** | `main_window.py::MainWindow`, `theme.py` | Alta | Baixo | Suíte (196) | Alta | P1 |
| Tema/paleta própria | Identidade BS | **IMPLEMENTADO E VALIDADO** | `theme.py` | Alta | Baixo | Suíte | Média | P7 |
| Tela "Sobre" | About | **IMPLEMENTADO E VALIDADO** | `screens/about.py` | Alta | Baixo | Suíte | Baixa | P7 |
| Barra lateral de ferramentas | Side toolbar | **IMPLEMENTADO PARCIALMENTE** | `widgets/tool_rail.py` com 19 ferramentas; apenas Navegação (Controles/ADB/Config/Instalar), Tela cheia e Reabrir têm ação real; as demais aparecem desabilitadas com motivo | Alta | Baixo | 6 testes GUI | Alta | P4 |
| Navegação entre páginas consistente | Home/Config | **IMPLEMENTADO E VALIDADO** | `MainWindow` | Alta | Baixo | Suíte | Alta | P1 |

## 2. Biblioteca de jogos

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Módulo / evidência | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|---|
| Detecção de pacotes instalados | App center | **IMPLEMENTADO E VALIDADO** | `RuntimeManager.list_apps()` → `RuntimeOperation.LIST_APPS` → `waydroid app list` injetado; `WaydroidService` emite pares parseados | Alta | Baixo (parser) | 3 testes + integração Qt | Alta | P1 |
| Grade responsiva (2/3/4 colunas) e lista local | App center | **IMPLEMENTADO E VALIDADO** | `screens/library.py` calcula colunas pela largura e atualiza no resize; `screens/home.py` via `services/library_metadata.py::recent_games()` | Alta | Baixo | 16 testes (9 puros + 7 GUI) | Alta | P1 |
| Pesquisa por nome | App center | **IMPLEMENTADO E VALIDADO** | `LibraryScreen` + `filtered_games()` — nome **e** package ID, sem diferenciar maiúsculas | Alta | Baixo | 2 testes GUI + puros | Média | P1 |
| Favoritos e categorias | App center | **IMPLEMENTADO E VALIDADO** | `GameEntry.favorite/category`, `GameCard` com estrela, filtros e ordenação em `LibraryScreen` | Alta | Baixo | testes puros + GUI | Média | P1 |
| Ícones e capas reais | App center | **NÃO IMPLEMENTADO** | sem extração de ícone | Média | Médio (memória) | — | Média | P1 |
| Última execução | App center | **IMPLEMENTADO E VALIDADO** | `GameEntry.last_launched_at/launch_count` gravados por `record_launch()` quando o comando é aceito; **não prova lobby** | Alta | Baixo | testes puros | Média | P1 |
| Estado instalado / instalação não confirmada / comando aceito | App center | **IMPLEMENTADO E VALIDADO** | `library_metadata.STATES` + `GameEntry.installed_status` / `last_launched_at`; sem campo `running` inventado | Alta | Baixo | 4 testes puros + 2 GUI | Alta | P1 |
| Abrir jogo com um clique | App launch | **IMPLEMENTADO E VALIDADO** | `RuntimeManager.launch_app()` valida package ID e estado ativo; `waydroid app launch` via backend injetado | Alta | Baixo | 3 testes + integração Qt | Alta | P1 |
| Desinstalar app com confirmação | App center | **IMPLEMENTADO E VALIDADO** | `GameCard.remove_btn` só aparece habilitado para app confirmado com package ID válido; `MainWindow.remove_game()` exige confirmação, Android ativo e usa `RuntimeManager.remove_app()`; registros locais passam a `missing` | Média | Médio (dados do jogo) | 5 testes GUI | Média | P1 |
| Fechar / atualizar app | App center | **NÃO IMPLEMENTADO** | — | Média | Médio | — | Média | P1 |
| Importar/exportar perfil de controle | Profiles | **IMPLEMENTADO E VALIDADO** | `input/profile_bridge.py`, `controls/phantom.py` | Alta | Baixo | `test_editor_model_storage.py` | Média | P3 |

## 3. Instalação de aplicativos

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Módulo / evidência | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|---|
| Instalação APK | Install APK | **IMPLEMENTADO E VALIDADO** | `services/installer.py::plan_apk_installation()` + `RuntimeManager.install_app()` → `waydroid app install`, com validação e histórico | Alta | Médio | 4 + 3 testes | Alta | P1 |
| Extração XAPK com streaming e cotas | Install XAPK | **IMPLEMENTADO E VALIDADO** (código untracked, 5 testes) | `services/xapk.py` — cotas 2 GiB/6 GiB, razão 500:1; `tests/test_xapk.py` | Alta | Médio (ZIP malformado) | 5 testes OK | Alta | P1 |
| APKS / splits / múltiplas ABIs | Install APKS | **IMPLEMENTADO PARCIALMENTE** | `extract_apk_members()` cobre membros APK | Média | Médio | `test_xapk.py` | Média | P1 |
| Verificação de assinatura/checksum dos splits | — | **IMPLEMENTADO E VALIDADO** | `services/apk_signature.py` + `services/installer.py` — compara identidade da chave v2/v3; falha fechada; **não** é validação criptográfica do arquivo | Média | Médio | 11 testes | Alta | P1 |
| Progresso e resultado | Install UI | **NÃO IMPLEMENTADO** | — | Alta | Baixo | — | Média | P1 |
| Fontes verificadas (Play/F-Droid/usuário) | Store | **LIMITADO PELO WAYDROID** | sem Play Store integrada | Baixa | Alto (procedência) | Documental | Baixa | P6 |

## 4. Runtime Manager / ciclo de vida

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Módulo / evidência | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|---|
| Start / stop / restart / unfreeze | Start/Stop | **IMPLEMENTADO E VALIDADO** (núcleo) | `runtime/manager.py` + `runtime/waydroid_backend.py` | Alta | Médio | 36 testes novos | Alta | P1 |
| Parser de estado `FROZEN` | — | **IMPLEMENTADO E VALIDADO** | `services/parsing.py::waydroid_status()`; `runtime/waydroid_backend.py::parse_status_output` | Alta | Baixo | `test_waydroid_state.py`, `test_waydroid_runtime_backend.py` | Alta | P1 |
| Comando `freeze` explícito | — | **IMPLEMENTADO COM MOCK** | D-Bus `id.waydro.Container` → `/ContainerManager`; **nunca executado no host** | Alta | Médio (permissão D-Bus) | `test_waydroid_runtime_backend.py` | Alta | P1 |
| Sessão `RUNNING` + container `FROZEN` separados | — | **IMPLEMENTADO E VALIDADO** | `RuntimeSnapshot.session_state` / `.container_state` | Alta | Baixo | `test_runtime_manager.py` | Alta | P1 |
| Reativar container antes de `play()` | — | **IMPLEMENTADO E VALIDADO** | `MainWindow.play()` (ainda via serviço antigo) | Alta | Médio | Suíte | Alta | P1 |
| Modo janela única/separadas (prop explícita) | Display mode | **IMPLEMENTADO E VALIDADO** | `screens/waydroid.py` — não consulta `prop get` automaticamente; leitura explícita via `RuntimeManager.get_property()` com bloqueio se container `FROZEN` | Alta | Baixo | 5 testes + 2 Qt | Alta | P1 |
| Abstração de runtime (backend trocável) | — | **IMPLEMENTADO E VALIDADO** (núcleo) | `runtime/backend.py`, `fake_backend.py`, `waydroid_backend.py` | Alta | Médio | 36 testes novos | Alta | P1 |
| GUI usando o manager no ciclo de vida | — | **IMPLEMENTADO E VALIDADO** | `runtime/qt_bridge.py` + delegação em `WaydroidService` | Alta | Médio | 9 testes novos | Alta | P1 |
| Operações auxiliares no manager | — | **IMPLEMENTADO E VALIDADO** | `list_apps`, `launch_app`, `install_app`, `remove_app`, `get_property`, `set_property`, `adb_connect`, `show_full_ui`, `diagnostics` no manager; `WaydroidService` sem `ProcessRunner`; keycodes seguem no cliente ADB separado | Alta | Médio | 27 testes | Média | P1 |
| ADB | ADB Debug | **IMPLEMENTADO PARCIALMENTE** | `RuntimeManager.adb_connect()` (`waydroid adb connect`, sem IP manual) + `services/adb_service.py` para devices/install/keycodes | Média | Médio (autorização no Android) | Suíte | Média | P4 |
| Atalhos Android (keycodes 4/3/187/25/24) | Navigation keys | **LIMITADO PELO WAYDROID** | hardcodes no serviço | Média | Baixo | — | Média | P4 |
| Timeout / cancelamento / duplicate / idempotência | — | **IMPLEMENTADO E VALIDADO** | `RuntimeManager` com `OperationContext` | Alta | Baixo | `test_runtime_manager.py` | Alta | P1 |
| Recuperação de falhas | — | **IMPLEMENTADO E VALIDADO** | `RuntimeManager.recover()` | Média | Médio | `test_recovery_after_error` | Alta | P1 |

## 5. Instance Manager

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|
| IDs/estados de instância | Multi-Instance Manager | **NÃO IMPLEMENTADO** | A AVALIAR | Alto (isolamento) | — | Alta | P5 |
| Criar/renomear/excluir | Multi-Instance Manager | **NÃO IMPLEMENTADO** | A AVALIAR | Alto | — | Alta | P5 |
| Clonar | Multi-Instance Clone | **NÃO IMPLEMENTADO** | A AVALIAR | Alto | — | Média | P5 |
| Snapshot / backup / restore | — | **NÃO IMPLEMENTADO** | A AVALIAR | Alto | — | Alta | P5 |
| Validação de integridade | — | **NÃO IMPLEMENTADO** | A AVALIAR | Médio | — | Alta | P5 |
| **Execução simultânea isolada** | Multi-Instance Sync | **NÃO IMPLEMENTADO** | **NECESSITA PROVA DE ISOLAMENTO** | **Muito alto** | Integração real | Alta | P5 |
| Multi-Instance Sync | Sync | **NÃO COMPATÍVEL** (uso indevido em jogos) | — | ToS | — | Baixa | — |

> Waydroid usa sessão/container por host com Binder e rede compartilhados. Duas instâncias sobre a mesma imagem de dados **não** são multi-instância real. Provar isolamento de rede, processos, armazenamento, Binder e GPU antes de implementar.

## 6. Editor de controles e Input Engine

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Módulo / evidência | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|---|
| Editor visual V2 (criar/capturar/duplicar/undo/redo/salvar) | Game Controls Editor | **IMPLEMENTADO PARCIALMENTE** | `screens/controls.py` (1.490 linhas), `input/editor_model.py::BindingEditor` | Alta | Baixo | 2 testes GUI ignorados (PySide6) | Alta | P3 |
| Perfis V2/V1 + migração + validação | Profiles | **IMPLEMENTADO E VALIDADO** | `controls/model.py::validate_profile()`, `input/profile_bridge.py`, `SCHEMA_VERSION=2` | Alta | Baixo | `test_controls_model.py` (34) | Alta | P3 |
| ScreenContract / coordenadas normalizadas | — | **IMPLEMENTADO E VALIDADO** | `controls/model.py::ScreenContract` | Alta | Baixo | Suíte | Alta | P3 |
| Captura de identidade de tecla (scan code + mods) | Game Controls | **IMPLEMENTADO E VALIDADO (lógica) / NÃO VALIDADO (GUI)** | `input/qt_bridge.py` | Alta | Baixo | teste GUI ignorado | Alta | P3 |
| Importar imagem de referência | Game Controls | **IMPLEMENTADO PARCIALMENTE** | `mapping_backgrounds`, import/export de imagem | Alta | Baixo | Suíte | Média | P3 |
| Captura automática da superfície Android | — | **NÃO IMPLEMENTADO** | — | Média (Wayland) | Médio | — | Alta | P2 |
| Engine: tap/hold/toggle/joystick/drag/aim/wheel/layer shift | Smart Controls | **IMPLEMENTADO E VALIDADO** | `input/engine.py::MappingEngine` | Alta | Médio | `test_engine.py` (13), `test_multitouch_safety.py` (14) | Alta | P2 |
| WASD + diagonais (bindings) | Smart Controls | **IMPLEMENTADO E VALIDADO** | `MappingEngine`, `input/normalizer.py` | Alta | Médio | Suíte | Alta | P2 |
| Multitoque seguro | — | **IMPLEMENTADO E VALIDADO** | `input/contacts.py` | Alta | Baixo | 14 testes | Alta | P2 |
| SAFE_RELEASE idempotente | — | **IMPLEMENTADO E VALIDADO** | Input Engine | Alta | Baixo | Suíte | Alta | P2 |
| Modo de tiro — ação de mira | Shooting Mode | **IMPLEMENTADO PARCIALMENTE** | ação `aim`/`mouse_camera` no engine | Alta | Médio | `test_engine.py` | Alta | P2 |
| Modo de tiro — captura real de ponteiro | Shooting Mode | **NÃO IMPLEMENTADO** | Wayland pointer constraints não implementados | **Média-Baixa** | **Alto** (não usar `grabMouse()`) | — | Alta | P2 |
| SimulatedInputProvider | — | **SIMULADO (intencional)** | `input/providers/simulated.py`, `runtime.mode="simulation"` | — | Nenhum | 18 testes | — | P2 |
| RecordingTouchBackend | — | **SIMULADO** | `input/backends/recording.py`, `mode="recording_only_no_injection"` | — | Nenhum | Suíte | — | P2 |
| PhantomAdapter | — | **SIMULADO** | `input/backends/phantom_adapter.py`, `functional/tested/operational=False` | — | Nenhum | `test_phantom_capabilities_diag.py` | — | P2 |
| Backend real de injeção | — | **NÃO IMPLEMENTADO** | `Diagnostics.snapshot()["injection_claimed"]=False` | A AVALIAR | **Alto** (permissão) | Integração real | Alta | P2 |
| Cursor virtual | — | **IMPLEMENTADO E VALIDADO** | `controls/cursor.py`, `test_cursor_state.py` (11) | Alta | Baixo | Suíte | Média | P2 |

## 7. Gamepad

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|
| Repasse USB → toques | Gamepad | **LIMITADO PELO WAYDROID** | `WaydroidService` gamepad passthrough (CHANGELOG: não traduz todo gamepad) | Média | Baixo | — | Média | P2 |
| Detecção evdev/capacidades reais | Gamepad | **NÃO IMPLEMENTADO** | Alta | **Alto** (não dar acesso irrestrito a `/dev/input`) | — | Média | P2 |
| Perfil por jogo / calibração / dead zone | Gamepad | **NÃO IMPLEMENTADO** | Alta | Médio | — | Média | P2 |
| Vibração | Gamepad | **NÃO IMPLEMENTADO** | A AVALIAR | Médio | — | Baixa | P6 |

## 8. Macros

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Evidência | Viabilidade | Riscos | Prior. | Etapa |
|---|---|---|---|---|---|---|---|
| Dados de macro no perfil | Macro Recorder | **IMPLEMENTADO PARCIALMENTE** | modelo aceita `macro`/`repeat_tap` | Alta | Baixo | Média | P4 |
| Runtime de macro | Macro Recorder | **NÃO IMPLEMENTADO / SIMULADO** | `_dispatch_action` emite `macro_runtime_disabled` | Alta | Médio (uso indevido) | Média | P4 |
| Guarda em jogos protegidos | — | **NÃO IMPLEMENTADO** (requisito de segurança) | — | Alta | Alto se ausente | Alta | P4 |
| Bots / auto-farm / mira automática | — | **NÃO COMPATÍVEL** | — | — | ToS/anticheat | — | — |

## 9. Desempenho e gráficos

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Evidência | Viabilidade | Riscos | Testes | Prior. | Etapa |
|---|---|---|---|---|---|---|---|
| Identificação GPU/Mesa/OpenGL/Vulkan | Graphics settings | **IMPLEMENTADO PARCIALMENTE** | `services/capabilities.py::collect()`, `assess_backend()`, `BackendStage` | Alta | Baixo | 22 testes | Alta | P1 |
| Checagem de requisitos do sistema | — | **IMPLEMENTADO E VALIDADO** | `services/system_check.py` (Wayland, Waydroid, binder, GPU, RAM, `/dev/input`) | Alta | Baixo | 17 testes | Alta | P1 |
| Perfis equilibrado/desempenho/econômico | Graphics settings | **NÃO IMPLEMENTADO** | — | Média | Médio | — | Média | P4 |
| Resolução/DPI/orientação | Display settings | **LIMITADO PELO WAYDROID** | somente leitura e prop de janela | Média | Médio | — | Alta | P4 |
| Parser de superfície real (`wm`/`dumpsys`) | — | **IMPLEMENTADO E VALIDADO** (15 testes) | `services/display_metrics.py` — `from_command_outputs()` | Alta | Baixo | `test_display_metrics.py` | Alta | P1 |
| Serviço de medição somente leitura | — | **IMPLEMENTADO E VALIDADO** (3 testes) | `services/display_metrics_service.py` — runner injetado, sem medição automática | Alta | Baixo | `test_display_metrics_service.py` | Alta | P1 |
| Uso da superfície real no editor | — | **IMPLEMENTADO E VALIDADO** (4 testes) | `ControlsScreen` usa referência `1920x1034@60`, dpi 180 marcada `REFERÊNCIA / MANUAL`; botão "Detectar resolução"; `NÃO MEDIDA` não apaga valor manual | Alta | Baixo | `test_controls_display_integration.py` | Alta | P1 |
| FPS médio/mínimo/frametime/picos | FPS display | **NÃO IMPLEMENTADO** | — | Média | Médio | — | Alta | P4 |
| CPU/RAM/temperatura/armazenamento | Performance monitor | **IMPLEMENTADO PARCIALMENTE** | `system_check.py` (somente checagem) | Média | Baixo | Suíte | Média | P4 |
| Eco Mode | Eco Mode | **NÃO IMPLEMENTADO** | — | Média | Médio (estabilidade) | — | Média | P4 |
| 120 FPS | High FPS | **NÃO COMPATÍVEL sem evidência** | — | Baixa | Falso suporte | — | Baixa | — |

## 10. Ferramentas e integração

| Recurso | Ref. BlueStacks | Estado no LinuxDroid | Evidência | Viabilidade | Prior. | Etapa |
|---|---|---|---|---|---|---|
| Screenshot da superfície Android | Screenshot | **NÃO IMPLEMENTADO** | sem captura automática | Alta | Alta | P4 |
| Gravação de vídeo | Screen recording | **NÃO IMPLEMENTADO** | — | Média (PipeWire/portal) | Média | P4 |
| Pasta de mídia | Media Manager | **NÃO IMPLEMENTADO** | — | Alta | Média | P4 |
| Clipboard Linux ↔ Android | — | **LIMITADO PELO WAYDROID** | serviço nativo do Waydroid, sem UI própria | Alta | Média | P4 |
| Compartilhamento de arquivos/imagens/downloads | — | **NÃO IMPLEMENTADO** | — | Média (permissões) | Média | P4 |
| Notificações/áudio/microfone | — | **LIMITADO PELO WAYDROID** | — | Média | Baixa | P6 |
| Atalhos globais e por jogo | Shortcuts | **NÃO IMPLEMENTADO** | — | Média (Wayland) | Média | P4 |
| ADB | ADB Debug | **IMPLEMENTADO PARCIALMENTE** | `services/adb_service.py` | Média (segurança) | Baixa | P4 |

## 11. Dados, recuperação e engenharia (BlueStacksRoot como referência conceitual)

| Recurso | Ref. conceitual | Estado no LinuxDroid | Evidência | Prior. | Etapa |
|---|---|---|---|---|---|
| JSON atômico, backup, `.corrupt` | BlueStacksRoot (conceito) | **IMPLEMENTADO E VALIDADO** | `storage.py` | Alta | P1 |
| Perfis versionados + migração V1 | BlueStacksRoot (conceito) | **IMPLEMENTADO E VALIDADO** | `controls/model.py`, `profile_bridge.py` | Alta | P1 |
| Checksums | BlueStacksRoot (conceito) | **IMPLEMENTADO PARCIALMENTE** | apenas nos backups do diagnóstico (fora do repo) | Alta | P5 |
| Backup/restore por instância | BlueStacksRoot (conceito) | **NÃO IMPLEMENTADO** | — | Alta | P5 |
| Rollback por instância | BlueStacksRoot (conceito) | **NÃO IMPLEMENTADO** | — | Alta | P5 |
| Detecção de operação interrompida | BlueStacksRoot (conceito) | **NÃO IMPLEMENTADO** | — | Alta | P5 |
| Relatórios sanitizados | BlueStacksRoot (conceito) | **NÃO IMPLEMENTADO** | — | Média | P7 |
| **Código do BlueStacksRoot** | CC BY-NC-ND 4.0 | **NÃO COMPATÍVEL — não copiar, adaptar ou incorporar** | — | — | — |

---

## Resumo quantitativo (inventário de 19/11/2026)

| Status | Contagem |
|---|---:|
| IMPLEMENTADO E VALIDADO | 38 |
| IMPLEMENTADO COM MOCK (nunca executado no host) | 1 |
| IMPLEMENTADO PARCIALMENTE | 11 |
| SIMULADO / intencional | 4 |
| NÃO IMPLEMENTADO | 29 |
| LIMITADO PELO WAYDROID / NECESSITA OUTRO RUNTIME / NÃO COMPATÍVEL | 10 |
| **Total linhas de recurso** | **93** |

**Testes:** 30 arquivos `test_*.py`, 333 funções, 333 OK no `.venv` (PySide6 6.12.0). No Python do sistema sem PySide6: 333 testes, **39 skips** por `@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 não está instalado neste interpretador")`: 2 em `tests/test_editor_gui.py::EditorGuiIntegrationTests`, 3 em `tests/test_runtime_qt_bridge.py`, 3 em `tests/test_display_metrics_service.py`, 4 em `tests/test_controls_display_integration.py`, 9 em `tests/test_library_gui.py`, 7 em `tests/test_auxiliary_qt_integration.py`, 5 em `tests/test_remove_app_gui.py` e 6 em `tests/test_tool_rail_gui.py`. Os testes de bridge/GUI/serviço de tela exigem o `.venv`.

## Dívidas mais urgentes (evidência no código)

1. ~~Hardcode `1280x720` no editor~~ — resolvido: `ControlsScreen` usa referência `1920x1034@60`, dpi 180 marcada `REFERÊNCIA / MANUAL` e medição explícita via botão "Detectar resolução" (somente leitura). `MainWindow.resize(1280,720)` é o tamanho da janela do launcher, não da superfície Android.
2. ~~UI acoplada a `WaydroidService`~~ — resolvido via `runtime/qt_bridge.py` para ciclo de vida, apps, propriedades, ADB e superfície; `WaydroidService` não tem mais `ProcessRunner`. Keycodes permanecem no cliente ADB separado, sem promoção falsa a operação do manager.
3. ~~Sem comando `freeze`~~ — resolvido no adaptador via D-Bus oficial; permanece pendente apenas a autorização para execução real no host.
4. **Backend real de injeção inexistente** — Phantom/Recording/Simulated são todos declarados não operacionais.
5. ~~XAPK sem verificação de assinatura~~ — resolvido com checagem de identidade v2/v3 e falha fechada. Permanece como limitação honesta: não é validação criptográfica completa e APKs v1-only são recusados.
6. **Ícones e capas reais ausentes** — o card mostra a inicial do nome. Não há extração de ícone do APK; qualquer capa precisaria vir de fonte explícita, nunca de recurso protegido do BlueStacks.
7. ~~Filtros de estado ausentes na UI~~ — resolvido: `LibraryScreen` filtra por instalados, instalação não confirmada e comando de lançamento aceito, com aviso explícito de que isso não prova jogo em execução. "Em execução" por jogo permanece sem fonte confiável e não é fingido.

## Próxima implementação concreta (proposta)

**Migração das operações auxiliares**, nesta ordem:

1. ~~Migrar `list_apps`, `install_app`, `launch_app`, `remove_app` e `prop get/set`~~ — entregue com validação de argumento, serialização, timeout, eventos, histórico e capacidade explícita; `prop get` é recusado com container congelado. ~~Migrar ADB e `show-full-ui`~~ — entregue; keycodes seguem fora do manager porque pertencem ao cliente ADB, não ao runtime.
2. ~~Expor filtros de estado na biblioteca~~ — entregue com dados já existentes; extração de ícone sem copiar recursos protegidos permanece em avaliação.
3. Inspeção visual das 128 imagens na etapa final, por decisão do usuário.

**Já entregue:** `services/display_metrics.py` (15 testes), `services/display_metrics_service.py` (3 testes), `ControlsScreen` integrado (4 testes), pacote `linuxdroid/runtime/` + bridge Qt e conversões para a UI (45 testes), `services/apk_signature.py` (7 testes) e `services/installer.py` (4 testes) com integração na tela Waydroid, `services/library_metadata.py` (9 testes) e `LibraryScreen`/`HomeScreen`/`GameCard` integrados (6 testes GUI), remoção de apps na biblioteca com confirmação (5 testes GUI), barra lateral direita com ferramentas reais e desabilitadas com motivo (6 testes GUI). Suíte: **333 testes** (333 OK no `.venv`, 39 skips no Python do sistema). Filtros de estado da biblioteca entregues com `STATE_INSTALLED/UNCONFIRMED/LAUNCHED` e aviso de que "comando aceito" não é "jogo em execução". Operações auxiliares migradas: `RuntimeOperation.LIST_APPS/LAUNCH_APP/INSTALL_APP/REMOVE_APP/GET_PROPERTY/SET_PROPERTY/ADB_CONNECT/SHOW_FULL_UI/DIAGNOSTICS`, `AUXILIARY_FEATURES`, capacidade recusada quando não anunciada, argumentos nomeados na ponte Qt, integração em `WaydroidService` (sem `ProcessRunner`) e bloqueio explícito de `prop get/set` com container `FROZEN`. Keycodes permanecem no cliente ADB separado, fora do runtime. Contrato completo em `docs/RUNTIME_MANAGER_CONTRACT.md`. Motivo da sequência: mudanças 100% no repositório, reversíveis via Git, sem tocar no container, no Native Bridge ou em dados do jogo.
