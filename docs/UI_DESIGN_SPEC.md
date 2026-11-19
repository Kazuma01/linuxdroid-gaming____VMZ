# LinuxDroid Gaming — Especificação da Interface

**Versão:** 1.0
**Data:** 19/11/2026
**Base:** fluxos extraídos de 8 páginas oficiais do BlueStacks 5 + inventário real do código do LinuxDroid
**Base Git:** `a4c06ac`

---

## 0. Estado da pesquisa visual — LEIA PRIMEIRO

| Item | Status |
|---|---|
| 8 páginas oficiais consultadas | **CONCLUÍDO** — texto extraído e citado em `references/bluestacks/ANALISE_FUNCIONAL.md` |
| 128 imagens oficiais baixadas, deduplicadas e organizadas | **CONCLUÍDO** — ver `references/bluestacks/INDEX.md` e `DOWNLOAD_LOG.md` |
| **Inspeção visual das imagens** | **NÃO REALIZADA** — o modelo Utilizado nesta sessão não aceita entrada de imagem. A tentativa de abrir `game-library/recursos_biblioteca_jogos1.jpg` retornou explicitamente `this model does not support image input`. |
| Descrições de cor, espaçamento, tipografia, ícones e layout das capturas | **NÃO PRODUZIDAS**. Nenhuma linha deste documento afirma ter visto uma imagem. |

**Consequência metodológica:** esta especificação deriva de **fluxos e requisitos documentados em texto**, não da aparência das capturas. Ela define estrutura de navegação, páginas, painéis, estados e interações — o que a documentação oficial permite comprovar. A camada puramente visual (paleta final, densidade, ilustrações, proporções de ícones) permanece como **projeto próprio**, sem pretensão de replicar o BlueStacks.

Para concluir o estudo visual falta um modelo com entrada de imagem, ou uma descrição humana das capturas. As imagens já estão organizadas e prontas para essa etapa.

---

## 1. Princípios de design do LinuxDroid

1. **Identidade própria.** Cores, tipografia, ícones e ilustrações são originais. Nenhum asset do BlueStacks é incorporado ao produto.
2. **Estado honesto na tela.** O usuário vê `MEDIDA`, `REFERÊNCIA / MANUAL` ou `NÃO MEDIDA`; `SIMULADO`, `EM DESENVOLVIMENTO` ou `NÃO IMPLEMENTADO`. Nunca um botão que pareça funcional sem sinalizar que não foi validado.
3. **Sem terminal no cotidiano.** LXC, Binder, ADB, Native Bridge e propriedades ficam em diagnóstico avançado, protegido e opcional.
4. **Uma ação, um resultado.** Cada comando mostra progresso, sucesso ou falha com mensagem acionável. Nenhuma operação destrutiva sem confirmação.
5. **Layout adaptativo.** A janela do launcher pode mudar de tamanho; a superfície Android é uma janela separada gerenciada pelo compositor Wayland, **não** um widget Qt incorporado.
6. **Menor privilégio.** Recursos de entrada e depuração são explícitos e desligados por padrão.
7. **Um único caminho para o runtime.** A UI não executa `waydroid`, `adb` ou `busctl`: ela envia intenções ao `RuntimeManager` e renderiza `RuntimeSnapshot` + `OperationResult` + eventos. Contrato em `RUNTIME_MANAGER_CONTRACT.md`.

### 1.1 Estado exibido pelo Runtime Manager (implementado nesta rodada)

O status da Home e da Central Android passa a ser interpretado a partir de dois campos independentes:

| Objeto | Campo | Uso na tela |
|---|---|---|
| `RuntimeSnapshot` | `session_state` | "Sessão: RUNNING / STARTING / STOPPING / STOPPED" |
| `RuntimeSnapshot` | `container_state` | "Container: RUNNING / FROZEN / STOPPED" |
| `RuntimeSnapshot` | `effective_state` | **resumo visual apenas**; nunca usado para autorizar transição |
| `RuntimeSnapshot` | `runtime_availability` | aviso de `NOT_FOUND`, `PERMISSION_DENIED`, `SERVICE_UNAVAILABLE` |
| `RuntimeSnapshot` | `active_operation` | indicador de operação em andamento |
| `RuntimeSnapshot` | `last_error` | faixa de erro com código traduzível e `retryable` |
| `OperationResult` | `ok`, `failure`, `message`, `skipped` | resposta de cada botão |
| `RuntimeEvent` | `kind`, `timestamp` | log técnico e histórico |

