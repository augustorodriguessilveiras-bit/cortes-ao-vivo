"""Gera o post diário do JP Personal Kids para o Instagram.

Uso:
    python gerar_post.py                 # post de hoje
    python gerar_post.py 2026-12-01      # post de uma data específica
    python gerar_post.py --semana        # os 7 posts a partir de hoje
    python gerar_post.py --divulgacao    # post de divulgação das aulas

Saída (pasta saida/AAAA-MM-DD/):
    post.png      -> imagem do feed (1080x1350, formato 4:5)
    story.png     -> versão para stories (1080x1920)
    legenda.txt   -> legenda + hashtags + horário sugerido para postar
"""
import random
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import conteudo

BASE = Path(__file__).resolve().parent
ASSETS = BASE / "assets"
SAIDA = BASE / "saida"

# @ do Instagram que aparece no rodapé (deixe "" para não mostrar)
INSTAGRAM = ""

# Cores tiradas da própria logo
CORES = {
    "roxo": (108, 63, 189),
    "azul_marinho": (24, 58, 140),
    "vermelho": (240, 75, 80),
    "amarelo": (255, 190, 30),
    "verde": (125, 195, 50),
    "azul": (45, 165, 235),
    "fundo": (255, 251, 240),
    "branco": (255, 255, 255),
    "texto": (40, 40, 70),
}
CONFETE = ["roxo", "vermelho", "amarelo", "verde", "azul"]
DIAS = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira",
        "Sexta-feira", "Sábado", "Domingo"]


def fonte(nome, tamanho, peso):
    f = ImageFont.truetype(str(ASSETS / "fonts" / f"{nome}.ttf"), tamanho)
    try:
        f.set_variation_by_axes([peso] if nome == "Nunito" else [peso, 100])
    except Exception:
        pass
    return f


SEM_EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\u200d\ufe0f\u2B00-\u2BFF]")


def limpar(t):
    """Tira emojis (a fonte da arte não tem emoji; eles ficam só na legenda)."""
    return re.sub(r"\s+", " ", SEM_EMOJI.sub("", t)).strip()


def quebrar(draw, texto, f, largura):
    texto = limpar(texto)
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = (atual + " " + palavra).strip()
        if draw.textlength(teste, font=f) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def confetes(draw, W, H, semente, area_livre):
    rnd = random.Random(semente)
    for _ in range(38):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        if area_livre[0] < x < area_livre[2] and area_livre[1] < y < area_livre[3]:
            continue
        cor = CORES[rnd.choice(CONFETE)]
        tipo = rnd.random()
        r = rnd.randint(8, 18)
        if tipo < 0.4:
            draw.ellipse((x - r, y - r, x + r, y + r), fill=cor)
        elif tipo < 0.7:
            draw.rounded_rectangle((x - r * 1.6, y - 5, x + r * 1.6, y + 5), 5, fill=cor)
        else:
            estrela(draw, x, y, r * 1.3, cor)


def estrela(draw, cx, cy, r, cor):
    import math
    pts = []
    for i in range(10):
        ang = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(ang), cy - rr * math.sin(ang)))
    draw.polygon(pts, fill=cor)


