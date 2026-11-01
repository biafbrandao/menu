#!/usr/bin/env python3
"""
Gera o cardápio em PDF para impressão a partir das páginas Markdown do site.

Lê os .md do repositório na ordem do menu de navegação (_layouts/default.html),
monta um único HTML paginado (capa, apresentação, sumário, capítulos) e o
imprime em PDF com o Chromium via Playwright, em duas passagens: a primeira
descobre em que página começa cada capítulo, a segunda preenche o sumário.

Uso (da raiz do repositório):
    python _pdf/gerar_pdf.py                  # A4 -> menu.pdf
    python _pdf/gerar_pdf.py --papel A5       # livreto A5
    python _pdf/gerar_pdf.py -o cardapio.pdf --html   # guarda também o HTML montado
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

import markdown
from bs4 import BeautifulSoup, NavigableString, Tag

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent

PAPEIS = {
    # largura, altura, margens (topo lado base), corpo, foto ao lado do texto,
    # galeria em linha, imagem única, respiro da capa
    "A4": dict(w="210mm", h="297mm", margem="20mm 17mm 20mm", corpo="10pt",
               foto_h="60mm", galeria_h="70mm", galeria_h1="88mm",
               capa_pad="9mm", capa_moldura_pad="16mm 18mm 14mm"),
    "A5": dict(w="148mm", h="210mm", margem="15mm 12mm 16mm", corpo="8.6pt",
               foto_h="40mm", galeria_h="46mm", galeria_h1="80mm",
               capa_pad="6mm", capa_moldura_pad="10mm 11mm 9mm"),
}


# ---------------------------------------------------------------- leitura

def ler_pagina(caminho: Path) -> tuple[dict, str]:
    """Separa front matter YAML simples (chave: valor) do corpo Markdown."""
    texto = caminho.read_text(encoding="utf-8")
    meta = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", texto, re.S)
    if m:
        for linha in m.group(1).splitlines():
            if ":" in linha:
                k, v = linha.split(":", 1)
                meta[k.strip()] = v.strip().strip('"\'')
        texto = texto[m.end():]
    texto = re.sub(r"^[ \t]*<!--.*?-->[ \t]*\n", "", texto, flags=re.S | re.M)   # linha só de comentário
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.S)
    return meta, texto


def ler_config() -> dict:
    cfg = {}
    arq = RAIZ / "_config.yml"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if ":" in linha and not linha.startswith(" "):
                k, v = linha.split(":", 1)
                cfg[k.strip()] = v.strip().strip('"\'')
    return cfg


def ordem_do_menu() -> list[Path]:
    """Páginas na ordem dos links do <nav> do layout; a página inicial fica de fora."""
    layout = (RAIZ / "_layouts" / "default.html").read_text(encoding="utf-8")
    nav = re.search(r"<nav>(.*?)</nav>", layout, re.S)
    slugs = re.findall(r"\{\{\s*'/([^']*)'\s*\|\s*relative_url\s*\}\}", nav.group(1) if nav else "")
    paginas = [RAIZ / f"{s}.md" for s in slugs if s]
    faltando = [p.name for p in paginas if not p.exists()]
    if faltando:
        sys.exit(f"Páginas do menu sem arquivo .md: {', '.join(faltando)}")
    return paginas


def cores_do_site() -> str:
    """Reaproveita o bloco :root do style.css para manter a paleta do site."""
    css = (RAIZ / "style.css").read_text(encoding="utf-8")
    m = re.search(r":root\s*\{(.*?)\}", css, re.S)
    return m.group(1).strip() if m else ""


def contatos(md_inicio: str) -> dict:
    zap = re.search(r"wa\.me/(\d+)", md_inicio)
    insta = re.search(r"instagram\.com/([\w.]+)", md_inicio)
    c = {}
    if zap:
        n = zap.group(1)
        local = n[2:] if n.startswith("55") else n          # tira o DDI do Brasil
        c["zap_link"] = f"https://wa.me/{n}"
        c["zap"] = f"({local[:2]}) {local[2:-4]}-{local[-4:]}"
    if insta:
        c["insta_link"] = f"https://www.instagram.com/{insta.group(1)}/"
        c["insta"] = "@" + insta.group(1)
    return c


# ---------------------------------------------------------------- transformação

def md_para_soup(texto: str) -> BeautifulSoup:
    html = markdown.markdown(texto, extensions=["extra", "sane_lists"])
    return BeautifulSoup(html, "html.parser")


def filhos(tag) -> list[Tag]:
    return [c for c in tag.children if isinstance(c, Tag)]


def so_imagens(p: Tag) -> bool:
    """Parágrafo composto apenas de <img> (linhas de imagem consecutivas no .md)."""
    if p.name != "p":
        return False
    tem_img = False
    for c in p.children:
        if isinstance(c, NavigableString):
            if c.strip():
                return False
        elif c.name == "img":
            tem_img = True
        else:
            return False
    return tem_img


def normalizar(soup: BeautifulSoup, ctx: dict) -> None:
    """Galerias, preços e chamadas de pedido."""
    for p in soup.find_all("p"):
        if so_imagens(p):
            imgs = p.find_all("img")
            p.name = "div"
            p["class"] = ["galeria", f"n{len(imgs)}"]
            for i in imgs:
                i.attrs.pop("title", None)
                i["loading"] = "eager"
        else:
            primeiro = next((c for c in p.children if not (isinstance(c, NavigableString) and not c.strip())), None)
            if isinstance(primeiro, Tag) and primeiro.name == "strong" and "R$" in primeiro.get_text():
                p["class"] = p.get("class", []) + ["preco"]

    # galerias vizinhas (separadas só por linha em branco) viram uma só
    for g in soup.select("div.galeria"):
        if g.parent is None:
            continue
        viz = g.find_next_sibling()
        while viz is not None and "galeria" in viz.get("class", []):
            for img in viz.find_all("img"):
                g.append(img.extract())
            prox = viz.find_next_sibling()
            viz.decompose()
            viz = prox
        g["class"] = ["galeria", f"n{len(g.find_all('img'))}"]

    for a in soup.select("a.whats"):
        rotulo = a.get_text(strip=True)
        caixa = soup.new_tag("div", attrs={"class": "pedido"})
        link = soup.new_tag("a", href=a.get("href", ctx.get("zap_link", "")))
        s1 = soup.new_tag("span", attrs={"class": "rotulo"}); s1.string = rotulo
        link.append(s1)
        if ctx.get("zap"):
            s2 = soup.new_tag("span", attrs={"class": "fone"}); s2.string = f"WhatsApp {ctx['zap']}"
            link.append(s2)
        caixa.append(link)
        # o markdown pode ter envolvido o <a> num <p>
        alvo = a.parent if a.parent.name == "p" and len(filhos(a.parent)) == 1 else a
        alvo.replace_with(caixa)


def secionar(soup: BeautifulSoup, n_cap: int, contador_item: list[int]) -> tuple[str, list[Tag]]:
    """Agrupa o fluxo em seções por título; o primeiro h1 é o título do capítulo."""
    titulo, secoes, atual = None, [], None

    def nova(classe, cabeca=None):
        s = soup.new_tag("section", attrs={"class": classe})
        if cabeca is not None:
            s.append(cabeca)
        secoes.append(s)
        return s

    for el in filhos(soup):
        el.extract()
        if el.name == "h1" and titulo is None:
            titulo = el.get_text(strip=True)
            continue
        if el.name == "h1":                       # h1 secundário vira seção maior
            el.name = "h2"
            atual = nova("bloco secao-maior", el)
        elif el.name == "h2":
            atual = nova("bloco", el)
        else:
            if atual is None:
                atual = nova("bloco")
            atual.append(el)

    for s in secoes:
        conteudo = filhos(s)
        cabeca = conteudo[0] if conteudo and conteudo[0].name == "h2" else None
        resto = conteudo[1:] if cabeca else conteudo
        if not resto:
            continue
        gal = resto[0]
        outras = resto[1:]
        pode_lado_a_lado = (
            cabeca is not None
            and "galeria" in gal.get("class", [])
            and len(gal.find_all("img")) <= 2
            and outras
            and not any(o.name == "table" or "galeria" in o.get("class", []) for o in outras)
            and "secao-maior" not in s.get("class", [])
        )
        if pode_lado_a_lado:
            contador_item[0] += 1
            classes = ["item"] + (["invertido"] if contador_item[0] % 2 == 0 else [])
            s["class"] = classes
            fotos = soup.new_tag("div", attrs={"class": "fotos"})
            for img in gal.find_all("img"):
                fotos.append(img.extract())
            gal.decompose()
            texto = soup.new_tag("div", attrs={"class": "texto"})
            texto.append(cabeca.extract())
            for o in outras:
                texto.append(o.extract())
            s.append(fotos)
            s.append(texto)
        elif cabeca is not None:
            # título preso ao primeiro bloco de conteúdo: impede título órfão no pé da página
            junto = soup.new_tag("div", attrs={"class": "junto"})
            cabeca.insert_before(junto)
            junto.append(cabeca.extract())
            junto.append(gal.extract())
    return titulo, secoes


# ---------------------------------------------------------------- montagem

def montar_html(papel: str, paginas_sumario: dict[int, int] | None, marcar: bool) -> tuple[str, list[str]]:
    cfg = ler_config()
    meta_ini, md_ini = ler_pagina(RAIZ / "index.md")
    ctx = contatos(md_ini)
    P = PAPEIS[papel]

    # ----- página inicial: logo, fotos e texto de apresentação
    sini = md_para_soup(md_ini)
    imgs_ini = [i for i in sini.find_all("img") if "contatos" not in " ".join(
        sum((p.get("class", []) for p in i.parents if isinstance(p, Tag)), []))]
    logo = imgs_ini[0]["src"] if imgs_ini else "img/logo_v.png"
    fotos_ola = [i["src"] for i in imgs_ini[1:]]
    foto_capa = fotos_ola.pop(0) if fotos_ola else None
    h1_ola = sini.find("h1")
    titulo_ola = h1_ola.get_text(strip=True) if h1_ola else "Olá"
    paragrafos_ola = []
    if h1_ola:
        for el in h1_ola.find_all_next(["p"]):
            if not el.find("img") and el.get_text(strip=True):
                paragrafos_ola.append(str(el))

    # ----- capítulos
    capitulos, contador = [], [0]
    for n, caminho in enumerate(ordem_do_menu(), start=1):
        meta, texto = ler_pagina(caminho)
        soup = md_para_soup(texto)
        normalizar(soup, ctx)
        titulo, secoes = secionar(soup, n, contador)
        titulo = titulo or meta.get("title", caminho.stem)
        capitulos.append((n, titulo, secoes))

    nomes = [BeautifulSoup(t, "html.parser").get_text() for _, t, _ in capitulos]

    # ----- CSS
    css = (AQUI / "impressao.css").read_text(encoding="utf-8")
    marca = cfg.get("title", "")
    rodape = "  ·  ".join(x for x in (f"WhatsApp {ctx.get('zap','')}" if ctx.get("zap") else "", ctx.get("insta", "")) if x)
    css = (css.replace("__PAPEL__", f"{P['w']} {P['h']}")
              .replace("__MARGEM__", P["margem"])
              .replace("__MARCA__", marca.replace('"', '\\"'))
              .replace("__CONTATO__", rodape.replace('"', '\\"')))
    topo, lado, base = (P["margem"].split() + [None, None])[:3]
    variaveis = f"""
