# Log de download — referências oficiais BlueStacks 5

Data da coleta: 2026-11-19. Método: `curl`/`urllib` com User-Agent de navegador (`Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36`) e cabeçalho `Referer` apontando para a página de origem. Nenhum pacote foi instalado; nenhum arquivo fora de `docs/references/bluestacks/` foi modificado.

## Resultado

- **131 referências de imagem extraídas** das 8 páginas (através de `img src`, `data-src` e `og:image`).
- **128 imagens únicas baixadas** e preservadas **byte a byte** (formato e proporção originais, sem conversão ou redimensionamento).
- **3 referências duplicadas** por SHA-256: apenas uma cópia física de cada foi mantida (detalhes abaixo).
- **0 falhas finais de download.**
- **0 capturas de página com navegador**: todas as páginas possuíam imagens diretas; nenhuma captura foi necessária ou alegada.
- Logos, ícones de marca e redes sociais da página de funcionalidades (`logo-icon.png`, `logo-text.png`, `bs_logo2.png`, `twitter-social-logo.png`) foram **deliberadamente não baixados**, conforme a regra de não copiar logos do produto. Ícones de ferramentas da interface e artes de recurso foram baixados **apenas como referência de análise**, nunca para incorporação no produto.

## Contagem por página

| Página oficial | Referências extraídas | Cópia única mantida |
|---|---:|---:|
| https://support.bluestacks.com/hc/pt-br/articles/360058928871-Como-criar-e-editar-controles-no-BlueStacks-5 | 40 | 40 |
| https://support.bluestacks.com/hc/pt-br/articles/360052834092-Como-criar-e-gerenciar-inst%C3%A2ncias-usando-o-Gerenciador-de-Multi-Inst%C3%A2ncia-no-BlueStacks-5 | 8 | 8 |
| https://support.bluestacks.com/hc/pt-br/articles/360053245871-Como-usar-o-menu-Configura%C3%A7%C3%B5es-do-BlueStacks-5 | 14 | 14 |
| https://support.bluestacks.com/hc/pt-br/articles/360052834772-Como-executar-v%C3%A1rias-inst%C3%A2ncias-do-BlueStacks-5-com-mais-efici%C3%AAncia-usando-o-Modo-Eco | 6 | 4 |
| https://support.bluestacks.com/hc/en-us/articles/360055672212-How-to-use-the-Side-toolbar-in-BlueStacks-5 | 24 | 24 |
| https://support.bluestacks.com/hc/en-us/articles/360055522292-How-to-use-the-Game-controls-menu-on-BlueStacks-5 | 3 | 3 |
| https://support.bluestacks.com/hc/en-us/articles/4422291276429-How-to-change-settings-in-the-Multi-instance-Manager-on-BlueStacks-5 | 8 | 8 |
| https://www.bluestacks.com/pt-br/features.html | 28 | 27 |
| **Total** | **131** | **128** |

## Deduplicação (SHA-256)

| URL repetida | Cópia mantida | SHA-256 (prefixo) | Motivo |
|---|---|---|---|
| https://support.bluestacks.com/hc/article_attachments/29500698516749 | `eco-mode/eco_barra_lateral.jpg` | `6e68eb4c64e04299` | Mesma URL citada duas vezes no artigo do Modo Eco. |
| https://support.bluestacks.com/hc/article_attachments/29500698518925 | `eco-mode/eco_controle_deslizante.jpg` | `b43cf7798a09f671` | Mesma URL citada duas vezes no artigo do Modo Eco. |
| https://cdn-www.bluestacks.com/bs-images/Feature_Index_01-Game.jpg | `controls-editor/recursos_controles_exemplo.jpg` | `03d43d09559ef230` | URL diferente (`Feature_Index_Game_control_1.jpg`), porém bytes idênticos no CDN. |

## Ocorrências transitórias (resolvidas)

- A primeira validação do downloader rejeitou 3 respostas por serem menores que 512 bytes:
  - `https://support.bluestacks.com/hc/article_attachments/29500943755789` (PNG válido de 505 bytes, 128×128);
  - `https://cdn-www.bluestacks.com/bs-images/controls_blue1.png` (PNG válido de 368 bytes, 130×128);
  - `https://cdn-www.bluestacks.com/bs-images/instance-manager_blue1.png` (PNG válido de 294 bytes, 130×128).
  Todas foram confirmadas como imagens reais via `file`/ImageMagick e baixadas no retry. Nenhuma falha permanece.
- Duplicatas físicas geradas por execuções interrompidas do script foram removidas; cada hash possui exatamente um arquivo em disco.

## Inspeção visual

**Nenhuma imagem foi aberta visualmente.** A ferramenta de leitura de imagens deste modelo reportou: "this model does not support image input". Consequentemente:

- nenhuma descrição visual foi inventada;
- todas as 128 linhas do `INDEX.md` usam o texto exato `NÃO INSPECIONADA VISUALMENTE — apenas URL registrada`;
- a análise funcional (`ANALISE_FUNCIONAL.md`) baseia-se apenas no texto oficial das páginas;
- a correspondência entre ícones da barra lateral e funções foi inferida da ordem/alt das imagens no HTML e está marcada como DÚVIDA quando aplicável.

## Arquivos temporários

Os scripts auxiliares de scraping/download e o cache JSON das páginas foram removidos ao final. Os únicos arquivos entregues são: `INDEX.md`, `ANALISE_FUNCIONAL.md`, `DOWNLOAD_LOG.md`, as 12 pastas temáticas e as 128 imagens nelas contidas.
