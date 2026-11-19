# Histórico de versões

## Não lançado

- Novo estado `FROZEN`: `Session: RUNNING` com `Container: FROZEN` não é mais reportado como "Ativo". O launcher oferece reativar o container antes de abrir um jogo.
- A tela Waydroid não consulta mais `waydroid prop get` automaticamente na inicialização ou no `refresh()`; a consulta do modo de janela passou a ser explícita pelo botão Atualizar.
- A captura automática do Phantom deixou de usar o timer fixo de 1.600 ms e passou a depender de resultados observáveis: app aberto, perfil carregado, daemon disponível e comando de captura concluído.
- Resolução portátil de executáveis: `process_runner.py` não usa mais `/usr/bin/python` e `/usr/bin/waydroid` fixos. O Python do sistema é detectado automaticamente e pode ser sobrescrito com `LINUXDROID_SYSTEM_PYTHON`.
- Extração de XAPK com streaming, cotas por split/total e limite de razão de compressão; o ZIP é fechado mesmo em caso de falha.
- A mensagem de captura automática do Phantom não afirma mais injeção real: o exit code é reportado como “comando de captura aceito”.
- Documentação corrigida: README/docs/V3 não afirmam mais que o `.venv` existe nesta árvore, e o modo de diagnóstico com provider simulado está alinhado ao runtime.
- Testes unitários em `tests/test_command_paths.py` e `tests/test_xapk.py`.
- Testes unitários do parser de estado em `tests/test_waydroid_state.py`.
- Configurações → Desempenho: checagem de requisitos do sistema (sessão Wayland, Waydroid instalado, binder no kernel, GPU, RAM, CPU e acesso a /dev/input). Somente leitura, com dicas de correção.
- Testes unitários da checagem em `tests/` (`python -m unittest tests.test_system_check -v`).
- Documentação atualizada com dados medidos do ambiente: Android 13/Waydroid 1.6.3, GPU AMD confirmada no Android (Mesa 26.0.8, HWC 1.5), superfície 1920x1034@60 Hz e Native Bridge `libndk_translation.so` 0.2.3. Free Fire segue **não aprovado** (abort no tradutor antes do lobby); nenhum backend de entrada é declarado operacional sem teste físico.
- Novo módulo `services/display_metrics.py`: interpreta `wm size`, `wm density` e `dumpsys display` sem Qt e sem alterar o sistema. Nunca inventa resolução quando a saída está vazia e marca explicitamente valores históricos como `NÃO MEDIDOS`. Doze testes em `tests/test_display_metrics.py`.
- Documentação de produto criada: `docs/MASTER_PRODUCT_VISION.md`, `docs/BLUESTACKS_FEATURE_PARITY.md` e `docs/ARCHITECTURE_ROADMAP.md`, com estados honestos por funcionalidade e inventário real dos módulos.
- Novo pacote `linuxdroid/runtime/`: `RuntimeSnapshot` com sessão e container separados, `RuntimeBackend`, `RuntimeManager`, `FakeRuntimeBackend` e `WaydroidRuntimeBackend`. O manager centraliza validação de transições, serialização de operações, timeout, cancelamento cooperativo, recuperação, eventos, histórico e erros estruturados. CLI e D-Bus são injetados; `Freeze`/`Unfreeze` usam `id.waydro.Container` sem sudo. Nenhum freeze/unfreeze real foi executado.
- Contrato das camadas documentado em `docs/RUNTIME_MANAGER_CONTRACT.md`; `UI_DESIGN_SPEC.md`, `INDEX.md`, roadmap e matriz de paridade atualizados sem inventar descrições visuais das 128 imagens.
- Suíte ampliada de 208 para **244 testes** com o núcleo do Runtime Manager: cobrem RUNNING+FROZEN, STARTING/STOPPING/UNKNOWN, permissão negada, timeout, serviço inexistente, resposta inválida, operação duplicada, freeze/unfreeze repetidos, cancelamento, recuperação e o contrato oficial do D-Bus.
- Interface integrada ao `RuntimeManager`: `runtime/qt_bridge.py` (ponte Qt com `QThread` e sinais) e `runtime/presentation.py` (tradução para `WaydroidStatus`/`CommandResult`). `WaydroidService` delega `status/start/stop/restart/freeze/unfreeze` ao manager, preservando sinais e callbacks das telas. Nenhuma tela executa comandos Waydroid diretamente para o ciclo de vida.
- Editor de controles sem `1280x720` silencioso: `ControlsScreen` passa a usar a referência documentada `1920×1034@60 Hz, dpi 180` marcada como `REFERÊNCIA / MANUAL` e oferece o botão "Detectar resolução". O novo `services/display_metrics_service.py` executa apenas consultas somente leitura (`wm size`, `wm density`, `dumpsys display`) com runner injetado, sem medição automática em segundo plano; um resultado falho mantém a configuração manual e exibe `NÃO MEDIDA`. `BindingEditor.set_screen()` aceita a origem do valor (`measured`/`user`).
- Verificação de instalação: novos módulos puros `services/apk_signature.py` (extrai a identidade da chave pública dos esquemas v2/v3 e compara SHA-256 entre splits) e `services/installer.py` (planeja a instalação e falha fechada se a assinatura for inconclusiva ou os assinantes divergirem). Splits extraídos e rejeitados são removidos. **Não** é validação criptográfica do arquivo nem substitui o `PackageManager` do Android. APKs assinados apenas com v1 são recusados com mensagem explícita.
- A tela Waydroid usa o planejador antes de instalar APK/XAPK: nenhum split não verificado chega ao `adb install-multiple`. `ProcessRunner` passou a tolerar a liberação do `QProcess` durante o shutdown e a aguardar o término dos processos ao encerrar.
- Biblioteca com metadados locais: `GameEntry` passou a ter `favorite`, `category`, `last_launched_at` e `launch_count`; novo `services/library_metadata.py` implementa busca por nome/package ID, filtros de favoritos/categoria e ordenação por nome/último lançamento/favoritos. `LibraryScreen` ganhou filtros e estrela; `HomeScreen` usa `recent_games()`; `GameCard` mostra o último lançamento. `storage.load_library()` ignora campos desconhecidos de versões antigas. **`last_launched_at` registra o comando de lançamento aceito — não prova abertura do jogo nem lobby.** Nenhuma data é inventada para jogos sem histórico. A estrela usa atualização adiada para não destruir o emissor do sinal durante a recriação dos cards.
- Suíte final desta rodada: **289 testes** — 289 OK no `.venv` (PySide6 6.12.0) e 289 OK no Python do sistema com 18 skips de GUI/bridge/serviço de tela.