:root {{
  {cores_do_site()}
  --papel-w: {P['w']}; --papel-h: {P['h']};
  --margem-topo: {topo}; --margem-lado: {lado}; --margem-base: {base};
  --corpo: {P['corpo']}; --foto-h: {P['foto_h']};
  --galeria-h: {P['galeria_h']}; --galeria-h1: {P['galeria_h1']};
  --capa-pad: {P['capa_pad']}; --capa-moldura-pad: {P['capa_moldura_pad']};
}}"""
    cabecalhos = "\n".join(
        f'@page cap-{n} {{ @top-right {{ content: "{nome.replace(chr(34), "")}"; font-family: "Fraunces", Georgia, serif; '
        f'font-size: 8pt; color: var(--rosa-escuro, #a76678); vertical-align: bottom; padding-bottom: 3mm; }} }}\n'
        f'#cap-{n} {{ page: cap-{n}; }}'
        for (n, _, _), nome in zip(capitulos, nomes)
    )

    # ----- corpo
    contatos_html = []
    if ctx.get("insta"):
        contatos_html.append(f'<a href="{ctx["insta_link"]}">Instagram {ctx["insta"]}</a>')
    if ctx.get("zap"):
        contatos_html.append(f'<a href="{ctx["zap_link"]}">WhatsApp {ctx["zap"]}</a>')
    sep = '<span class="sep">◆</span>'
    rod = re.search(r"<footer>(.*?)</footer>", (RAIZ / "_layouts" / "default.html").read_text(encoding="utf-8"), re.S)
    frase = rod.group(1).strip() if rod else ""

    partes = [f"""