**Regra visual obrigatória:** `Session: RUNNING` + `Container: FROZEN` deve aparecer como **"Android congelado"** com ação **Reativar**, nunca como "Ativo" e nunca como "Parado".

**Botões e estados (`skipped`, implementado):**

| Ação | Estado atual | Resultado na UI |
|---|---|---|
| Congelar | container já `FROZEN` | "Já congelado; nada a fazer" — sem erro, sem comando |
| Reativar | container já `RUNNING` | "Já ativo; nada a fazer" — sem erro, sem comando |
| Iniciar | sessão `RUNNING` + container `FROZEN` | recusado com dica de Reativar |
| Qualquer ação duplicada | operação em andamento | "Operação duplicada" |
| Falha de permissão/timeout | erro estruturado | mensagem acionável + badge `retryable` |

**Componente de UI ainda a criar:** `StatusPill` (item 4) deve consumir `effective_state` e `runtime_availability`; o bridge Qt ainda não foi implementado, então a tela atual ainda usa o serviço antigo.

---

## 2. Estrutura de navegação

```
LinuxDroid Gaming
├── Home
│   ├── Jogos recentes (máx. 8 — já existe em HomeScreen)
│   ├── Ações rápidas: Abrir Android, Instalar app, Atualizar biblioteca
│   └── Status do runtime: RUNNING / FROZEN / STOPPED / UNKNOWN
├── Biblioteca
│   ├── Grade / lista
│   ├── Busca por nome e package ID (já existe)
│   ├── Filtros: favoritos, categoria e estado [IMPLEMENTADO]; "em execução" por jogo [NÃO IMPLEMENTADO — sem fonte confiável]
│   └── Cartão de jogo → abrir [SIM], estrela de favorito [SIM], desinstalar [NÃO]
├── Instâncias                                                  [NÃO IMPLEMENTADO]
│   ├── Lista com ID, nome, estado, ABI, resolução, CPU, RAM
│   ├── Criar / clonar / renomear / iniciar / parar / excluir
│   └── Configurações por instância (somente quando inativa)
├── Controles                                                   [editor V2 existe]
│   ├── Seletor de perfil por jogo (criar, renomear, copiar, importar, exportar)
│   ├── Canvas sobre a superfície Android
│   ├── Paleta de tipos de controle
│   ├── Configurações avançadas do controle selecionado
│   └── Estado do backend: SIMULADO / EM DESENVOLVIMENTO / VALIDADO
├── Desempenho                                                  [parcial]
│   ├── GPU / OpenGL / Vulkan / Mesa detectados
│   ├── CPU, RAM, temperatura, armazenamento
│   ├── Perfis: equilibrado, desempenho, econômico              [NÃO IMPLEMENTADO]
│   └── FPS: configurado ≠ efetivo                              [NÃO IMPLEMENTADO]
├── Configurações
│   ├── Geral, interface, idioma, atalhos
│   ├── Exibição: resolução, DPI, escala, orientação
│   ├── Gráficos: renderizador, texturas, GPU preferida         [NÃO IMPLEMENTADO]
│   ├── Dispositivos: áudio, microfone, câmera, gamepad
│   └── Desempenho: checagem de requisitos (já existe, somente leitura)
├── Mídia                                                       [NÃO IMPLEMENTADO]
│   ├── Capturas, gravações, pasta de mídia
│   └── Importar/exportar
├── Diagnóstico                                                 [parcial]
│   ├── Logs e relatórios sanitizados                            [NÃO IMPLEMENTADO]
│   ├── Integridade/checksums                                   [NÃO IMPLEMENTADO]
│   └── ADB Debug — protegido e opcional
└── Sobre
```

**Nota:** itens marcados como NÃO IMPLEMENTADO aparecem no projeto de navegação para definir o destino, mas devem ser exibidos na interface como **indisponíveis com motivo**, não como botões que não fazem nada.

---

## 3. Páginas e painéis

### 3.1 Home

**Função:** ponto de entrada; mostrar o que está pronto e o que precisa de atenção.

