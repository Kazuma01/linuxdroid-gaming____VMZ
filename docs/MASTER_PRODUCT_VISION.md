# LinuxDroid Gaming — Visão Mestra do Produto

**Versão do documento:** 1.0  
**Data:** 19/11/2026  
**Status:** documento vivo — atualizado conforme a implementação avança.  
**Base Git:** `a4c06ace01385aa4d2266e94d5f6834c9d286b47` (`VMZ`)

---

## 1. O que estamos construindo

O LinuxDroid Gaming é um **emulador Android Gaming para Linux**, não um launcher de Waydroid, não um editor de teclas e não uma interface para comandos de terminal.

O objetivo é alcançar a maior paridade funcional possível com o BlueStacks 5, usando tecnologias próprias, adaptadas a Linux, Wayland, AMD, Intel e outras plataformas compatíveis. O usuário deve conseguir **instalar, abrir, configurar, controlar, organizar e jogar** aplicativos Android por meio de uma única aplicação desktop, sem precisar entender LXC, Binder, ADB, Native Bridge, propriedades Android, systemd ou comandos Linux.

**Nome de trabalho:** LinuxDroid Gaming.  
**Identidade:** própria, independente, modular e extensível. Não copiamos marca, logos, recursos visuais protegidos nem código proprietário de terceiros.

O **Free Fire é o primeiro jogo de validação**, não o limite do produto.

---

## 2. Princípios não negociáveis

1. **Honestidade de estado.** Nada é marcado como "implementado", "operacional", "testado" ou "compatível" sem evidência mensurável. Backend simulado nunca é reportado como injeção real. Uma janela aberta não prova estabilidade. Uma ABI anunciada não prova que a tradução funciona.
2. **Preservação.** Não recomeçar instalações, não apagar dados Android, contas Google, progresso de jogos, imagens, perfis, backups ou histórico Git. Nenhum `git reset --hard`, `git clean -fd` ou `rm -rf` em diretórios do Waydroid.
3. **Uma mudança por experimento.** Toda alteração de sistema, container, Native Bridge, propriedade Android, driver, kernel ou permissão exige evidência, risco, backup, reversão e autorização específica.
4. **Menor privilégio.** A interface nunca roda como root. Não adicionar usuário a grupo `input` automaticamente, não criar regras udev genéricas, não dar acesso irrestrito a `/dev/input` ou `/dev/uinput`, não desativar SELinux/AppArmor/firewall.
5. **Sem evasão.** Não implementar spoofing, root para jogos, ocultação de ferramentas, bypass de Play Integrity, Anti-Cheat ou verificações de integridade. Macros nunca devem virar bots, auto-farm ou mira automática em jogos protegidos.
6. **Portabilidade.** Não fixar `/dev/dri/renderD128`, caminhos de Python, resolução, GPU específica ou compositor. Detectar recursos em tempo de execução e expor limitações.
7. **Testabilidade.** Cada módulo com testes próprios. Testes simulados separados de testes reais, com critérios mensuráveis.
8. **Dados versionados.** Esquemas versionados, migrações testadas, checksums, rollback e relatórios sanitizados. Nenhuma informação sensível em logs.

---

## 3. Arquitetura alvo (6 camadas)

| Camada | Responsabilidade | Estado atual resumido |
|---|---|---|
| **1. Interface desktop** | Home, biblioteca, instâncias, controles, configurações, desempenho, diagnóstico, arquivos, atualizações, capturas, gravações, ajuda | PySide6 existente; ampliar com navegação consistente, barra lateral e painéis |
| **2. Android Runtime Manager** | Waydroid, ciclo de vida, sessão, estado, instalação, ADB, integração desktop, configurações Android, recuperação | Parcial: há serviço Waydroid e parser de estado com `FROZEN`; falta abstração de runtime |
| **3. Instance Manager** | Criar, iniciar, parar, clonar, renomear, configurar, snapshot, backup, restaurar, excluir com confirmação, validar integridade | **NÃO IMPLEMENTADO** como camada; multi-instância real ainda precisa prova de isolamento |
| **4. Input Engine** | Teclado, mouse, gamepad, normalização, captura, mapeamento, coordenadas, multitouch, joystick, mira, cursor virtual, SAFE_RELEASE, perfis | V3 existente com bindings e SAFE_RELEASE; captura/injeção real ainda não validada |
| **5. Graphics and Performance Engine** | GPU, FPS, frametime, CPU, memória, temperatura, sincronização, diagnósticos | Diagnóstico de capabilities existe; medição contínua de FPS/frametime não implementada |
| **6. Data and Recovery** | Perfis, preferências, instâncias, backups, snapshots, logs, checksums, migrações, rollback, histórico | Storage atômico e perfis versionados existem; backup/restore de instâncias não existe |