<div class="capa"><div class="capa-moldura">
  <img class="logo" src="{logo}" alt="{marca}">
  {f'<img class="foto-capa" src="{foto_capa}" alt="">' if foto_capa else ''}
  <div>
    <p class="descricao">{cfg.get('description', '')}</p>
    <p class="contatos">{sep.join(contatos_html)}</p>
  </div>
</div></div>

<div class="ola">
  {''.join(f'<div class="retrato"><img src="{f}" alt=""></div>' for f in fotos_ola[:1])}
  <div class="texto">
    <h1>{titulo_ola}</h1><span class="ornamento" style="margin-left:0;margin-bottom:6mm"></span>
    {''.join(paragrafos_ola)}
  </div>
</div>

<nav class="sumario">
  <h1>Sumário</h1><span class="ornamento"></span>
  <ol>
    {''.join(
        f'<li><a href="#cap-{n}">{t}</a><span class="pontos"></span>'
        f'<span class="pag">{(paginas_sumario or {}).get(n, "")}</span></li>'
        for n, t, _ in capitulos)}
  </ol>
</nav>
"""]
    for n, titulo, secoes in capitulos:
        marcador = f'<span class="marca">@@CAP{n}@@</span>' if marcar else ""
        partes.append(
            f'<article class="capitulo" id="cap-{n}">{marcador}'
            f'<header><h1>{titulo}</h1><span class="ornamento"></span></header>'
            + "".join(str(s) for s in secoes)
            + (f'<p class="frase-final">{frase}</p>' if frase and n == len(capitulos) else "")
            + "</article>"
        )

    html = f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">
<title>{marca} · Cardápio</title>
<base href="{RAIZ.as_uri()}/">
<style>{variaveis}
{css}
{cabecalhos}</style>
</head><body class="papel-{papel}">
{''.join(partes)}
</body></html>"""
    return html, nomes