**Elementos:**
- Cabeçalho com nome do produto e status do runtime.
- Faixa de status do container. Se `FROZEN`, exibir aviso explícito e ação "Reativar Android" (comportamento já implementado em `MainWindow.play()`).
- Cartões de jogos recentes (`HomeScreen`, `recent_games(games, 8)`). Favoritos e jogos com lançamento registrado aparecem primeiro; jogos sem histórico nunca recebem data inventada. `last_launched_at` marca o comando de lançamento **aceito**, não a abertura do jogo.
- Ações rápidas: Abrir Android, Instalar APK/XAPK, Atualizar biblioteca.
- **Instalação (implementado):** antes de instalar, `services/installer.py` verifica a identidade do assinante (v2/v3) de todos os splits. Assinatura inconclusiva ou assinantes diferentes geram aviso explícito e nenhuma instalação. A checagem **não** é validação criptográfica do arquivo e não substitui o Android; APKs assinados apenas com v1 são recusados com mensagem clara.

**Estados do runtime e significado na UI:**

| Estado | Texto exibido | Ação oferecida |
|---|---|---|
| `RUNNING` | Android ativo | Abrir jogo |
| `FROZEN` | "Sessão existe, mas o Android está congelado" | Reativar |
| `STOPPED` | Android encerrado | Iniciar |
| `NOT_INITIALIZED` | Waydroid não inicializado | Abrir diagnóstico |
| `UNKNOWN` | Estado não identificado | Atualizar / diagnóstico |

> Nunca mostrar `RUNNING` quando o container está `FROZEN` — decisão já implementada no parser (`services/parsing.py`).

### 3.2 Biblioteca

**Função:** encontrar e abrir jogos instalados.

**Evidência documentada de origem:** "Inicie um jogo, abra o editor de Controles…" (U1) e "Launch any game and then click on the 'Game controls' icon on the Side toolbar" (U5). As páginas **não** documentam filtros de biblioteca; portanto filtros são requisito nosso, não replicação.

**Elementos:**
- Grade responsiva com 2 colunas abaixo de 560 px, 3 abaixo de 860 px e 4 acima disso, com scroll (`LibraryScreen`). Alternância grade/lista [NÃO IMPLEMENTADO].
- Busca por nome e package ID, sem diferenciar maiúsculas (`filtered_games`).
- Filtros implementados: "Só favoritos", categoria, estado e ordenação (nome / último lançamento / favoritos). O filtro de estado oferece: **instalados** (`installed_status == "installed"`, originado de `waydroid app list`), **instalação não confirmada** (`unknown`/`missing`) e **comando de lançamento aceito** (`last_launched_at` preenchido). A interface explicita que o último não significa jogo em execução, ativo ou no lobby.
- Estado "em execução" por jogo [NÃO IMPLEMENTADO]: não existe hoje fonte confiável que o comprove sem medição; nenhum campo `running` foi inventado no modelo.
- Cartão de jogo: nome, package, estado da instalação ("instalado" / "não encontrado" / "instalação não confirmada"), **último comando aceito** e estrela de favorito. Ícone real [NÃO IMPLEMENTADO].
- Ações por cartão: Abrir [SIM], favoritar [SIM], **Desinstalar [SIM, somente para instalação confirmada com package ID válido]**: botão "Remover" exige confirmação (padrão NÃO), Android ativo e passa por `RuntimeManager.remove_app()`; o registro local passa a `missing` quando o comando é aceito. Controles/Informações [NÃO IMPLEMENTADO]. "Fechar" e "Atualizar" app [NÃO IMPLEMENTADO].

**Persistência:** `GameEntry` inclui `favorite`, `category`, `last_launched_at` e `launch_count`; `storage.load_library()` ignora campos desconhecidos de versões anteriores. A estrela usa `QTimer.singleShot(0, refresh)` para não destruir o emissor do sinal durante a recriação dos cards.

**Regra de detecção:** a lista vem de `parse_waydroid_apps()` / `waydroid app list`. Nunca de uma lista fixa de nomes. `last_launched_at` é gravação local do comando aceito — **não** é evidência de que o jogo abriu ou chegou ao lobby.

### 3.3 Editor de controles

**Fluxo documentado (U1):**
1. Iniciar jogo.
2. Abrir editor pelo ícone "Controles do jogo" na barra lateral, ou clique direito → "Editor de Controles".
3. Escolher esquema no menu suspenso; se não houver, "Criar um novo perfil".
4. Selecionar tipo de controle na galeria, arrastar e soltar sobre o controle do jogo.
5. Clicar no controle e pressionar a nova tecla para reatribuir.
6. Configurações avançadas: passar o mouse sobre o controle → ícone de engrenagem → painel → personalizar.
7. Salvar. Redefinir volta ao padrão.
8. Alternar esquemas em jogo: `Ctrl+Shift+Q` (atalho configurável).

