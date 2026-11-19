# LinuxDroid Gaming — Roadmap de Arquitetura

**Versão do documento:** 1.2 — operações auxiliares migradas para o manager (19/11/2026)
**Data:** 19/11/2026
**Base Git:** `a4c06ac`
**Evidência:** leitura de código, `git status`, 333 testes OK no `.venv` (39 skips no Python do sistema)

---

## 1. Estrutura real do repositório (inventariada)

```
linuxdroid/
├── __main__.py                    entrypoint
├── main_window.py                 MainWindow — navegação, play(), tratamento FROZEN
├── models.py                      GameEntry e modelos
├── theme.py                       tema/paleta
├── storage.py                     JSON atômico, .corrupt, migração V1
├── screens/
│   ├── home.py                    HomeScreen (games[:8])
│   ├── library.py                 LibraryScreen (grade cols=4, busca por nome)
│   ├── waydroid.py                WaydroidScreen (start/stop/restart/unfreeze)
│   ├── controls.py                ControlsScreen — editor V2 (1.490 linhas)
│   ├── settings.py                SettingsScreen (inclui checagem de desempenho)
│   └── about.py                   AboutScreen
├── controls/
│   ├── model.py                   ControlProfileV2, ScreenContract, validate_profile, SCHEMA_VERSION=2
│   ├── keys.py                    InputBinding, CODE_SPACES, normalize_phantom_name
│   ├── cursor.py                  VirtualCursor
│   └── phantom.py                 compatibilidade/exportação Phantom
├── input/
│   ├── events.py, normalizer.py, state.py, contacts.py
│   ├── engine.py                  MappingEngine — tap/hold/toggle/joystick/drag/aim/mouse_camera/wheel/layer_shift
│   ├── runtime.py                 runtime com provider injetado; mode="simulation"
│   ├── diagnostics.py             Diagnostics — injection_claimed=False
│   ├── editor_model.py            BindingEditor — undo/redo, conflitos, dirty state (sem Qt)
│   ├── qt_bridge.py               binding_from_qt_key/mouse, canonical_for_qt_key
│   ├── profile_bridge.py          conversão V1↔V2, validação
│   ├── providers/{base,simulated}.py
│   └── backends/{phantom_adapter,recording}.py
├── services/
│   ├── process_runner.py          execução sem shell/elevação
│   ├── command_paths.py           system_python(), resolve_command() [untracked]
│   ├── parsing.py                 waydroid_status() com FROZEN, parse_waydroid_apps()
│   ├── waydroid_service.py        start/stop/restart/unfreeze/launch/install/props/gamepad
│   ├── adb_service.py             ADB
│   ├── phantom_service.py         comandos Phantom
│   ├── capabilities.py            collect(), assess_backend(), BackendStage
│   ├── system_check.py            checagem de requisitos
│   └── xapk.py                    extract_apk_members() com cotas [untracked]
└── widgets/{common,game_card}.py
```

**Fronteira preservada:** o núcleo (`controls/model.py`, `input/editor_model.py`, `input/engine.py`, `services/*`) é independente de Qt. Acoplamento Qt existe em `main_window.py`, `theme.py`, `screens/*` e `widgets/*`. Essa separação deve ser mantida.

---

## 2. Mapa funcionalidade ↔ módulo

