"""
Regras especiais por streamer (campeonatos de cortes).
Só valem pros cortes daquele canal; os outros continuam normais.
Cada regra veio do PDF "Regras e Informações" do campeonato.
"""
import re
from pathlib import Path

from . import config as C

LOWERS_DIR = C.DATA_DIR / "lowers"
LOWERS_DIR.mkdir(parents=True, exist_ok=True)
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")
VID_EXT = (".mp4", ".mov", ".webm", ".mkv")

RULES = {
    "orenatovicente": {
        "label": "Campeonato Renato Vicente",
        "display": "Renato",
        "watermark": "kick.com/orenatovicente",      # no corte inteiro, legível
        "title_tag": "#orenatovicente",              # obrigatória no título
        "mention": "@orenatovicente",
        "hashtags": ["#orenatovicente", "#renatovicente"],
        "yt_tags": ["renato vicente", "orenatovicente", "cortes renato vicente", "renato vicente gta 6"],
        "notes": ["O corte precisa ter o Renato participando de verdade.",
                  "Não postar o mesmo corte duas vezes na mesma plataforma."],
    },
    "allanstag": {
        "label": "Campeonato Allan Stag",
        "display": "Allan",
        "watermark": "kick.com/allanstag",           # no corte inteiro, legível
        "title_tag": "#allanstag",                   # obrigatória no título
        "mention": None,
        "hashtags": ["#allanstag"],
        "yt_tags": ["allan stag", "allanstag", "cortes allan stag", "allan stag gta 6"],
        "notes": ["O corte precisa ter o Allan participando de verdade.",
                  "Proibido usar imagens de familiares do Allan.",
                  "Não pode postar em carrossel ou imagem parada."],
    },
    "mitsuke": {
        "label": "Campeonato Mitsuke",
        "display": "Mitsuke",
        "watermark": "kick.com/mitsuke",             # sobreposto no corte (não só na legenda)
        "title_tag": "#mitsuke",                     # no título ou na descrição (vai nos dois)
        "mention": None,
        "hashtags": ["#mitsuke"],
        "yt_tags": ["mitsuke", "mitsuke01", "cortes mitsuke", "mitsuke gta 6"],
        "notes": ["Só vale no Instagram, TikTok e YouTube.",
                  "Não pode repostar vídeos que o próprio Mitsuke postou."],
    },
    "luanz7": {
        "label": "Campeonato Luanz7",
        "display": "Luan",
        "lower": True,                               # imagem oficial "Lower - Luanz7" no corte
        "title_tag": "#luanz7",
        "mention": "@luanz7",
        "hashtags": ["#luanz7"],
        "yt_tags": ["luanz7", "luan z7", "cortes luanz7", "luanz7 gta 6"],
        "notes": ["Só valem trechos de lives a partir de 19/11/2026.",
                  "Não pode repostar vídeos que o próprio Luanz7 postou."],
    },
    "sofiaespanha": {
        "label": "Campeonato Sofia Espanha",
        "display": "Sofia",
        "fem": True,                                 # "A SOFIA", não "O SOFIA"
        "watermark": "twitch.tv/sofiaespanha",       # o corte inteiro, 100% legível
        "title_tag": "#sofiaespanha",                # obrigatória no título
        "mention": "@sofiaespanha",
        "hashtags": ["#sofiaespanha"],
        "yt_tags": ["sofia espanha", "sofiaespanha", "cortes sofia espanha", "sofia espanha gta 6", "sofia espanha twitch"],
        "notes": ["O corte precisa ter a Sofia como protagonista na maior parte.",
                  "Vale live da Twitch e vídeo do YouTube dela.",
                  "Proibido fake react."],
    },
    "yayahuz": {
        "label": "Campeonato Yayah",
        "display": "Yayah",
        "fem": True,                                 # "A YAYAH", não "O YAYAH"
        "safe": True,                                # títulos e textos só respeitosos (regra 9)
        "title_tag": "#yayah",
        "mention": "@yayahuz",
        "hashtags": ["#yayah", "#yayahuz"],
        "yt_tags": ["yayah", "yayahuz", "cortes yayah", "yayah gta 6"],
        "notes": ["Atenção: nada que exponha, constranja ou incomode a Yayah. Nada de foco no corpo, zoom, "
                  "duplo sentido ou trecho fora de contexto. Na dúvida, não poste.",
                  "Não vale corte de react de filme ou série."],
    },
    "paulinholokobr": {
        "label": "Campeonato Paulinho o Loko",
        "display": "Paulinho",
        "watermark": "kick.com/paulinholokobr",      # NO CORTE (não vale só na legenda/título)
        "title_tag": "#paulinhooloko",               # obrigatória em todos os cortes
        "mention": None,
        "hashtags": ["#paulinhooloko", "#paulinholoko"],
        "yt_tags": ["paulinho o loko", "paulinholoko", "paulinho loko", "paulinholokobr", "cortes paulinho o loko"],
        "notes": ["Só valem trechos de lives e vídeos com o Paulinho de 17/10/2026 pra frente (campeonato de 22/11 a 22/12).",
                  "Título, hashtags e legenda têm que ter a ver com o corte (nada aleatório nem em outro idioma).",
                  "Não pode repetir o mesmo vídeo na mesma plataforma, nem postar muito corte só pra ganhar view.",
                  "Não vale corte feito só com IA: revise e edite antes de postar.",
                  "Proibido marca/link de casa de aposta ou afiliado no vídeo, na legenda ou na bio."],
    },
}
ALIASES = {"paulinholoko": "paulinholokobr", "paulinhooloko": "paulinholokobr", "paulinho": "paulinholokobr",
           "paulinhoololoko": "paulinholokobr", "renatovicente": "orenatovicente", "mitsuke01": "mitsuke", "yayah": "yayahuz", "luan": "luanz7",
           "sofia": "sofiaespanha", "sofiaespanhaoficial": "sofiaespanha"}