## 0.3.1

- Oferece troca para o modo Waydroid de janela única ao iniciar jogos, para manter os apps na mesma superfície Android.
- O jogo é aberto com `waydroid app launch`, sem exigir ADB para a ação de iniciar.
- Editor de controles aprimorado com screenshot de referência do jogo e suporte a layouts em retrato/paisagem.
- Pontos de gesto agora mostram e permitem reposicionar separadamente início e fim.
- Ajustes da mira: alcance, curva, modo de ativação, sensibilidade e eixo vertical.
- Posições de rolagem superior/inferior podem ser ajustadas separadamente.
- Importação de perfis JSON Phantom.
- Validação estrutural básica na importação e slots de macro reutilizáveis.

## 0.3.0

- Biblioteca local e importação de apps instalados via `waydroid app list`.
- Modo de janela única e modo de janelas separadas.
- Instalação de APK e XAPK (splits), atalhos de navegação Android.
- Editor visual de controles e integração opcional com Phantom.

## Limitações conhecidas

- A superfície Android é uma janela Waydroid gerenciada pelo compositor; ela não é embutida como widget Qt dentro do LinuxDroid.
- O mapeamento real de teclado/mouse depende do daemon Phantom, de permissões de entrada e da resolução configurada.
- O repasse USB não traduz automaticamente todo gamepad para toques.
- Macros são sequências simples de toque; macros complexas podem ser refinadas no Phantom GUI ou no JSON.
- A interface foi verificada por compilação Python. O ambiente de build não possui PySide6 e não permite validar a janela graficamente nesta execução.