| Funcionalidade | Módulo atual | Módulo alvo | Camada | Status |
|---|---|---|---|---|
| Home / navegação / tema | `main_window.py`, `theme.py` | manter + `ui/sidebar.py` (NOVO) | 1 | Implementado |
| Barra lateral de ferramentas | — | `ui/sidebar.py` (NOVO) | 1 | NÃO IMPLEMENTADO |
| Biblioteca (grade/busca/filtros) | `screens/library.py`, `screens/home.py`, `services/library_metadata.py`, `models.py` | manter | 1 | **Implementado e testado** (favoritos, categorias, busca por nome/package ID, estado da instalação e último comando aceito) |
| Detecção de pacotes | `services/parsing.py`, `waydroid_service.py` | `runtime/waydroid_backend.py::list_apps` | 2 | **Implementado e testado** (manager + CLI injetado) |
| Instalação APK/XAPK | `services/xapk.py`, `waydroid_service.py` | `services/installer.py`, `runtime/manager.py::install_app` | 2 | **Implementado e testado** (planejador + manager; instalação real permanece explícita) |
| Remoção de app e propriedades | `services/waydroid_service.py` | `runtime/manager.py::{remove_app,get_property,set_property}` | 1/2 | **Implementado e testado** (validação de package/chave/valor; `prop get` bloqueado se `FROZEN`) |
| Verificação de assinatura | — | `services/apk_signature.py`, `services/installer.py` | 2 | **Implementado e testado** (identidade v2/v3, falha fechada; não é validação criptográfica) |
| Resolução de comandos | `services/command_paths.py` | manter | 2 | Implementado (untracked) |
| Ciclo de vida Waydroid | `services/waydroid_service.py` → `runtime/qt_bridge.py` → `runtime/manager.py` | manter | 1/2 | **Implementado e testado** (operações núcleo) |
| Parser de estado | `services/parsing.py` | `runtime/waydroid_backend.py::parse_status_output` | 2 | Implementado e testado (sessão/container separados) |
| ADB | `services/adb_service.py` | manter + interface | 2 | Parcial |
| **Abstração de runtime** | — | `runtime/backend.py` | 2 | **IMPLEMENTADO E TESTADO** |
| **Orquestração/estado/timeout/eventos** | — | `runtime/manager.py` | 2 | **IMPLEMENTADO E TESTADO** |
| **Adaptador falso** | — | `runtime/fake_backend.py` | 2 | **IMPLEMENTADO E TESTADO** |
| **Freeze/Unfreeze oficiais** | `services/waydroid_service.py::freeze()` | `runtime/waydroid_backend.py` (D-Bus `id.waydro.Container`) | 1/2 | **IMPLEMENTADO COM MOCK**; nunca executado no host |
| **Ponte Qt para a UI** | — | `runtime/qt_bridge.py`, `runtime/presentation.py` | 1/2 | **IMPLEMENTADO E TESTADO** (argumentos nomeados para operações auxiliares) |
| **Operações auxiliares no manager** | `services/waydroid_service.py` | `runtime/models.py`, `manager.py`, `waydroid_backend.py`, `fake_backend.py`, `qt_bridge.py` | 1/2 | **IMPLEMENTADO E TESTADO** (`list_apps`, `launch_app`, `install_app`, `remove_app`, `get_property`, `set_property`, `diagnostics`) |
| **Detecção de superfície real — parser** | `services/display_metrics.py` | manter | 2 | **IMPLEMENTADO E TESTADO** (15 testes) |
| **Detecção de superfície real — serviço Qt** | — | `services/display_metrics_service.py` | 1/2 | **IMPLEMENTADO E TESTADO** (3 testes) — somente leitura, runner injetado |
| **Detecção de superfície real — uso no editor** | `ControlsScreen` + referência documentada | integrar `display_metrics` em `ControlsScreen` | 1 | **IMPLEMENTADO E TESTADO** (4 testes) — botão "Detectar resolução", status `MEDIDA`/`REFERÊNCIA`/`NÃO MEDIDA` |
| Instance Manager | — | `instances/{model,manager,snapshot}.py` (NOVOS) | 3 | NÃO IMPLEMENTADO |
| Integridade/checksums | — | `data/integrity.py` (NOVO) | 6 | Parcial (fora do repo) |
| Editor visual V2 | `screens/controls.py`, `input/editor_model.py` | manter + organizar | 1/4 | Parcial |
| Perfis/validação | `controls/model.py`, `input/profile_bridge.py` | manter | 4 | Implementado e testado |
| Input Engine | `input/engine.py`, `normalizer.py`, `contacts.py` | manter | 4 | Implementado e testado |
| SAFE_RELEASE | Input Engine | manter | 4 | Implementado e testado |
| Cursor virtual | `controls/cursor.py` | manter | 4 | Implementado e testado |
| Provider simulado | `input/providers/simulated.py` | isolar | 4 | SIMULADO |
| RecordingTouchBackend | `input/backends/recording.py` | isolar | 4 | SIMULADO |
| PhantomAdapter | `input/backends/phantom_adapter.py` | isolar | 4 | SIMULADO |
| Backend real de injeção | — | `input/backends/linux_uinput.py` (NOVO) | 4 | NÃO IMPLEMENTADO |
| Gamepad evdev | — | `input/gamepad.py` (NOVO) | 4 | NÃO IMPLEMENTADO |
| Macro runtime | `input/engine.py` (`macro_runtime_disabled`) | `macros/recorder.py` (NOVO) | 4 | NÃO IMPLEMENTADO |
| Capacidades/GPU | `services/capabilities.py`, `system_check.py` | `performance/monitor.py` (NOVO) | 5 | Parcial |
| FPS/frametime/temps | — | `performance/monitor.py` (NOVO) | 5 | NÃO IMPLEMENTADO |
| Config gráfica por perfil | — | `performance/profiles.py` (NOVO) | 5 | NÃO IMPLEMENTADO |
| Storage atômico | `storage.py` | manter | 6 | Implementado e testado |
| Migrações | `storage.py`, `input/profile_bridge.py` | `data/migrations.py` | 6 | Parcial (V1→V2) |
| Logs/relatórios sanitizados | — | `data/reports.py` (NOVO) | 6 | NÃO IMPLEMENTADO |

