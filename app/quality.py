"""
Nota de qualidade do corte (0 a 10), focada no que importa pra um corte bom:
  - o que o streamer FALA perto do momento: reação ("meu deus", "que isso"), descoberta ("olha isso",
    "descobri"), coisa engraçada ("kkkk") e quanto ele fala
  - o "pico" (áudio/chat) entra com peso menor: barulho de jogo sem fala nenhuma ganha nota baixa
E aprende com você: cortes que você aprova/posta contam como bons, os que você exclui como ruins.
"""
import json
import math
import re
import time
import unicodedata

from . import config as C
from . import db

REACTION = ["meu deus", "caraca", "caramba", "que isso", "nao acredito", "olha isso", "olha so", "socorro", "nossa",
            "wtf", "caralho", "pqp", "vish", "eita", "que porra", "ta louco", "doido", "absurdo", "insano", "surreal",
            "corre", "cuidado", "morri", "mano do ceu", "nao nao", "para para", "ai meu", "jesus", "que loucura",
            "inacreditavel", "nao pode ser", "como assim", "o que", "puta merda", "misericordia"]
DISCOVERY = ["descobri", "voces viram", "viu isso", "sabia que", "da pra", "consegui", "achei", "olha o que",
             "repara", "segredo", "easter egg", "que legal", "que da hora", "incrivel", "perfeito", "nunca vi",
             "primeira vez", "olha ali", "olha la", "funciona", "detalhe", "realista", "nunca tinha visto",
             "impressionante", "que lindo", "que bonito", "olha que", "grafico", "que perfeicao", "que detalhe",
             "nao sabia", "tem como", "olha esse", "olha essa"]
BUG = ["bug", "bugou", "bugado", "glitch", "atravessou", "atravessei", "caiu do mapa", "voou", "voando", "travou",
       "preso", "ficou preso", "entrou na parede", "dentro da parede", "fisica", "que bizarro", "bizarro", "sumiu",
       "teleport", "flutuando", "de ponta cabeca", "desapareceu"]
FUNNY = ["kkk", "haha", "hehe", "rsrs", "risos", "zoeira", "que vergonha", "ridiculo", "palhaco", "kkkk",
         "to rindo", "morrendo de rir", "chorando de rir", "piada"]

WIN_BEFORE, WIN_AFTER = 10.0, 12.0     # janela ao redor do momento forte (segundos)
MODEL_PATH = C.DATA_DIR / "aprendizado.json"
FEATS = ["sinal", "fala", "reacao", "descoberta", "engracado", "sem_fala", "bug", "nao_ouviu", "curtido"]


def _liked(text):
    try:
        from . import likes
        return likes.match(text)
    except Exception:
        return []

with db._lock:
    db._conn.execute("CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                     "clip_id INTEGER, features TEXT, label INTEGER, at REAL)")
    db._conn.commit()


