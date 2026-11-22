"""
"O que você curte": aprende com os cortes que você aprovou/postou QUAIS ASSUNTOS do jogo aparecem neles
(missão, lugar, bicho, veículo, situação...) e dá nota extra quando QUALQUER streamer falar desses assuntos.
Ex.: você aprovou o Renato no "aeroporto" e no "jacaré" -> o Allan falando de jacaré ganha nota a mais.
Nomes de streamer ficam de fora, pra valer pra todo mundo. Dá pra tirar um assunto pelo painel.
"""
import json
import math
import re
import threading
from collections import Counter

from . import config as C
from . import db, rules
from .quality import BUG, DISCOVERY, FUNNY, REACTION, _norm

PATH = C.DATA_DIR / "curtidos.json"
MIN_CLIPS = 3                 # precisa de pelo menos 3 cortes aprovados com a fala ouvida
MAX_TERMS = 40
_lock = threading.Lock()
_cache = {"terms": {}, "bad": {}, "blocked": [], "n": 0, "n_bad": 0}

STOP = set("""
a o e é as os um uma uns umas de do da dos das no na nos nas em pra pro pras pros para por pelo pela com sem que
se ser ter tem tinha tava tá ta to tô estou esta está estava foi vai vou vamos ia era sou são seu sua meu minha
nosso nossa ele ela eles elas eu você voce vocês voces vc mano cara velho vei veio tipo assim então entao ai aí
la lá aqui ali isso isto esse essa este esta aquele aquela mais menos muito muita pouco bem mal sim não nao nem
já ja ainda agora depois antes hoje ontem amanhã quando onde como porque porquê qual quais quem tudo nada todo
toda todos todas algum alguma coisa coisas gente galera chat né ne hein opa ok okay beleza blz então daí dai
olha olhar vem vai bora fala falar faz fazer fez feito pega pegar deu dar dá da dá vê ver vi viu sabe saber acho
achei quer querer queria pode poder posso vou vai fica ficar ficou parece mesmo também tambem só so sempre nunca
aí uhm hum ah eh oh ué ue pô po porra caralho cacete merda puta foda fodase krl pqp mds slk tlgd
""".split())
GENERIC = set(_norm(w) for w in REACTION + DISCOVERY + BUG + FUNNY)
GENERIC |= {p for w in GENERIC for p in w.split()}          # "meu deus" -> "deus" também não é assunto
GENERIC |= {"gta", "jogo", "jogar", "jogando", "live", "stream", "video", "vídeo", "clip", "corte", "cortes", "kkk",
            "kkkk", "kkkkk", "haha", "gente", "pessoal", "obrigado", "valeu", "seguir", "inscreve"}


# Só coisas DO JOGO viram "assunto" (lugar, veículo, bicho, missão, situação). Palavras soltas como "favor",
# "querendo", "fora" nunca entram.
GAME = """
assalto aviao banco barco bike bomba bug cachorro caminhao carro corrida explosao grau heli helicoptero hospital
jacare jason lancha loja lucia moto npc policia ponte posto praia prisao rampa swat tiro tiroteio trem tubarao urso
viatura aeroporto aviao jatinho paraquedas paraquedista pulo salto queda cachoeira lago rio mar oceano ilha pantano
mangue floresta montanha deserto fazenda cidade vice city leonida miami keys port gellhorn ambrosia grassrivers
mount kalaga praia vice beach shopping mercado mercadinho lanchonete restaurante bar boate balada clube posto
gasolina hotel cassino estadio academia igreja delegacia cadeia presidio penitenciaria hospital farmacia oficina
garagem estacionamento predio cobertura mansao casa favela trailer porto navio iate jetski submarino tanque
onibus taxi ambulancia bombeiro caminhao guincho limousine quadriciclo trator tratorzinho skate bicicleta patinete
perseguicao fuga roubo furto sequestro refem tiroteio troca tiro emboscada racha corrida drift manobra grau
acidente batida capotou capotar explodiu explosao incendio fogo tornado furacao tempestade chuva raio enchente
missao missoes golpe heist cofre joalheria loja roupa tatuagem barbearia salao cabelo academia pesca pescar caca
cacar crocodilo jacare tubarao cobra urso puma onca flamingo passaro gaivota cavalo vaca porco galinha peixe golfinho
baleia arma fuzil pistola sniper metralhadora granada faca bazuca rpg colete dinheiro grana cofre maleta droga
procurado estrela estrelas wanted swat fbi exercito militar helicoptero drone
""".split()
GAME_SET = {_norm(w) for w in GAME}
GAME_PHRASES = {"vice city", "port gellhorn", "grassrivers", "mount kalaga", "vice beach", "loja roupa",
                "troca tiro", "jet ski"}


def _game_terms(text):
    """Coisas do jogo que aparecem no texto (palavras da lista e algumas expressões de duas palavras)."""
    ws = _norm(text).split()
    out = {w for w in ws if w in GAME_SET}
    out |= {f"{a} {b}" for a, b in zip(ws, ws[1:]) if f"{a} {b}" in GAME_PHRASES}
    for ph in [t for t in out if " " in t]:          # "vice city" já diz tudo: tira "vice" e "city" sozinhos
        out -= set(ph.split())
    return out