> `runtime/` **já existe** (`models.py`, `errors.py`, `backend.py`, `manager.py`, `fake_backend.py`, `waydroid_backend.py`). Os caminhos `ui/`, `instances/`, `performance/` e `data/` continuam propostos. Antes de mover arquivos existentes, confirmar imports e testes. A prioridade é **adicionar** módulos, não reorganizar os atuais.

---

## 3. Dependências entre camadas

```
[1] Interface (main_window, screens, widgets, theme)
       │  usa
       ▼
[2] Runtime Manager (runtime/manager.py → runtime/backend.py → waydroid_backend.py)
       │  usa
       ▼
[3] Instance Manager (instances/)  ← só após prova de isolamento
       
[1] usa [4] Input Engine (engine, editor_model, providers, backends)
[1] usa [5] Performance (capabilities, monitor, profiles)
[2,3,4,5] persistem em [6] Data & Recovery (storage, integrity, reports)
```

**Regras:**
- `runtime/`, `input/`, `data/` **não** importam PySide6.
- A UI apenas configura perfis e consome eventos; lógica de controle não vive em widgets.
- `performance/` expõe leituras — nunca aplica limites automáticos no kernel.
- Backend trocável por fake em testes; nenhum teste de unidade mexe no container.

---

## 4. Dívidas urgentes com evidência no código