def desenhar(dia, post, tema, W, H):
    img = Image.new("RGB", (W, H), CORES["fundo"])
    d = ImageDraw.Draw(img)
    margem = 70
    cor_tema = CORES[tema["cor"]]

    # Faixas coloridas no topo e no rodapé (cores da logo)
    faixa = W / len(CONFETE)
    for i, c in enumerate(CONFETE):
        d.rectangle((i * faixa, 0, (i + 1) * faixa, 16), fill=CORES[c])
        d.rectangle((i * faixa, H - 16, (i + 1) * faixa, H), fill=CORES[c])

    # Logo original num "adesivo" branco
    logo = Image.open(ASSETS / "logo.png").convert("RGB")
    lw = int(W * ((0.42 if post.get("cta") else 0.52) if H < 1600 else 0.62))
    lh = int(logo.height * lw / logo.width)
    logo = logo.resize((lw, lh), Image.LANCZOS)
    pad = 28
    ly = (50 if post.get("cta") else 60) if H < 1600 else 140
    lx = (W - lw) // 2
    d.rounded_rectangle((lx - pad + 6, ly - pad + 10, lx + lw + pad + 6, ly + lh + pad + 10),
                        60, fill=(230, 222, 205))
    d.rounded_rectangle((lx - pad, ly - pad, lx + lw + pad, ly + lh + pad), 60, fill=CORES["branco"])
    img.paste(logo, (lx, ly))
    y = ly + lh + pad + 50

    # Etiqueta do tema
    f_tag = fonte("Fredoka", 40, 600)
    tw = d.textlength(tema["nome"], font=f_tag)
    d.rounded_rectangle(((W - tw) / 2 - 36, y, (W + tw) / 2 + 36, y + 70), 35, fill=cor_tema)
    d.text((W / 2, y + 35), tema["nome"], font=f_tag, fill=CORES["branco"], anchor="mm")
    y += 110

    frase = not post["itens"]
    story = H >= 1600
    cta = post.get("cta")
    fim_cartao = H - (290 if cta else 150) - (60 if cta and story else 0)
    escala = 1.0
    # Diminui as letras até tudo caber no cartão
    while True:
        tam = int(((96 if story else 82) if frase else (88 if story else 70)) * escala)
        while True:
            f_tit = fonte("Fredoka", tam, 600)
            linhas = quebrar(d, post["titulo"], f_tit, W - 2 * margem - 60)
            if len(linhas) <= (5 if frase else 3) or tam <= 40:
                break
            tam -= 4
        alt_linha = int(tam * 1.15)
        f_item = fonte("Nunito", int((58 if story else 46) * escala), 800)
        li = int((72 if story else 58) * escala)
        esp = int(34 * escala)
        itens_linhas = [quebrar(d, it, f_item, W - 2 * margem - 150) for it in post["itens"]]
        altura_itens = sum(len(l) * li + esp for l in itens_linhas)
        bloco = len(linhas) * alt_linha + (30 + altura_itens if not frase else 0)
        if bloco <= fim_cartao - y - 70 or escala < 0.6:
            break
        escala -= 0.05

    d.rounded_rectangle((margem - 20, y, W - margem + 20, fim_cartao), 50, fill=CORES["branco"],
                        outline=cor_tema, width=6)

    ty = y + (fim_cartao - y - bloco) / 2
    if frase:
        d.text((W / 2, ty - 40), "“", font=fonte("Fredoka", 180, 700), fill=cor_tema, anchor="mm")
    for i, ln in enumerate(linhas):
        d.text((W / 2, ty + i * alt_linha + alt_linha / 2), ln, font=f_tit,
               fill=CORES["azul_marinho"], anchor="mm")
    ty += len(linhas) * alt_linha + 30

    if not frase:
        for n, ls in enumerate(itens_linhas):
            c = CORES[CONFETE[(n + 2) % len(CONFETE)]]
            cx = margem + 60
            d.ellipse((cx - 30, ty - 2, cx + 30, ty + 58), fill=c)
            if post.get("marcador") == "check":
                d.line([(cx - 14, ty + 30), (cx - 4, ty + 40), (cx + 15, ty + 16)], fill=CORES["branco"],
                       width=8, joint="curve")
            else:
                d.text((cx, ty + 28), str(n + 1), font=fonte("Fredoka", 38, 600), fill=CORES["branco"], anchor="mm")
            for k, ln in enumerate(ls):
                d.text((cx + 60, ty + 28 + k * li), ln, font=f_item, fill=CORES["texto"], anchor="lm")
            ty += len(ls) * li + esp

    confetes(d, W, H, dia.toordinal(), (margem - 40, ly - pad - 20, W - margem + 40, H - 40))

    # Botão de chamada (posts de divulgação)
    if cta:
        f_cta = fonte("Fredoka", 50 if story else 44, 700)
        cw = d.textlength(cta, font=f_cta) + 100
        by = fim_cartao + (55 if story else 35)
        bh = 100 if story else 90
        d.rounded_rectangle(((W - cw) / 2 + 6, by + 8, (W + cw) / 2 + 6, by + bh + 8), bh / 2, fill=(200, 50, 60))
        d.rounded_rectangle(((W - cw) / 2, by, (W + cw) / 2, by + bh), bh / 2, fill=CORES["vermelho"])
        d.text((W / 2, by + bh / 2), cta, font=f_cta, fill=CORES["branco"], anchor="mm")

    # Rodapé
    f_rod = fonte("Fredoka", 38, 500)
    rodape = INSTAGRAM if INSTAGRAM else "Movimento é diversão!"
    d.text((W / 2, H - 82), rodape, font=f_rod, fill=CORES["roxo"], anchor="mm")
    return img