**Tipos documentados na galeria (U1):** Ponto de toque, Toque repetido, D-pad, Mirar/pan/atirar, Visão livre, Script, Deslizar, Zoom, Inclinar, D-Pad MOBA, MOBA Skill pad, Rotacionar, Rolagem de borda, Rolagem, Roda do mouse.

**Como isso mapeia no LinuxDroid:**

| Tipo documentado | Recurso no LinuxDroid | Situação |
|---|---|---|
| Ponto de toque | `tap` | Implementado e testado |
| Toque repetido | `repeat_tap` | Dado existe; runtime desabilitado (`macro_runtime_disabled`) |
| D-pad | joystick / bindings | Implementado e testado |
| Mirar/pan/atirar | `aim`, `mouse_camera` | Ação no engine; captura real de ponteiro não implementada |
| Visão livre | `mouse_camera` | Implementado no engine |
| Script / macro | — | Runtime não implementado, por decisão de segurança |
| Deslizar | `drag` | Implementado e testado |
| Zoom / rolagem / roda | `wheel` | Implementado e testado |
| Inclinar / Rotacionar / sensores | — | Não implementado; depende de sensor no Waydroid |
| D-Pad MOBA / Skill pad | layers + bindings parcialmente | A avaliar |

**Requisitos de UI derivados:**
- Seletor de esquema sempre visível no topo do editor, com criar/renomear/copiar/importar/exportar.
- Paleta de controles categorizada; clique em um item mostra descrição curta (equivalente funcional ao "clicar para saber mais" documentado).
- Canvas com a **resolução real da superfície**, nunca `1280x720` fixo. **Implementado:** `ControlsScreen` usa a referência documentada `1920×1034@60 Hz, dpi 180` marcada `REFERÊNCIA / MANUAL`; o botão "Detectar resolução" dispara consultas **somente leitura** (`wm size`, `wm density`, `dumpsys display`) via `services/display_metrics_service.py` e atualiza o rótulo para `MEDIDA`. Um resultado `NÃO MEDIDA` não apaga a configuração manual. Nenhuma medição acontece em segundo plano. Ver `RUNTIME_MANAGER_CONTRACT.md` e `test_controls_display_integration.py`.
- Painel de configuração avançada contextual ao controle selecionado, aberto por duplo clique ou botão de engrenagem.
- Botões Salvar e Redefinir sempre acessíveis; alterações não salvas marcadas como `dirty` (já existe em `BindingEditor`).
- Aviso de que esquemas padrão podem ser revertidos em atualização — documentado em U1.

### 3.4 Barra lateral de ferramentas

**Função documentada (U6):** "quick access to very useful tools that let you take screenshots, manage game volume, run macros, customize game controls". Fica no lado direito da tela inicial/do jogo.

**Ferramentas documentadas (U6):** fechar barra, tela cheia, volume, travar cursor, controles do jogo, gerenciador de macros, sincronização, limpar memória, instalar APK, screenshot, gravação, pasta de mídia, modo avião, girar, sacudir, definir localização, gerenciador de multi-instância, modo Eco, configurações, voltar, Home, apps recentes.

**Projeto LinuxDroid (ordem e agrupamento próprios):**

| Grupo | Ferramentas | Implementação hoje |
|---|---|---|
| Navegação | Home, Voltar, Apps recentes | **Desabilitadas** no trilho: keycodes não foram validados com injeção real |
| Tela | Tela cheia, Travar/liberar cursor, Girar | Tela cheia **implementada** (`show_full_ui`, exige Android ativo); demais desabilitadas |
| Mídia | Screenshot, Gravação, Pasta de mídia | **Desabilitadas**: captura/gravação reais não existem |
| Jogo | Controles, Macro manager, Monitor de desempenho, Reabrir | Controles e Reabrir **implementados**; macro e monitor desabilitados |
| Sistema | Instalar APK/XAPK, Volume, Modo Eco, Multi-instância, Configurações | Instalar e Configurações **implementados**; demais desabilitadas |
| Avançado | ADB Debug (protegido), Diagnóstico | ADB abre a Central Android (conexão exige autorização); demais desabilitadas |

**Implementação:** `widgets/tool_rail.py` com 19 entradas; `MainWindow._handle_tool()` só navega ou chama serviços para as ferramentas com backend real. "Tela cheia" e "Reabrir" exigem sessão `RUNNING`; "Reabrir" exige um comando de lançamento previamente aceito.