| Dívida | Evidência | Impacto | Correção |
|---|---|---|---|
| ~~`1280x720` fixo no editor~~ | resolvido em `ControlsScreen`: referência `1920x1034` marcada `REFERÊNCIA / MANUAL` + medição explícita | — | **Concluído**; `MainWindow.resize(1280,720)` é apenas o tamanho da janela do launcher, não da superfície Android |
| ~~Sem `freeze`~~ | resolvido no adaptador via D-Bus oficial | — | **Núcleo pronto**; integração à UI pendente |
| ~~UI acoplada a `WaydroidService`~~ | resolvido para ciclo de vida, apps, propriedades, ADB e superfície via bridge; `WaydroidService` não tem mais `ProcessRunner` | — | **Núcleo pronto**; restam apenas keycodes em `services/adb_service.py` |
| Operações auxiliares fora do manager | keycodes em `services/adb_service.py` (cliente ADB separado) | escopo próprio, não é comando `waydroid` | migrar somente se existir operação real e fizer sentido arquitetural |
| ~~Hardcode de colunas da biblioteca~~ | resolvido: `LibraryScreen._columns_for_width()` (2/3/4) e atualização no resize | — | **Concluído**; `HomeScreen.games[:8]` permanece como recorte intencional da tela inicial |
| Keycodes Android fixos | 4/3/187/25/24 no serviço | limitado pelo Waydroid | documentar limite |
| Caminhos `/usr/bin/python3` | `command_paths.system_python()` | quebra em outras distros | mitigado por `LINUXDROID_SYSTEM_PYTHON` e `shutil.which` |
| ~~XAPK sem assinatura~~ | resolvido: `services/apk_signature.py` + `installer.py` | — | **Mitigado** com identidade v2/v3 e falha fechada; validação criptográfica completa permanece a cargo do Android |
| Macro desabilitado | `_dispatch_action` → `macro_runtime_disabled` | recurso anunciado mas inoperante | implementar com guardas |
| GUI não validada graficamente | PySide6 ausente no Python do sistema | 2 testes ignorados | executar suíte no `.venv` |

---

## 5. Sequência de implementação por etapa

### P0 — Estabilização do Android (atual)
- Diagnóstico do Native Bridge concluído; alteração `ndk_translation.mode` **não autorizada**.
- Nenhuma alteração de sistema nesta etapa.

### P1 — Núcleo do emulador

**Concluído nesta rodada:**
- `services/display_metrics.py` + 15 testes (196 → 211): parser puro, `from_command_outputs()` e status `MEDIDA`/`REFERÊNCIA`/`NÃO MEDIDA`.
- `services/display_metrics_service.py` + 3 testes: sequência de consultas somente leitura com runner injetado, sem medição automática.
- `ControlsScreen` + 4 testes de integração: referência documentada `1920×1034@60 Hz, dpi 180` como `REFERÊNCIA / MANUAL`, botão "Detectar resolução", resultado `NÃO MEDIDA` não apaga configuração manual. `BindingEditor.set_screen(..., source=)` registra `measured`/`user`.
- Pacote `linuxdroid/runtime/` completo + 45 testes: modelos separados, erros estruturados, `RuntimeBackend`, `RuntimeManager`, `FakeRuntimeBackend`, `WaydroidRuntimeBackend` com CLI e D-Bus injetados, `freeze`/`unfreeze` pelo método oficial sem executá-los no host, bridge Qt e conversões para a UI. Contrato em `docs/RUNTIME_MANAGER_CONTRACT.md`.
- Interface integrada ao manager para as operações de ciclo de vida: `qt_bridge.py` + delegação em `WaydroidService`, preservando sinais e callbacks.

- `services/apk_signature.py` + 7 testes e `services/installer.py` + 4 testes: identidade do assinante v2/v3, comparação entre splits, falha fechada para assinatura inconclusiva e remoção de splits rejeitados. A tela Waydroid usa o planejador antes de instalar.
- `services/library_metadata.py` + 9 testes: categorias, busca por nome/package ID, filtros de favoritos/categoria, ordenações por nome/recente/favoritos e `record_launch()`. `GameEntry` ganhou `favorite`, `category`, `last_launched_at` e `launch_count`; `storage.load_library()` ignora campos desconhecidos de versões antigas. `LibraryScreen`, `HomeScreen` e `GameCard` integrados com 6 testes GUI. **`last_launched_at` registra o comando aceito, não a abertura do jogo nem o lobby.**

**Suíte:** **333 testes** — 333 OK no `.venv` (PySide6 6.12.0); 333 OK no Python do sistema com 39 skips (GUI, bridge, serviço de tela e auxiliares Qt).

