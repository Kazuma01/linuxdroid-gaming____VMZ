# LinuxDroid Gaming 0.3.1

Central de jogos Android para Linux, usando o **Waydroid** como ambiente Android. A identidade visual é própria; a experiência de central de jogos e o editor de controles se inspiram em conceitos conhecidos de emuladores, sem copiar marcas ou recursos proprietários.

## Experiência de emulador

O launcher abre os jogos com o comando nativo `waydroid app launch`, então iniciar um jogo não depende de uma conexão ADB ativa. O modo recomendado é **Janela única — apps dentro da superfície Android**. Se a instalação estiver em janelas separadas, ao clicar em **Jogar** o LinuxDroid oferece mudar para janela única e reiniciar a sessão. Depois, abre a tela Android e inicia o jogo dentro dela.

A janela Android continua sendo gerenciada pelo Waydroid e pelo compositor Wayland. Não é uma janela Android incorporada como widget dentro da janela Qt do LinuxDroid. A opção de janelas separadas permanece disponível na Central Android.

## Editor de controles

O editor é por jogo/package ID e oferece:

- Ponto de toque e toque alternado.
- Toque repetido com intervalo configurável.
- D-pad/joystick com teclas direcionais e raio ajustável.
- Mira com botão de ativação, sensibilidade, alcance, curva e inversão vertical.
- Gestos de arrastar com início e fim reposicionáveis no mapa.
- Rolagem com posições de cima e baixo ajustáveis.
- Macros simples e troca de camadas.
- Layouts iniciais para tiro, runner, corrida, jogos casuais e Geometry Dash Lite.
- Importação e exportação de perfis JSON do Phantom.
- Imagem de referência: importe uma captura do jogo para posicionar os pontos diretamente sobre o HUD. As imagens são guardadas localmente por jogo.

O editor usa coordenadas normalizadas de 0 a 1. A resolução do perfil precisa corresponder exatamente à resolução definida no `~/.config/phantom/config.toml` e à superfície Android. A imagem de referência facilita o alinhamento, mas não detecta automaticamente a resolução real do Waydroid. No ambiente de teste atual a superfície foi **medida** em 1920x1034 a 60 Hz (densidade 180), valor que deve ser usado ao criar perfis — não o fallback 1280x720.

### Ambiente Android medido

Nesta máquina o Waydroid 1.6.3 executa Android 13 (LineageOS 20, build `TQ3A.230901.001`) com GPU AMD Radeon RX 580 2048SP. A aceleração dentro do Android foi confirmada por `dumpsys SurfaceFlinger`: `radeonsi/polaris10/ACO`, OpenGL ES 3.2, Mesa 26.0.8, HWC 1.5, 1920x1034@60 Hz. O suporte a ARM64 vem de `libndk_translation.so` 0.2.3. O Free Fire (`com.dts.freefireth`, Unity 2018/IL2CPP `arm64-v8a`) **não está aprovado**: aborta no tradutor antes do lobby. Nenhum backend de entrada é declarado operacional sem teste físico real; veja `docs/V3.md`.

### Mapeamento real

A integração com o **Phantom** é opcional e precisa ser instalada/configurada separadamente. O Phantom captura teclado e mouse no Linux e injeta toques Android. O LinuxDroid consegue validar/carregar perfis, abrir o editor Phantom e alternar captura/mira quando o daemon estiver ativo.

Projeto e instruções oficiais: https://github.com/oliviermugishak/phantom

O daemon exige acesso a `/dev/input/event*` (por permissões/grupo `input` ou pelo procedimento de inicialização privilegiada descrito pelo Phantom). A interface `phantom-gui` e o LinuxDroid devem ser abertos como usuário normal. O launcher **não executa sudo automaticamente**.

Fluxo resumido:

1. Instale o Phantom seguindo a documentação oficial para sua distribuição.
2. Inicie o Waydroid e abra a superfície Android.
3. Configure `[screen]` em `~/.config/phantom/config.toml` para corresponder exatamente à resolução da superfície.
4. Inicie o daemon Phantom de acordo com as instruções oficiais.
5. Crie/importe um perfil no LinuxDroid, ajuste os pontos e clique em **Carregar no Phantom**.
6. Abra o jogo. Quando um perfil válido estiver disponível, o LinuxDroid tenta carregá-lo e ativar a captura após iniciar o app.

Atalhos padrão do Phantom: F8 alterna captura, F1 alterna entre mira e toque de menu e F9 pausa a saída de toques. A disponibilidade pode depender do teclado/Fn Lock e do compositor.

## Gamepad e limites

- O botão de repasse USB pede ao Waydroid para expor dispositivos de entrada ao Android. O reconhecimento depende do hardware, do kernel e do jogo.
- O repasse USB **não** transforma automaticamente botões de qualquer controle em pontos de toque. Mapeamento de controle para toque ainda não é fornecido pelo editor.
- Phantom mapeia teclado e mouse; não injeta giroscópio/acelerômetro e não simula sensores que o jogo exija.
- Compatibilidade com jogos, Google Play, Play Integrity e anti-cheat varia conforme o jogo e a imagem Android.
- XAPK usa `adb install-multiple`; é necessário conectar e autorizar o ADB. Arquivos OBB adicionais ainda podem precisar de cópia manual.