**Regra de segurança:** ferramentas não implementadas devem aparecer desabilitadas com tooltip explicando o motivo. "Travar cursor" só pode ser ativado se a captura real de ponteiro estiver implementada e validada — nunca usar `QWidget.grabMouse()` como substituto.

### 3.5 Instâncias

**Fluxo documentado (U2/U7):**
- Criar: botão "Instância" no gerenciador → assistente.
- Clonar: "Clonar instância".
- Organizar: "Ordenar por" Nome ou Engine; busca no canto superior direito.
- Lote: caixas de seleção → iniciar, parar, excluir; "Selecionar tudo".
- Alinhar janelas: ícone de grade → "Organizar tudo" / "Organizar selecionados".
- Configuração por instância: **somente quando inativa**; engrenagem → aba Performance (CPU, memória, FPS) ou Display (resolução, orientação, DPI, escala) → Salvar → aplica no próximo lançamento.

**Projeto LinuxDroid:** mesma arquitetura de informação (lista, seleção, lote, configuração por instância inativa), com uma diferença obrigatória: até provar isolamento de Binder/rede/armazenamento/GPU, a tela deve exibir **"Multi-instância indisponível: Waydroid não oferece isolamento comprovado neste host"**, em vez de permitir criar instâncias falsas.

### 3.6 Configurações e Desempenho

**Documentado (U3):**
- CPU/RAM e modos de desempenho; taxa de quadros; VSync; overlay de FPS.
- Resoluções personalizadas; DPI 160/240/320 ou 10–999; escala de interface; até 4K.
- Renderizador gráfico (Vulkan & OpenGL ou OpenGL), renderizador de interface, texturas ASTC, GPU preferida; aplica após salvar e reiniciar.
- Câmera, alto-falante, microfone; pasta de mídia; idioma, atalhos, comportamento do ESC, notificações.
- Perfil de dispositivo e operadora móvel.
- "Salvar alterações" obrigatório.

**Projeto LinuxDroid:**
- Painel de Desempenho com checagem somente leitura **já existe** (`system_check.py`).
- Mostrar GPU detectada e caminho gráfico real (Mesa/OpenGL ES/Vulkan), com dados medidos separados de estimativas.
- **Nunca** exibir FPS configurado como se fosse FPS efetivo. Exibir dois campos distintos quando ambos existirem.
- Alterações que exigem reinício da sessão devem dizer isso explicitamente antes de confirmar.
- Perfis de dispositivo apenas com propriedades legítimas e documentadas; sem falsificar identidade.

### 3.7 Modo Eco

**Documentado (U4):** ativação por controle deslizante na barra lateral (instância atual) ou no gerenciador (todas as ativas); cor azul indica ativo; submenu permite som e FPS por instância; configurações de uma instância não afetam outra.

**Projeto LinuxDroid:** controle por instância, desligado por padrão, com aviso de que limites só serão aplicados após medição antes/depois. Sem alteração automática de parâmetros globais do kernel.

---

## 4. Componentes visuais (projeto próprio)

| Componente | Finalidade | Estado no código |
|---|---|---|
| `GameCard` | Cartão de jogo na biblioteca/home | Existe (`widgets/game_card.py`) — com botão Jogar, estrela de favorito, último comando aceito e Remover (habilitado somente para instalação confirmada) |
| Sidebar | Barra de ferramentas lateral | A criar |
| `StatusPill` | `RUNNING`/`FROZEN`/`MEDIDA`/`SIMULADO` | A criar |
| `ProfileSelector` | Seletor de esquema de controle | A criar (lógica de perfil já existe) |
| `ControlPalette` | Galeria de tipos de controle | Parcial (`ControlsScreen`) |
| `AdvancedPanel` | Configurações contextuais do controle | Parcial (`ControlsScreen`) |
| `MetricsPanel` | GPU/CPU/RAM/FPS medidos | A criar (`system_check` existe) |
| `ConfirmationDialog` | Operações destrutivas | A criar |
| `DiagnosticsPanel` | Logs sanitizados e checksums | A criar |

**Direção visual (original):** tema escuro com contraste alto, acento em azul-ciano, tipografia sem serifa do sistema, cantos moderados, densidade confortável. Isso é uma proposta nossa — não uma cópia de paleta, logo ou ícone observado. Deve ser validada por teste de legibilidade e acessibilidade.

---

## 5. Responsividade e escala