**Concluído nesta rodada:** operações auxiliares `list_apps`, `launch_app`, `install_app` e `diagnostics` passaram a existir como `RuntimeOperation` com `AUXILIARY_FEATURES`; validação de package ID/arquivo/estado ativo antes do subprocesso; serialização com mutações; timeout/cancelamento/eventos/histórico; `INVALID_ARGUMENT` estruturado; adaptador Waydroid e backend falso atualizados; ponte Qt com argumentos nomeados; `WaydroidService` delegando as três operações usadas pela UI. 15 testes novos, nenhum comando real executado.

**Concluído nesta rodada (filtros):** `library_metadata.STATES` expõe `installed`, `unconfirmed` e `launched` (comando aceito) sem inventar campo `running`; `LibraryScreen` mostra o seletor e um aviso de que "comando aceito" não prova jogo em execução; `GameCard` passa a dizer "instalação não confirmada" quando aplicável; 6 testes novos (4 puros + 2 GUI).

**Concluído nesta rodada (props/remoção):** `remove_app`, `get_property` e `set_property` passaram a existir como operações reais com `AUXILIARY_FEATURES`, validação de package/chave/valor, serialização e capacidade explícita. `get_property` e `set_property` são recusados com `INVALID_TRANSITION` quando o container está `FROZEN`, cumprindo a regra de nunca consultar `prop get` nesse estado. `operation_to_command_result` preserva o valor da propriedade em `stdout` para o callback antigo da tela. 9 testes novos (7 puros + 2 Qt).

**Concluído nesta rodada (layout):** `LibraryScreen` usa 2 colunas abaixo de 560 px, 3 abaixo de 860 px e 4 acima disso, com reagendamento via `QTimer` quando a largura muda. 1 teste GUI novo.

**Concluído nesta rodada (ADB/superfície):** `adb_connect` e `show_full_ui` passaram a existir como `RuntimeOperation` com capacidade explícita e são exigidos com sessão **e** container `RUNNING`. `WaydroidRuntimeBackend` usa `waydroid adb connect` e `waydroid show-full-ui` (CLI injetado); `WaydroidService` deixou de ter `ProcessRunner` — todo comando `waydroid` da interface passa pelo manager via ponte Qt. A conexão ADB ainda depende da autorização no Android e nenhum comando real foi executado nos testes. 3 testes novos (2 puros + 1 Qt).

**Concluído nesta rodada (desinstalação):** `GameCard` oferece "Remover" somente para pacotes confirmados pelo Android com package ID válido; `MainWindow.remove_game()` exige confirmação explícita (padrão NÃO), sessão `RUNNING` e usa `RuntimeManager.remove_app()`. O registro local passa a `missing` e `last_launched_at` é limpo apenas quando o comando é aceito — nenhuma alegação de que o Android concluiu a exclusão fora do texto do backend. 5 testes GUI, nenhum comando real executado.

**Concluído nesta rodada (barra lateral P4):** `widgets/tool_rail.py` implementa 19 ferramentas no trilho direito; só Navegação (Controles/ADB/Config/Instalar), Tela cheia e Reabrir último jogo têm ação real. Tela cheia e Reabrir exigem sessão `RUNNING`, e Reabrir exige um comando de lançamento previamente aceito. Todas as demais ficam desabilitadas com tooltip "NÃO IMPLEMENTADO" e motivo, conforme §3.4 da especificação visual. 6 testes GUI, nenhum comando real executado.