def _words(text):
    return [w for w in _norm(text).split() if len(w) >= 4 and w not in STOP and not w.isdigit() and not w.startswith("kk")]


def _names():
    """Nomes de streamers (e apelidos) pra não virarem 'assunto'."""
    out = set()
    for r in db.query("SELECT DISTINCT channel_name FROM clips"):
        n = _norm(r["channel_name"] or "")
        out |= {n, *n.split()}
        out.add(_norm(rules.display(r["channel_name"] or "")))
    for k, r in rules.RULES.items():
        out |= {k, _norm(r["display"])}
    out |= set(rules.ALIASES)
    return {x for x in out if x}


def _terms_of(text, names):
    return {t for t in _game_terms(text) if t not in names}


def _pretty(texts):
    """Jeito bonito (com acento) de cada palavra: 'jacare' -> 'jacaré'."""
    out = {}
    for tx in texts:
        for w in re.findall(r"[0-9a-zà-öø-ÿ]+", (tx or "").lower()):
            out.setdefault(_norm(w), w)
    return out


def _side(good, bad, names, blocked):
    """Assuntos que aparecem bem mais em 'good' do que em 'bad'."""
    terms = {}
    if len(good) < MIN_CLIPS:
        return terms
    gk = Counter(t for tx in good for t in _terms_of(tx, names))
    bk = Counter(t for tx in bad for t in _terms_of(tx, names))
    ng, nb = len(good), max(1, len(bad))
    for t, n in gk.items():
        if n < 2 or t in blocked:
            continue
        share_g, share_b = n / ng, bk.get(t, 0) / nb
        if share_g < 0.12 or share_g < share_b * 1.5:
            continue
        terms[t] = round(share_g * math.log(1 + n) * (1.3 if " " in t else 1.0), 3)
    # se a dupla de palavras já está, a palavra sozinha só fica se aparecer bem mais
    for t in [t for t in terms if " " in t]:
        for w in t.split():
            if w in terms and gk[w] <= gk[t] + 1:
                terms.pop(w, None)
    return dict(sorted(terms.items(), key=lambda kv: -kv[1])[:MAX_TERMS])


def rebuild():
    """Recalcula os assuntos que você curte e os que você costuma descartar (ao aprovar/postar/excluir e ao abrir)."""
    names = _names()
    liked = {r["id"]: r["transcript"] for r in db.query(
        "SELECT id, transcript FROM clips WHERE (status IN ('aprovado','postado') OR posted_on IS NOT NULL) "
        "AND transcript IS NOT NULL AND transcript<>''")}
    disliked = {}
    for r in db.query("SELECT clip_id, label, text FROM feedback WHERE text IS NOT NULL AND text<>''"):
        (liked if r["label"] else disliked).setdefault(r["clip_id"], r["text"])
    for k in list(disliked):
        if k in liked:                            # aprovou depois: vale o aprovado
            disliked.pop(k)
    pending = [r["transcript"] for r in db.query(
        "SELECT transcript FROM clips WHERE status NOT IN ('aprovado','postado') AND posted_on IS NULL "
        "AND transcript IS NOT NULL AND transcript<>''")]
    blocked = load().get("blocked", [])
    lk, dk = list(liked.values()), list(disliked.values())
    terms = _side(lk, dk + pending, names, blocked)
    bad = _side(dk, lk, names, blocked)
    for t in list(bad):
        if t in terms:
            bad.pop(t)
    pretty = _pretty(lk + dk)
    show = {t: " ".join(pretty.get(w, w) for w in t.split()) for t in list(terms) + list(bad)}
    data = {"terms": terms, "bad": bad, "show": show, "blocked": blocked, "n": len(lk), "n_bad": len(dk), "v": VERSION}
    with _lock:
        _cache.update(data)
    try:
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return data


VERSION = 2


def load():
    with _lock:
        if _cache["terms"] or _cache["bad"] or _cache["blocked"] or _cache["n"] or _cache["n_bad"]:
            return dict(_cache)
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
        if d.get("v") != VERSION:              # versão antiga (pegava qualquer palavra): começa limpo
            d = {"terms": {}, "bad": {}, "blocked": [], "n": 0, "n_bad": 0}
        with _lock:
            _cache.update(d)
        return d
    except Exception:
        return {"terms": {}, "blocked": [], "n": 0}


def block(term):
    d = load()
    if term not in d.get("blocked", []):
        d.setdefault("blocked", []).append(term)
    with _lock:
        _cache["blocked"] = d["blocked"]
    PATH.write_text(json.dumps({**d, "blocked": d["blocked"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return rebuild()


def unblock_all():
    with _lock:
        _cache["blocked"] = []
    d = load()
    d["blocked"] = []
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return rebuild()


def match(text, key="terms"):
    """Assuntos curtidos que aparecem nesse texto (os mais fortes primeiro)."""
    terms = load().get(key) or {}
    if not terms or not text:
        return []
    have = _terms_of(text, set())                 # mesmo jeito de quando aprende ("loja de roupa" -> "loja roupa")
    found = [k for k in terms if k in have]
    found = [k for k in found if not any(k != o and k in o.split() for o in found)]   # "jacare" some se tem "jacare gigante"
    return sorted(found, key=lambda k: -terms[k])


def match_bad(text):
    """Assuntos que você costuma descartar que aparecem nesse texto."""
    return match(text, "bad")