- A janela do launcher deve funcionar a partir de 1024×768 e escalar até 4K.
- Biblioteca: grade de 4 colunas em telas largas, 3 em larguras médias e 2 em telas estreitas — implementado em `LibraryScreen._columns_for_width()` com atualização no `resizeEvent`.
- Home: no máximo 8 jogos recentes; em telas estreitas, menos.
- Editor: canvas mantém a proporção da superfície Android real (`_screen_rect` já faz isso), com painel lateral recolhível em larguras pequenas.
- Nunca usar a resolução da janela do launcher como resolução do Android.

---

## 6. Matriz de conformidade com a referência

| Fluxo documentado | Como o LinuxDroid atende | Classificação |
|---|---|---|
| Abrir editor pelo ícone na barra lateral | Trilho direito implementado; botão "Controles" abre o editor | **Já existe e funciona** (GUI testada) |
| Arrastar controle da galeria para o jogo | Já existe no editor V2 | **Já existe e funciona** (GUI não validada neste interpretador) |
| Reatribuir tecla clicando no controle | Já existe (`qt_bridge`, identidade por scan code) | **Já existe e funciona** (lógica testada) |
| Salvar / redefinir esquema | Existe (storage atômico, BindingEditor) | **Já existe e funciona** |
| Criar/clonar instância | Não existe; Waydroid sem isolamento comprovado | **Exige outra arquitetura / prova de isolamento** |
| Configurar CPU/RAM por instância inativa | Não existe | **Depende de nova implementação** |
| Ativar Modo Eco | Não existe | **Depende de nova implementação** |
| Screenshot / gravação pela barra lateral | Não existe | **Depende de nova implementação** |
| Instalar APK/XAPK pela barra lateral | Botão "Instalar" abre a Central Android; instalação usa verificador de assinante | **Existe parcialmente** (seleção de arquivo na Central) |
| Gravador de macro | Runtime desabilitado por decisão de segurança | **Existe apenas como simulação/dado** |
| Alternar esquema em jogo (`Ctrl+Shift+Q`) | Não implementado | **Depende de nova implementação** |
| Tela cheia / girar / sacudir / localização | Não implementado | **Limitado pelo Waydroid / nova implementação** |
| Mostrar sessão e container separadamente | `RuntimeSnapshot` implementado e testado | **Núcleo pronto**; renderização na UI pendente |
| Congelar/reativar com idempotência | `RuntimeManager.freeze()/unfreeze()` com `skipped` e D-Bus oficial | **Núcleo pronto**; botão na UI pendente, execução real não autorizada |
| Timeout/cancelamento/erro estruturado | `RuntimeManager` + eventos + histórico | **Implementado e testado**; bridge Qt pendente |

---

## 7. Pendências para fechar a missão visual

1. **Inspecionar as 128 imagens** com modelo que aceite entrada de imagem ou com descrição humana, preenchendo a coluna "Descrição visual" de `INDEX.md`.
2. Validar a direção visual proposta (item 4) contra essa inspeção, ajustando espaçamento, hierarquia e estados.
3. Abrir o artigo de mira personalizado linkado em U1 (`https://support.bluestacks.com/hc/articles/16149598303245`) para detalhar o Modo de Disparo — hoje em DÚVIDA.
4. Abrir o artigo aprofundado de macros linkado pela barra lateral para completar o fluxo de gravação.
5. Executar os testes GUI no `.venv` com PySide6 para validar o editor e a ponte Qt (itens 1.1 e 3.3).
6. ~~Implementar o bridge Qt e fazer a UI usar exclusivamente o `RuntimeManager`~~ — concluído para o ciclo de vida (item 1.1).
7. ~~Integrar `display_metrics` ao `ControlsScreen`~~ — concluído: referência explícita + botão de medição somente leitura (item 3.3).
8. ~~Instalação com verificação de assinatura~~ — concluído (identidade v2/v3, falha fechada; §3.1).
9. ~~Biblioteca com favoritos, categorias e último lançamento~~ — concluído (item 3.2).
10. ~~Migrar operações auxiliares para o manager~~ — concluído para apps, propriedades, ADB e superfície (item 1.1).
11. ~~Barra lateral direita~~ — concluída com ferramentas reais e desabilitadas com motivo (item 3.4); permanece pendente apenas o que exige backend inexistente (captura, gravação, macros).

Nada nesta seção autoriza mudança de sistema, container, Native Bridge ou dados do jogo.
