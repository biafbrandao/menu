# Cardápio em PDF

`gerar_pdf.py` lê as páginas `.md` do site (na ordem do menu de navegação do
`_layouts/default.html`), monta um HTML paginado e imprime em PDF com o Chromium.
O Jekyll ignora pastas que começam com `_`, então nada aqui vai para o site.

## Instalar (uma vez)

```bash
conda activate geo
conda install -c conda-forge playwright markdown beautifulsoup4 pypdf
playwright install chromium
```

## Gerar

Na raiz do repositório:

```bash
conda activate geo
python _pdf/gerar_pdf.py                 # A4 -> menu.pdf
python _pdf/gerar_pdf.py --papel A5      # A5 -> menu.pdf
python _pdf/gerar_pdf.py -o cardapio-a5.pdf --papel A5
python _pdf/gerar_pdf.py --html          # guarda também menu.html para inspecionar o layout
python _pdf/gerar_pdf.py --navegador "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

Se o `menu.pdf` for commitado na raiz, ele fica acessível em
`https://biafbrandao.github.io/menu/menu.pdf`.

## O que o script faz com o conteúdo

- Capa: logo e a primeira foto da página inicial, a descrição do `_config.yml` e os contatos
  (extraídos dos links de WhatsApp e Instagram do `index.md`).
- Página "Olá" com o texto e o retrato; sumário com números de página
  (calculados numa primeira passagem; sem `pypdf` o sumário sai sem números).
- Cada página do menu vira um capítulo que abre em página nova, com o nome no cabeçalho.
- Seção `##` que começa com até duas fotos seguidas de texto vira um item com fotos ao lado
  do texto (alternando os lados); demais seções ficam em fluxo com as fotos em faixa.
- Parágrafos que começam com **R$** ganham estilo de preço; os botões de WhatsApp viram um
  quadro com o telefone.
- Cores vêm do `:root` do `style.css`; fontes (Fraunces e DM Sans, licença OFL) estão em `fontes/`.

## Ajustes

Tamanhos de foto, margens e corpo de texto por formato ficam no dicionário `PAPEIS` do script;
o restante da aparência, em `impressao.css`.