## Requisitos

- Linux com sessão Wayland (recomendado).
- Waydroid instalado e inicializado.
- Python 3.10+ e Git.

No CachyOS/Arch:

```bash
sudo pacman -S --needed python git
cd linuxdroid-gaming
./run.sh
```

O `run.sh` cria `.venv`, instala PySide6 e inicia o launcher. Não execute o LinuxDroid com `sudo`.

## Dados locais

A biblioteca, configurações, perfis e imagens de referência ficam em:

`~/.local/share/linuxdroid-gaming/`

Perfis por package ID: `game_controls.json`  
Perfis versionados V2: `controls_v2/<package>.json`  
Imagens de mapa: `mapping_backgrounds/`  
JSONs preparados para o Phantom: `phantom_profiles/`

## Núcleo de entrada V3

O núcleo V3 está em `linuxdroid/input/` e é independente de Qt. O fluxo é:

`provider → normalizador → MappingEngine → máquina de estados → comandos touch → backend`

### O que já funciona

- `InputEvent` imutável com timestamp monotônico, device ID, namespace, tipo, código/espaço de código explícito, valor, modificadores, origem, flags `pressed/released/repeated`, relativos X/Y, rolagem, foco e proveniência.
- `Normalizer` com aliases e conversão **explícita** de `evdev` para nomes canônicos. Códigos Qt permanecem em `qt_native_scan_code`/`qt_virtual_key` e **nunca** são convertidos em evdev.
- `SimulatedInputProvider` determinístico e `RecordingTouchBackend` como backend padrão de testes. O backend de gravação **não injeta nada**: ele apenas registra comandos em memória.
- `ContactManager` com slots `0..254`, slot `255` reservado, limite Phantom de 10 contatos, IDs estáveis, DOWN antes de MOVE, UP exatamente uma vez, nenhum MOVE após UP e recuperação de contatos após exceção.
- `MappingEngine` para Tap, Toggle Tap, Hold, Joystick, Drag, Aim, Repeat Tap, Wheel e Layer Shift. Macro existe apenas como dado compatível; não há runtime automatizado de macro.
- Cursor virtual reaproveitando `CursorVirtual`, com `virtual_capture_state` e `physical_pointer_capture_state` separados.
- Máquina de estados com `STOPPED`, `STARTING`, `READY`, `PROFILE_LOADING`, `PROFILE_READY`, `CAPTURE_ACTIVE`, `MENU_TOUCH`, `AIM_ACTIVE`, `PAUSED`, `FOCUS_LOST`, `SAFE_RELEASE`, `BACKEND_DISCONNECTED`, `ERROR` e `STOPPING`.
- `SAFE_RELEASE` prioritário e idempotente: libera contatos, botões, teclas, mira, captura e filas, registra o motivo e preserva o estado seguro.
- Editor V2 integrado ao launcher: captura local por códigos Qt, drag-to-bind da lista para o canvas, conflitos, Undo/Redo, duplicar, copiar/colar, excluir, reposicionar, remover/trocar binding e estado “não salvo”.
- Persistência V2 com escrita atômica, backup, quarentena `.corrupt`, validação antes de gravar e migração explícita de V1 sem apagar o arquivo antigo.
- Diagnóstico com modos `simulation`, `recording_backend` e `real_backend`, contadores, motivos de SAFE_RELEASE e tempos por estágio. Nunca registra texto digitado e nunca afirma que houve injeção quando houve apenas gravação em memória.

### Proveniência

Toda identidade de entrada é classificada como uma destas:

| Valor | Significado |
| --- | --- |
| `validated_by_vocabulary` | nome reconhecido pelo vocabulário canônico; **não** é captura física |
| `captured_from_device` | captura real declarada por backend com evidência |
| `validated_by_backend` | identidade validada por backend, sem afirmar captura global |
| `unverified` | texto/código sem origem comprovada |

`ControlProfileV2` continua sendo o único modelo versionado. `BindingEditor`, conversões e persistência usam esse modelo; o payload V1 do canvas é apenas uma visão de compatibilidade.

### Backend real

`native` continua sendo apenas candidato. Nenhum backend real é funcional sem teste físico explicitamente autorizado. `PhantomAdapter` valida/perfila/consulta status somente com runner injetado; não inicia daemon, não executa comandos arbitrários e marca `functional=False`, `tested=False` e `operational=False` até evidência real.

### Testes

```bash
PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v
```

A suíte cobre eventos, normalização, proveniência, provider simulado, backend de gravação, motor, multitouch, SAFE_RELEASE, cursor, máquina de estados, editor, storage, capacidades e diagnóstico. Dois testes de integração da GUI exigem PySide6 e são ignorados no Python do sistema. Quando um `.venv` com PySide6 estiver disponível (`run.sh` pode criá-lo), execute `QT_QPA_PLATFORM=offscreen .venv/bin/python -B -m unittest discover -s tests -v`. Nesta árvore o `.venv` ainda não foi criado. Não usa pytest, não inicializa o launcher e não toca hardware.
