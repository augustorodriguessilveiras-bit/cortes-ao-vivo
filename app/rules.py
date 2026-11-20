"""
Regras especiais por streamer (ex: campeonatos de cortes).
Só valem pros cortes daquele canal; os outros continuam normais.
"""
import re

RULES = {
    # Campeonato do Renato Vicente (regras do PDF "Regras e Informações - Renato Vicente")
    "orenatovicente": {
        "label": "Campeonato Renato Vicente",
        "display": "Renato",                         # nome usado nos títulos e textos
        "watermark": "kick.com/orenatovicente",      # marca d'água obrigatória, o corte inteiro
        "title_tag": "#orenatovicente",              # obrigatória no título
        "mention": "@orenatovicente",                # @ oficial pra marcar ao postar
        "hashtags": ["#orenatovicente", "#renatovicente"],
        "drop_hashtags": ["#fyp", "#viral"],         # regra 12: nada de hashtag aleatória
        "yt_tags": ["renato vicente", "orenatovicente", "cortes renato vicente", "renato vicente gta 6",
                    "renato vicente kick"],
    },
}
ALIASES = {"renatovicente": "orenatovicente"}


def _key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def for_channel(name):
    k = _key(name)
    return RULES.get(k) or RULES.get(ALIASES.get(k, ""))


def display(name):
    r = for_channel(name)
    return r["display"] if r else name


def title_with_tag(name, title):
    """Garante a hashtag obrigatória no título."""
    r = for_channel(name)
    if r and r.get("title_tag") and r["title_tag"].lower() not in (title or "").lower():
        return f"{title} {r['title_tag']}".strip()
    return title


def public(name):
    """O que o painel precisa saber das regras desse canal."""
    r = for_channel(name)
    if not r:
        return None
    return {k: r.get(k) for k in ("label", "watermark", "title_tag", "mention")}