O Runtime Manager deve ser desacoplado da interface e expor uma **interface abstrata** para estudar outros runtimes no futuro. Waydroid permanece o primeiro runtime; substituí-lo exige planejamento e provas técnicas.

---

## 4. Experiência alvo do usuário

Ao abrir o LinuxDroid Gaming, o usuário encontra uma central completa e pode:

1. Abrir o Android.
2. Acessar a biblioteca de jogos.
3. Instalar aplicativos.
4. Abrir jogos com um clique.
5. Configurar controles.
6. Criar perfis.
7. Ajustar resolução.
8. Configurar desempenho.
9. Gerenciar instâncias.
10. Gravar e capturar a tela.
11. Organizar aplicativos.
12. Gerenciar arquivos.
13. Consultar diagnósticos.
14. Fazer backups.
15. Recuperar ambientes anteriores.
16. Encerrar e reiniciar o Android.

Durante o jogo, uma **barra lateral de ferramentas** oferece acesso rápido: screenshot, gravação, pasta de mídia, volume, teclado, gamepad, configurações, tela cheia, bloquear/liberar mouse, controles do jogo, gerenciador de macros, monitor de desempenho, reiniciar aplicativo, Home do Android e ADB Debug (protegido e opcional).

Atalhos globais e por jogo devem respeitar os limites do compositor Wayland. **Não presumir que `QWidget.grabMouse()` controla o ponteiro global em outra janela.**

---

## 5. Mapa de funcionalidades (resumo)

O inventário detalhado com STATUS, viabilidade, dependências, riscos, testes, prioridade e etapa está em `BLUESTACKS_FEATURE_PARITY.md`.

Áreas cobertas pela visão:

- **Biblioteca:** grade/lista, pesquisa, favoritos, categorias, ícones, capas, última execução, estado instalado/em execução, abrir/fechar/desinstalar/atualizar/importar/exportar perfil. Detecção por mecanismos confiáveis, nunca lista fixa de nomes.
- **Instalação:** APK, XAPK, APKS, splits, múltiplas arquiteturas. Validação de pacote, assinatura e integridade; streaming sem carregar arquivos enormes em memória; limites de tamanho e proteção contra ZIP malformado.
- **Controles:** editor visual com captura real da tela Android, geometria na resolução real (1920x1034 nesta máquina), coordenadas normalizadas, `ScreenContract`, WASD, joystick, D-pad, tap/hold/toggle, swipe/drag, mira, scroll, multitouch, layer shift, SAFE_RELEASE idempotente.
- **Gamepad:** evdev, USB/Bluetooth, botões/gatilhos/analógicos, calibração, dead zone, sensibilidade, vibração quando disponível, perfil por jogo, capacidades reais do dispositivo.
- **Macros:** gravação/reprodução legítima com nomes, atalhos, edição, intervalos, histórico e controles de segurança. Desativadas por padrão em jogos competitivos protegidos.
- **Multi-instância:** criar/clonar/iniciar/pausar/retomar/encerrar/renomear/excluir/configurar/backup/restaurar, com ID, nome, versão Android, ABI, perfil de hardware, resolução, DPI, CPU, memória, GPU, diretório de dados, estado, histórico e data de criação. **Execução simultânea só será considerada implementada após comprovar isolamento de rede, processos, armazenamento, Binder e dispositivo gráfico.**
- **Eco Mode:** reduzir atividade em segundo plano, priorizar instância em foco, exibir RAM/GPU/temperatura/armazenamento. Nenhum limite global automático sem medição antes/depois.
- **Gráficos:** perfis equilibrado/desempenho/econômico, CPU, memória, resolução, DPI, orientação, FPS configured vs. FPS efetivo, VSync, renderização, OpenGL ES/Vulkan/Mesa. Diferençar medição de estimativa. Nunca modificar arquivos internos do jogo para desbloquear FPS.
- **Ferramentas:** screenshot, gravação, mídia, teclado/gamepad, performance, atalhos, barra lateral, ADB debug opcional.
- **Integração Linux:** clipboard, compartilhamento de arquivos, imagens, downloads, notificações, áudio, microfone, links — sempre com permissões explícitas.
- **Perfis de dispositivo:** apenas configurações legítimas e documentadas. Sem falsificar identidade para Play Store ou proteções.