# ---------------------------------------------------------------- impressão

def abrir_navegador(pw, caminho: str | None):
    if caminho:
        return pw.chromium.launch(executable_path=caminho)
    try:
        return pw.chromium.launch()
    except Exception:
        try:
            return pw.chromium.launch(channel="chrome")       # Chrome instalado no sistema
        except Exception as e:
            sys.exit("Não encontrei um Chromium. Rode uma vez:  playwright install chromium\n"
                     f"(ou passe --navegador /caminho/do/chrome)\n{e}")


def imprimir(navegador, html: str, destino: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        tmp = Path(f.name)
    try:
        pagina = navegador.new_page()
        pagina.goto(tmp.as_uri(), wait_until="networkidle")
        pagina.evaluate("document.fonts.ready")
        pagina.pdf(path=str(destino), prefer_css_page_size=True, print_background=True,
                   outline=True, tagged=True)
        pagina.close()
    finally:
        tmp.unlink(missing_ok=True)


def localizar_capitulos(pdf: Path, total: int) -> dict[int, int]:
    from pypdf import PdfReader
    achados = {}
    for i, pg in enumerate(PdfReader(str(pdf)).pages, start=1):
        for m in re.finditer(r"@@CAP(\d+)@@", pg.extract_text() or ""):
            achados.setdefault(int(m.group(1)), i)
    return achados


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera o cardápio em PDF a partir das páginas do site.")
    ap.add_argument("-o", "--saida", default=str(RAIZ / "menu.pdf"), help="arquivo PDF de saída (padrão: menu.pdf na raiz)")
    ap.add_argument("--papel", choices=PAPEIS, default="A4")
    ap.add_argument("--navegador", help="caminho de um Chrome/Chromium, se o do Playwright não estiver instalado")
    ap.add_argument("--html", action="store_true", help="salva também o HTML montado, para depurar o layout")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright

    saida = Path(a.saida).resolve()
    with sync_playwright() as pw:
        nav = abrir_navegador(pw, a.navegador)

        # 1ª passagem: descobre a página de abertura de cada capítulo
        paginas = {}
        try:
            html, nomes = montar_html(a.papel, None, marcar=True)
            with tempfile.TemporaryDirectory() as d:
                rascunho = Path(d) / "rascunho.pdf"
                imprimir(nav, html, rascunho)
                paginas = localizar_capitulos(rascunho, len(nomes))
        except ImportError:
            print("pypdf ausente: o sumário sai sem números de página.")

        # 2ª passagem: versão final com o sumário preenchido
        html, nomes = montar_html(a.papel, paginas, marcar=False)
        imprimir(nav, html, saida)
        nav.close()

    if a.html:
        saida.with_suffix(".html").write_text(html, encoding="utf-8")
    print(f"PDF gerado: {saida}")
    for n, nome in enumerate(nomes, start=1):
        print(f"  p. {paginas.get(n, '?'):>3}  {nome}")


if __name__ == "__main__":
    main()