**Avaliação de ícone/capa (concluída, sem implementação):** o host não tem `aapt`, `aapt2`, `apkanalyzer` nem `apksigner` (verificado por `command -v`); apenas `unzip`/`zipinfo` estão disponíveis. Extrair o ícone real exige resolver `android:icon` em `AndroidManifest.xml` binário e o recurso correspondente em `resources.arsc`; casar nomes como `ic_launcher*` por heurística pode mostrar o ícone errado. Não há APK local para validação de ponta a ponta. Decisão: **não** implementar extração automática agora e manter `GameEntry.icon_path` como escolha explícita do usuário. Uma implementação futura deve usar ferramenta injetada com capacidade `UNSUPPORTED` quando ausente, ou parser puro validado com fixtures sintéticas e ao menos um APK real; nunca reutilizar recursos do BlueStacks.

**Próximos passos:**
1. Inspeção visual das 128 imagens na etapa final, por decisão do usuário.
2. Manter keycodes como cliente ADB separado, sem promoção falsa a operação do runtime.

**Critério de pronto:** operações de ciclo de vida, apps (inclusive remoção confirmada), propriedades, ADB e superfície sem chamada direta a Waydroid na UI (concluído); `status()` distingue `RUNNING`/`FROZEN`/`STOPPED`/`UNKNOWN` (concluído); `prop get` bloqueado com container congelado (concluído); resolução medida substitui o hardcode no editor (concluído); instalação com verificação de assinante (concluído); biblioteca com favoritos/categorias/estado/último comando aceito e grade responsiva (concluído); 333 testes continuam OK.

### P2 — Controles reais
- `input/backends/linux_uinput.py` com permissão específica; captura de tela real; SAFE_RELEASE com backend real; gamepad evdev; investigar pointer constraints Wayland. Começar em app de demonstração.

### P3 — Editor e perfis
- Organizar editor V2, camadas, sensibilidade, import/export e `ScreenContract` validado contra a resolução medida.

### P4 — Experiência avançada
- Barra lateral, screenshot, gravação, clipboard, mídia, monitor de desempenho, macros com guardas de segurança.

### P5 — Instâncias
- **Pré-requisito:** prova de isolamento (rede, processos, armazenamento, Binder, GPU). Só depois CRUD/clone/backup/restore.

### P6 — Compatibilidade
- Matriz AMD/Intel/NVIDIA, Wayland/X11, compositores, ARM64/ARM32 com relatórios por ABI.

### P7 — Acabamento
- UX, instalador, atualizações, relatórios sanitizados, empacotamento.

---

## 6. Riscos arquiteturais e mitigação

| Risco | Impacto | Mitigação |
|---|---|---|
| Multi-instância falsa | Corrupção de dados | Não implementar; provar isolamento antes |
| Backend simulado confundido com real | Falsa propaganda | Flags `functional/tested/operational=False`, nomes explícitos |
| Lógica de controle em widgets | Impossível testar sem GUI | Input Engine puro — já é a realidade atual, preservar |
| Acesso amplo a `/dev/input` | Segurança do host | Permissão específica, nunca regras udev genéricas |
| `grabMouse()` em Wayland | Captura não funciona | Investigar protocolos; declarar limitação se não der |
| ~~Hardcode de resolução~~ | ~~Perfis errados~~ | Mitigado: `display_metrics.py` + serviço somente leitura + `ControlsScreen` com status explícito; referência nunca é rotulada como medição |
| Cópia de código de terceiros | Risco jurídico | BlueStacksRoot apenas conceitual (CC BY-NC-ND 4.0) |
| Mudança de sistema sem autorização | Perda de dados | Uma variável, backup, rollback, autorização explícita |

---

## 7. Documentos relacionados

- `MASTER_PRODUCT_VISION.md` — visão, princípios, critério de sucesso.
- `BLUESTACKS_FEATURE_PARITY.md` — matriz recurso a recurso.
- `UI_DESIGN_SPEC.md` — especificação visual própria (em elaboração, após referências).
- `references/bluestacks/INDEX.md` — referências visuais oficiais com atribuição.
- `references/bluestacks/ANALISE_FUNCIONAL.md` — fluxos documentados.
- `V3.md` — detalhes do Input Engine V3 e limitações.
