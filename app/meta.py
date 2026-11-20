"""Título, descrição e hashtags de cada corte, a partir do que o chat escreveu."""
import re
import unicodedata
from collections import Counter

from . import settings

# Tipo de momento, reconhecido pelas mensagens do chat logo depois dele
CATS = {
    "policia": dict(re=r"(pol[ií]cia|persegui[çc][aã]o|fuga|fugiu|estrelas?|procurado|swat|viatura|cops|preso|pris[aã]o)",
                    lead="Perseguição insana", tags=["#perseguicao", "#policia", "#fuga"],
                    titles=["A FUGA MAIS INSANA DO {N} NO GTA 6 🚓", "{N} VS A POLÍCIA INTEIRA 🚨", "5 ESTRELAS: {N} ENLOUQUECEU NO GTA 6 🚓"]),
    "fail": dict(re=r"(^f+$|^f\s|\brip\b|morreu|morre|wasted|noob|^-1|perdeu tudo|que burro|burr[oa]|errou|eliminad)",
                 lead="O fail", tags=["#fail", "#gtafail", "#wasted"],
                 titles=["{N} MORREU DO JEITO MAIS BURRO 💀", "F NO CHAT PRO {N} 😭 GTA 6", "{N} PERDEU TUDO EM 1 SEGUNDO 💀"]),
    "epico": dict(re=r"(pog|insan[oa]|brab[oa]|monstro|absurd[oa]|\bclip|clipa|🔥|que isso|goat|lenda|\bgg\b|mito|jogou muito)",
                  lead="Jogada insana", tags=["#insano", "#epico", "#jogadaincrivel"],
                  titles=["{N} FEZ O IMPOSSÍVEL NO GTA 6 🔥", "JOGADA INSANA DO {N} NO GTA 6 😱", "O CHAT PEDIU CLIP: {N} FOI BRABO 🔥"]),
    "susto": dict(re=r"(wtf|monka|caralho|\bmds\b|meu deus|nossa|\boq\b|o que foi|\?\?\?|😱|susto|medo|jumpscare)",
                  lead="A reação", tags=["#susto", "#reacao", "#wtf"],
                  titles=["{N} TOMOU O SUSTO DA VIDA 😱", "O QUE ACONTECEU AQUI, {N}?! 😳", "A REAÇÃO DO {N} FOI SURREAL 😳"]),
    "engracado": dict(re=r"(k{3,}|ha(ha)+|rs(rs)+|\blul\b|kekw|omegalul|icant|😂|🤣|💀|lmao)",
                      lead="Momento hilário", tags=["#humor", "#engracado", "#comedia"],
                      titles=["{N} NÃO AGUENTOU 😂 GTA 6", "O CHAT CHOROU DE RIR COM {N} 😂", "NINGUÉM ESPERAVA ISSO DO {N} 💀"]),
    "geral": dict(re=None, lead="Melhor momento", tags=["#reacao", "#momentos"],
                  titles=["{N} PERDEU A CABEÇA NO GTA 6 🤯", "O MOMENTO MAIS INSANO DA LIVE DO {N}", "OLHA O QUE O {N} FEZ NO GTA 6 👀"]),
}
_RE = {k: re.compile(v["re"], re.I) for k, v in CATS.items() if v["re"]}

# Coisas do GTA que o chat costuma citar: (artigo, o que o streamer "foi fazer")
THINGS = {
    "urso": ("O URSO", "MEXER COM O URSO"), "tubarao": ("O TUBARÃO", "NADAR COM TUBARÃO"),
    "jacare": ("O JACARÉ", "MEXER COM O JACARÉ"), "policia": ("A POLÍCIA", "FUGIR DA POLÍCIA"),
    "viatura": ("A VIATURA", "ROUBAR UMA VIATURA"), "swat": ("A SWAT", "ENFRENTAR A SWAT"),
    "carro": ("O CARRO", "PEGAR UM CARRO"), "moto": ("A MOTO", "DAR GRAU"), "grau": ("O GRAU", "DAR GRAU"),
    "bike": ("A BIKE", "DAR GRAU DE BIKE"), "aviao": ("O AVIÃO", "PILOTAR UM AVIÃO"),
    "helicoptero": ("O HELICÓPTERO", "PILOTAR UM HELICÓPTERO"), "heli": ("O HELI", "PILOTAR UM HELICÓPTERO"),
    "barco": ("O BARCO", "ANDAR DE BARCO"), "lancha": ("A LANCHA", "PILOTAR UMA LANCHA"),
    "caminhao": ("O CAMINHÃO", "ROUBAR UM CAMINHÃO"), "trem": ("O TREM", "PEGAR O TREM"),
    "banco": ("O BANCO", "ASSALTAR O BANCO"), "assalto": ("O ASSALTO", "FAZER UM ASSALTO"),
    "loja": ("A LOJA", "ASSALTAR A LOJA"), "posto": ("O POSTO", "ASSALTAR O POSTO"), "tiro": ("O TIRO", "TROCAR TIRO"),
    "tiroteio": ("O TIROTEIO", "ENTRAR NUM TIROTEIO"), "bomba": ("A BOMBA", "MEXER COM UMA BOMBA"),
    "explosao": ("A EXPLOSÃO", "EXPLODIR TUDO"), "praia": ("A PRAIA", "CURTIR A PRAIA"),
    "prisao": ("A PRISÃO", "FUGIR DA PRISÃO"), "hospital": ("O HOSPITAL", "IR PRO HOSPITAL"),
    "npc": ("O NPC", "ZOAR UM NPC"), "bug": ("O BUG", "TESTAR UM BUG"), "cachorro": ("O CACHORRO", "MEXER COM O CACHORRO"),
    "lucia": ("A LUCIA", "JOGAR COM A LUCIA"), "jason": ("O JASON", "JOGAR COM O JASON"),
    "corrida": ("A CORRIDA", "APOSTAR CORRIDA"), "rampa": ("A RAMPA", "PULAR DA RAMPA"), "ponte": ("A PONTE", "PULAR DA PONTE"),
}
ENDINGS = {
    "engracado": ["E NÃO ESPERAVA POR ISSO KKKKKKKKKK", "E DEU TUDO ERRADO KKKKKKKK"],
    "fail": ["E DEU MUITO RUIM 💀", "E SE ARREPENDEU NA HORA 💀"],
    "epico": ["E FEZ HISTÓRIA 🔥", "E MOSTROU COMO SE FAZ 🔥"],
    "susto": ["E TOMOU O SUSTO DA VIDA 😱", "E NINGUÉM ENTENDEU NADA 😳"],
    "policia": ["E VIROU O MAIS PROCURADO 🚨", "E A POLÍCIA NÃO PERDOOU 🚨"],
    "geral": ["E OLHA NO QUE DEU 😱", "E NÃO ESPERAVA POR ISSO 😳"],
}
EMO = {"engracado": "KKKKKKKKKK", "fail": "💀", "epico": "🔥", "susto": "😱", "policia": "🚨", "geral": "😳"}
PLAT = {"twitch": "Twitch", "kick": "Kick", "youtube": "YouTube"}