---

## 6. Roadmap

| Etapa | Nome | Entrega |
|---|---|---|
| **P0** | Estabilização do Android | Concluir investigação do Native Bridge; testar modo leve **se autorizado**; resolver ou delimitar o crash do Free Fire; validar sessão, GPU e ADB; preservar backups |
| **P1** | Núcleo do emulador | Runtime manager, estado Android, gestão de processos, launcher, biblioteca, instalação, configurações, diagnóstico, backup/restore |
| **P2** | Controles reais | Captura e injeção, joystick, WASD, mira, mouse, teclado, gamepad, SAFE_RELEASE — começar em app Android de demonstração |
| **P3** | Editor e perfis | Canvas, drag-and-drop, bindings, perfis por jogo, import/export, sensibilidade, camadas, histórico |
| **P4** | Experiência avançada | Barra lateral, atalhos, screenshot, gravação, clipboard, mídia, configuração de tela, monitor de desempenho, Macro Recorder permitido |
| **P5** | Instâncias | Isolamento real, criação, clone, backup, restauração, configuração independente, gestão de recursos |
| **P6** | Compatibilidade | AMD, Intel, NVIDIA (com limitações), Wayland, X11, ARM64, ARM32, versões Android |
| **P7** | Acabamento | UX, documentação, instalador, atualizações, logs, diagnóstico, relatórios, empacotamento |

---

## 7. Estado atual do P0 — Free Fire (prioridade imediata)

**Não autorizado a alterar.** Experimento preparado, não aplicado.

- Pacote `com.dts.freefireth`, Android 13/SDK 33, Waydroid 1.6.3, host AMD RX 580 2048SP.
- Três reproduções idênticas: `Guest call didn't restore sp`, `SIGABRT`, delta `0x10`, BuildId `619f1b989579361ca8a7a25027432444`, `libndk_translation.so` 0.2.3.
- Autenticação Google Play Games passa; Unity 2018/IL2CPP ARM64 inicializa; **lobby não é alcançado**.
- Aceleração GLES dentro do Android comprovada por medição (Mesa 26.0.8, `radeonsi/polaris10/ACO`, HWC 1.5, 1920x1034@60 Hz).
- Análise local provou que `ndk_translation.mode` existe no binário; valores aceitos incluem `light-translate-or-interpret`; padrão identificado é `two-gear`.
- Mudança proposta: `ndk_translation.mode=light-translate-or-interpret`. Confiança **baixa a média** para este abort. Requer autorização específica.
- Documentação: `../diagnostico_freefire_2026-11-19/experimento_native_bridge_v2/RELATORIO.md` (fora do repositório).

**Regras durante o experimento:** mudar somente a propriedade; reiniciar sessão de forma controlada; confirmar carregamento desde o boot; coletar logcat; abrir o jogo uma vez; não entrar em partida sem nova autorização; rollback se o crash repetir; não instalar libndk-fixer nem libhoudini; não misturar com alterações de GPU.

---

## 8. Critério definitivo de sucesso

O produto estará pronto quando o usuário conseguir, sem comandos manuais no cotidiano:

1. Abrir o LinuxDroid Gaming.
2. Visualizar seus jogos.
3. Instalar um novo aplicativo.
4. Criar e organizar instâncias.
5. Abrir um jogo com um clique.
6. Usar teclado e mouse como no BlueStacks.
7. Personalizar controles visualmente.
8. Usar modo de tiro e cursor travado.
9. Utilizar gamepad.
10. Ajustar resolução e gráficos.
11. Medir FPS e desempenho.
12. Gravar e capturar a tela.
13. Fazer backups e restaurar instâncias.
14. Utilizar ferramentas laterais.
15. Administrar várias instâncias **quando o isolamento estiver comprovado**.
16. Usar Android sem depender de terminal.

---

## 9. Documentos relacionados

- `BLUESTACKS_FEATURE_PARITY.md` — matriz recurso a recurso com estado, viabilidade e prioridade.
- `ARCHITECTURE_ROADMAP.md` — mapa módulo ↔ funcionalidade e sequência de implementação.
- `UI_DESIGN_SPEC.md` — especificação da interface própria, baseada em referências visuais oficiais.
- `references/bluestacks/INDEX.md` — índice das referências visuais com atribuição e URLs originais.
- `references/bluestacks/ANALISE_FUNCIONAL.md` — fluxos extraídos da documentação oficial.
- `V3.md` — detalhes do Input Engine V3 e limitações atuais.