def escolher(dia):
    wd = dia.weekday()
    lista = conteudo.POSTS[wd]
    semana = dia.toordinal() // 7
    return wd, lista[semana % len(lista)], conteudo.TEMAS[wd]


def gerar(dia):
    wd, post, tema = escolher(dia)
    pasta = SAIDA / dia.isoformat()
    pasta.mkdir(parents=True, exist_ok=True)
    desenhar(dia, post, tema, 1080, 1350).save(pasta / "post.png", optimize=True)
    desenhar(dia, post, tema, 1080, 1920).save(pasta / "story.png", optimize=True)

    hashtags = " ".join(conteudo.HASHTAGS_FIXAS + conteudo.HASHTAGS_TEMA[wd])
    horario = conteudo.HORARIOS[wd]
    texto = (
        f"📅 {DIAS[wd]}, {dia.strftime('%d/%m/%Y')}\n"
        f"⏰ Horário sugerido para postar: {horario}\n"
        f"🏷️ Tema: {tema['nome']}\n\n"
        f"===== LEGENDA (copie daqui para baixo) =====\n\n"
        f"{post['legenda']}\n\n"
        f"📲 Salve este post e compartilhe com quem tem criança em casa!\n"
        f"💬 Quer aulas de personal para o seu filho? Chama no direct!\n\n"
        f"{hashtags}\n"
    )
    (pasta / "legenda.txt").write_text(texto, encoding="utf-8")
    return pasta, horario, tema["nome"], post["titulo"]


def gerar_divulgacao():
    post, tema = conteudo.DIVULGACAO, {"nome": "AULAS DE PERSONAL KIDS", "cor": "roxo"}
    pasta = SAIDA / "divulgacao"
    pasta.mkdir(parents=True, exist_ok=True)
    hoje = date.today()
    desenhar(hoje, post, tema, 1080, 1350).save(pasta / "post.png", optimize=True)
    desenhar(hoje, post, tema, 1080, 1920).save(pasta / "story.png", optimize=True)
    hashtags = " ".join(conteudo.HASHTAGS_FIXAS + ["#personaltrainer", "#aulaexperimental", "#esporteinfantil"])
    (pasta / "legenda.txt").write_text(
        f"⏰ Melhor horário para postar: {conteudo.HORARIO_DIVULGACAO}\n"
        f"🏷️ Post de divulgação (fixe no topo do perfil!)\n\n"
        f"===== LEGENDA (copie daqui para baixo) =====\n\n"
        f"{post['legenda']}\n\n{hashtags}\n", encoding="utf-8")
    print(f"divulgação -> {pasta}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--divulgacao":
        return gerar_divulgacao()
    if args and args[0] == "--semana":
        dias = [date.today() + timedelta(days=i) for i in range(7)]
    elif args:
        dias = [datetime.strptime(args[0], "%Y-%m-%d").date()]
    else:
        dias = [date.today()]
    for dia in dias:
        pasta, horario, tema, titulo = gerar(dia)
        print(f"{dia} | postar às {horario} | {tema} | {titulo} -> {pasta}")


if __name__ == "__main__":
    main()