def _norm(w):
    return unicodedata.normalize("NFD", w.lower()).encode("ascii", "ignore").decode()


def find_subject(lines):
    seen = Counter()
    for line in lines:
        for w in set(re.findall(r"[a-z]+", _norm(line))):
            if w in THINGS:
                seen[w] += 1
    if seen:
        w, n = seen.most_common(1)[0]
        if n >= 2:
            return w
    return None


def title_list(cat, name, subject):
    N = name.upper()
    C = CATS.get(cat, CATS["geral"])
    ends = ENDINGS.get(cat, ENDINGS["geral"])
    out = []
    if subject:
        art, act = THINGS[subject]
        de = re.sub(r"^O ", "DO ", re.sub(r"^A ", "DA ", art))
        out += [f"{N} FOI {act} NO GTA VI {ends[0]}", f"{N} FOI {act} NO GTA VI {ends[1]}"]
        extra = {
            "engracado": [f"{art} ACABOU COM O {N} KKKKKKKK", f"{N} E {art}: NINGUÉM ESPERAVA ISSO 😂"],
            "fail": [f"{N} MORREU POR CAUSA {de} 💀", f"{art} DESTRUIU O {N} 💀"],
            "epico": [f"{N} DOMINOU {art} NO GTA VI 🔥"],
            "susto": [f"{N} TOMOU SUSTO COM {art} 😱"],
            "geral": [f"OLHA {art} QUE O {N} ACHOU NO GTA VI 👀"],
        }
        out += extra.get(cat, [])
    else:
        out.append(f"O {N} NÃO ESPERAVA POR ISSO NO GTA VI {EMO.get(cat, '😳')}")
    return out + [t.replace("{N}", N) for t in C["titles"]]


def top_message(lines):
    count = Counter()
    first = {}
    for raw in lines:
        t = re.sub(r"\s+", " ", raw.strip())
        t = re.sub(r"k{4,}", "KKKK", t, flags=re.I)
        if len(t) < 2 or len(t) > 70 or re.search(r"https?:|www\.|@", t):
            continue
        key = t.lower()
        count[key] += 1
        first.setdefault(key, t)
    if not count:
        return ""
    best = max(count, key=lambda k: count[k] + (0.5 if " " in k else 0))
    return first[best]


def make_meta(channel, platform, url, lines=(), manual=False):
    lines = list(lines)
    cat, best = "geral", 1
    for k, rx in _RE.items():
        n = sum(1 for l in lines if rx.search(l))
        if n > best:
            cat, best = k, n
    subject = find_subject(lines)
    titles = title_list(cat, channel, subject)
    title = titles[0]
    chat_top = top_message(lines)
    Nn = channel[:1].upper() + channel[1:]
    plat = PLAT.get(platform, "live")
    desc = f"{CATS[cat]['lead']} do {Nn} ao vivo no GTA 6 🎮"
    if chat_top:
        desc += f'\n💬 O chat: "{chat_top}"'
    desc += f"\n🔴 Acompanhe o {Nn} na {plat}: {url}"
    name_tag = "#" + re.sub(r"[^a-z0-9_]", "", channel.lower())
    tags = []
    for t in settings.get("tags").split() + [name_tag, name_tag + "cortes", "#" + plat.lower()] + CATS[cat]["tags"]:
        t = t if t.startswith("#") else "#" + t
        if t not in tags:
            tags.append(t)
    return {
        "cat": cat, "subject": subject, "title": title, "title_idx": 0, "descr": desc,
        "tags": " ".join(tags), "chat_top": chat_top,
        "overlay": title if settings.get("ov_on") else "",
    }
