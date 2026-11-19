# Histórico de versões

## Não lançado

- Configurações → Desempenho: checagem de requisitos do sistema (sessão Wayland, Waydroid instalado, binder no kernel, GPU, RAM, CPU e acesso a /dev/input). Somente leitura, com dicas de correção.
- Testes unitários da checagem em `tests/` (`python -m unittest tests.test_system_check -v`).

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