def _norm(t):
    t = unicodedata.normalize("NFD", (t or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def _hits(text, words):
    found = []
    for w in words:
        if re.search(rf"\b{re.escape(w)}", text):
            found.append(w)
    return found


def evaluate(signal, speech, peak_rel, dur=None):
    """
    signal: nota do pico (0-10, áudio/chat) · speech: [(início, fim, texto)] do corte · peak_rel: segundo do momento no corte
    Retorna dict com a nota final e o porquê. 'known' = False quando não deu pra ouvir a fala.
    """
    signal = min(10.0, max(0.0, signal or 0))
    if speech is None:
        # sem ouvir a fala: o aprendizado usa só o pico (áudio/chat), pra aprovar/excluir contar mesmo assim
        feats = {f: 0.0 for f in FEATS}
        feats.update(sinal=signal / 10, nao_ouviu=1.0)
        final = signal
        learned = predict(feats)
        if learned is not None:
            final = 0.5 * final + 0.5 * learned * 10
        return {"known": False, "final": round(min(10.0, final), 1), "content": None, "signal": signal, "reasons": [],
                "features": feats}
    p = peak_rel if peak_rel is not None else (dur or 60) * 0.65
    a, b = p - WIN_BEFORE, p + WIN_AFTER
    near = [(s, e, t) for s, e, t in speech if e >= a and s <= b]
    talk = sum(min(e, b) - max(s, a) for s, e, _ in near)
    ratio = max(0.0, min(1.0, talk / (b - a)))
    text = _norm(" ".join(t for _, _, t in near))
    whole = _norm(" ".join(t for _, _, t in speech))
    react, disc, fun = _hits(text, REACTION), _hits(text, DISCOVERY), _hits(whole, FUNNY)
    bug = _hits(text, BUG)
    liked = _liked(text)            # assuntos parecidos com os cortes que você aprovou
    excl = sum(t.count("!") + t.count("?") for _, _, t in near)
    reasons = []
    if not near:
        content = 0.5
        reasons.append("🔇 ninguém falou perto do momento (pode ser só barulho do jogo)")
    else:
        content = 2.0 + min(2.0, ratio * 3) + min(5.0, len(react) * 1.8) + min(4.0, len(disc) * 1.8) \
            + min(4.5, len(bug) * 2.2) + min(4.0, len(fun) * 1.6) + min(0.8, excl * 0.2) + min(3.0, len(liked) * 1.6)
        content = min(10.0, content)
        quote = max(near, key=lambda x: len(_hits(_norm(x[2]), REACTION + DISCOVERY + FUNNY + BUG)) * 10 + min(len(x[2]), 60))[2]
        if bug:
            reasons.append(f"🐞 bug no jogo: “{quote.strip()[:60]}”")
        elif disc and len(disc) >= len(react):
            reasons.append(f"🔎 descoberta: “{quote.strip()[:60]}”")
        elif react:
            reasons.append(f"🗣 reação: “{quote.strip()[:60]}”")
        elif disc:
            reasons.append(f"🔎 descoberta: “{quote.strip()[:60]}”")
        elif fun:
            reasons.append(f"😂 engraçado: “{quote.strip()[:60]}”")
        elif ratio < 0.15 and not liked:
            reasons.append("🤐 falou pouco no momento")
        elif not liked:
            reasons.append(f"🎙 falando: “{quote.strip()[:60]}”")
        if liked:
            reasons.append("⭐ parecido com cortes que você aprovou: " + ", ".join(liked[:3]))
    feats = {"sinal": signal / 10, "fala": ratio, "reacao": min(3, len(react)) / 3, "descoberta": min(3, len(disc)) / 3,
             "engracado": min(3, len(fun)) / 3, "sem_fala": 0.0 if near else 1.0, "bug": min(2, len(bug)) / 2,
             "nao_ouviu": 0.0, "curtido": min(2, len(liked)) / 2}
    final = 0.3 * signal + 0.7 * content      # o que ele fala pesa mais que o barulho
    learned = predict(feats)
    if learned is not None:
        final = 0.5 * final + 0.5 * learned * 10
        reasons.append("🧠 ajustada pelo que você aprova")
    return {"known": True, "final": round(min(10.0, final), 1), "content": round(content, 1), "signal": round(signal, 1),
            "reasons": reasons, "features": feats}


# palavras comuns demais pra, sozinhas, virarem corte ("o que você quer?", "corre ali")
WEAK = {"o que", "corre", "cuidado", "nossa", "como assim", "da pra", "achei", "consegui", "funciona", "detalhe",
        "tem como", "olha esse", "olha essa", "olha ali", "olha la", "repara", "preso", "voando", "sumiu", "fisica",
        "haha", "hehe", "rsrs", "doido", "nao nao"}


def speech_moment(text):
    """
    Nota (0-10) de uma frase falada na live: reação, descoberta, bug ou risada. 0 = frase comum.
    Precisa de pelo menos uma palavra forte ("meu deus", "que isso", "bugou", "kkkk"...) ou duas comuns.
    """
    t = _norm(text)
    found = _hits(t, REACTION) + _hits(t, DISCOVERY) + _hits(t, BUG) + _hits(t, FUNNY)
    strength = sum(0.5 if w in WEAK else 1.0 for w in dict.fromkeys(found))
    strength += min(2, len(_liked(text))) * 1.0     # assunto que você curte (de cortes que você aprovou)
    if strength < 1:
        return 0.0
    excl = (text or "").count("!") + (text or "").count("?")
    bug = 0.6 if _hits(t, BUG) and any(w not in WEAK for w in _hits(t, BUG)) else 0
    return round(min(10.0, 3.2 + 2.0 * strength + bug + min(0.8, excl * 0.3)), 1)


# ------------------------------------------------------------ aprender com você
def record(clip_id, features_json, label):
    """label 1 = você aprovou/postou · 0 = você excluiu sem usar."""
    if not features_json:
        features_json = _signal_only(clip_id)
    if not features_json:
        return
    if db.query("SELECT id FROM feedback WHERE clip_id=?", (clip_id,)):
        return
    db.insert("feedback", {"clip_id": clip_id, "features": features_json, "label": int(label), "at": time.time()})
    train()


def total_views(views_json):
    try:
        return sum(int(v or 0) for v in json.loads(views_json or "{}").values())
    except Exception:
        return 0


def _view_labels():
    """
    Cortes com visualizações anotadas: os que foram melhor que a metade dos seus outros postados contam como
    'bons' e os piores como 'ruins'. Isso vale mais do que só ter aprovado (o público é quem decide).
    """
    rows = [r for r in db.query("SELECT id, features, views FROM clips WHERE views IS NOT NULL AND features IS NOT NULL")
            if total_views(r["views"]) > 0]
    if len(rows) < 6:
        return {}
    vals = sorted(total_views(r["views"]) for r in rows)
    med = vals[len(vals) // 2]
    return {r["id"]: (r["features"], 1 if total_views(r["views"]) >= med else 0) for r in rows}


def _training_rows():
    data = {r["clip_id"]: (r["features"], r["label"]) for r in db.query("SELECT clip_id, features, label FROM feedback")}
    data.update(_view_labels())            # as views mandam mais que a aprovação
    return [{"features": f, "label": l} for f, l in data.values()]


def _signal_only(clip_id):
    """Corte sem a fala ouvida: usa só a nota do pico."""
    c = db.query("SELECT signal_score, score FROM clips WHERE id=?", (clip_id,))
    if not c:
        return None
    feats = {f: 0.0 for f in FEATS}
    feats.update(sinal=min(10.0, float(c[0]["signal_score"] or c[0]["score"] or 0)) / 10, nao_ouviu=1.0)
    return json.dumps(feats)


def backfill():
    """Cortes que você já aprovou/postou antes (e não contaram pro aprendizado) passam a contar."""
    rows = db.query("SELECT id, features FROM clips WHERE status IN ('aprovado','postado') "
                    "AND id NOT IN (SELECT clip_id FROM feedback WHERE clip_id IS NOT NULL)")
    for r in rows:
        f = r["features"] or _signal_only(r["id"])
        if f:
            db.insert("feedback", {"clip_id": r["id"], "features": f, "label": 1, "at": time.time()})
    if rows:
        train()
    return len(rows)


def stats():
    rows = _training_rows()
    pos = sum(r["label"] for r in rows)
    n_views = len(_view_labels())
    return {"bons": pos, "ruins": len(rows) - pos, "ativo": MODEL_PATH.exists(), "com_views": n_views}


def train():
    """Regressão logística simples com o que você aprovou/excluiu e com as views (precisa de 15 bons e 15 ruins)."""
    rows = _training_rows()
    pos = sum(r["label"] for r in rows)
    if pos < 15 or len(rows) - pos < 15:
        return
    X = [[json.loads(r["features"]).get(f, 0.0) for f in FEATS] for r in rows]
    y = [r["label"] for r in rows]
    w, bias = [0.0] * len(FEATS), 0.0
    for _ in range(800):
        gw, gb = [0.0] * len(FEATS), 0.0
        for xi, yi in zip(X, y):
            z = bias + sum(a * b for a, b in zip(w, xi))
            p = 1 / (1 + math.exp(-max(-30, min(30, z))))
            for k in range(len(w)):
                gw[k] += (p - yi) * xi[k]
            gb += p - yi
        n = len(X)
        w = [wk - 0.5 * (g / n + 0.01 * wk) for wk, g in zip(w, gw)]
        bias -= 0.5 * gb / n
    MODEL_PATH.write_text(json.dumps({"w": w, "b": bias, "feats": FEATS, "n": len(X)}), encoding="utf-8")


def predict(feats):
    try:
        m = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    z = m["b"] + sum(wk * feats.get(f, 0.0) for wk, f in zip(m["w"], m["feats"]))
    return 1 / (1 + math.exp(-max(-30, min(30, z))))