# palavras que não entram nos títulos/textos dos canais com regra "safe"
UNSAFE = re.compile(r"(VERGONHA|BURR|SURT|SABOT|FAIL|MORREU|WASTED|CHOR|PERDEU A CABE|PASSOU DO LIMITE|"
                    r"ZOO|TROLL|MEDO|ASSUST|CAIR DA CADEIRA|CAIU|F NO CHAT|GRIT|ESTOUR|MICROFONE|"
                    r"NÃO PERDOA|DESTRUIU|ACABOU COM|SE ARREPEND|DEU RUIM|DEU TUDO ERRADO|CAOS|💀|😭)")
SAFE_TITLES = ["A {N} NÃO ESPERAVA POR ESSA 😂", "OLHA A REAÇÃO DA {N} 😂", "MELHOR MOMENTO DA LIVE DA {N} ✨",
               "ISSO SÓ ACONTECE NA LIVE DA {N} 😂", "A {N} E O CHAT NESSE MOMENTO 😂", "A {N} NO GTA 6 É OUTRO NÍVEL ✨",
               "A RISADA DA {N} NESSE MOMENTO 😂", "A {N} DESCOBRIU ISSO NO GTA 6 😳", "MOMENTO ALEATÓRIO DA LIVE DA {N} 😂",
               "A {N} FICOU SEM PALAVRAS 😳", "QUE MOMENTO DA {N} NO GTA 6 ✨", "A {N} JOGANDO GTA 6 E O CHAT AMANDO 😂"]
SAFE_HOOKS = ["A {N} NÃO ESPERAVA POR ESSA NO GTA VI 😂", "OLHA A REAÇÃO DA {N} NO FINAL 😂", "ESPERA ATÉ O FINAL 😳",
              "QUE MOMENTO DA {N} NO GTA VI ✨", "A {N} DESCOBRIU UMA COISA NO GTA VI 😳", "O CHAT AMOU ESSE MOMENTO DA {N} 😂"]


def _key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def key_for(name):
    k = _key(name)
    if k in RULES:
        return k
    return ALIASES.get(k) if ALIASES.get(k) in RULES else None


def for_channel(name):
    k = key_for(name)
    return RULES[k] if k else None


def display(name):
    r = for_channel(name)
    return r["display"] if r else name


def title_with_tag(name, title):
    """Garante a hashtag obrigatória no título."""
    r = for_channel(name)
    if r and r.get("title_tag") and r["title_tag"].lower() not in (title or "").lower():
        return f"{title} {r['title_tag']}".strip()
    return title


def adapt(name, texts, kind="title"):
    """Ajusta títulos/textos pro canal: feminino quando for o caso e só respeitosos nos canais 'safe'."""
    r = for_channel(name)
    if not r:
        return list(texts)
    N = r["display"].upper()
    out = []
    for t in texts:
        if r.get("fem"):
            for a, b in (("O ", "A "), ("DO ", "DA "), ("PRO ", "PRA "), ("NO ", "NA "), ("AO ", "À "), ("COM O ", "COM A ")):
                t = re.sub(rf"(?<![A-ZÀ-Ú]){a}{N}\b", f"{b}{N}", t)
            for a, b in (("TRANQUILO", "TRANQUILA"), ("CHOCADO", "CHOCADA"), ("PRONTO", "PRONTA"), ("MALUCO", "MALUCA"),
                         ("REVOLTADO", "REVOLTADA"), ("SOFRENDO", "SOFRENDO"), ("LOUCO", "LOUCA")):
                t = t.replace(a, b)
        if r.get("safe") and UNSAFE.search(t):
            continue
        out.append(t)
    if r.get("safe"):
        extra = SAFE_TITLES if kind == "title" else SAFE_HOOKS
        out += [t.replace("{N}", N) for t in extra if t.replace("{N}", N) not in out]
    return out


def is_safe(name):
    r = for_channel(name)
    return bool(r and r.get("safe"))


def lower_file(name):
    """Imagem/vídeo do Lower que você enviou pro canal (ou None)."""
    k = key_for(name)
    if not k or not RULES[k].get("lower"):
        return None
    for f in sorted(LOWERS_DIR.glob(f"{k}.*")):
        if f.name.startswith("_"):
            continue
        if f.suffix.lower() in IMG_EXT + VID_EXT:
            return f
    return None


def mark_for(name):
    """O que vai sobreposto no vídeo: texto da marca d'água, arquivo do Lower ou nada."""
    r = for_channel(name)
    if not r:
        return None
    if r.get("lower"):
        return lower_file(name)
    return r.get("watermark")


def public(name):
    """O que o painel precisa saber das regras desse canal."""
    k = key_for(name)
    if not k:
        return None
    r = RULES[k]
    lf = lower_file(name)
    out = {"key": k, "label": r["label"], "watermark": r.get("watermark"), "title_tag": r.get("title_tag"),
           "mention": r.get("mention"), "notes": r.get("notes", []), "lower": bool(r.get("lower")),
           "lower_url": f"/api/rules/{k}/lower_preview?v={int(lf.stat().st_mtime)}" if lf else None,
           "lower_missing": bool(r.get("lower")) and not lf, "safe": bool(r.get("safe"))}
    if lf:
        try:
            from . import render
            info = render.lower_info(lf)
            full = info["size"][1] / info["size"][0] > 1.2
            out.update(lower_wf=info["wfrac"] if full else 0.86, lower_x=info["cx"] if full else 0.5,
                       lower_y=info["cy"] if full else 0.8)
        except Exception:
            pass
    return out
