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
             "repara", "segredo", "easter egg", "bug", "que legal", "que da hora", "incrivel", "perfeito", "nunca vi",
             "primeira vez", "olha ali", "olha la", "tem um", "tem uma", "funciona", "detalhe", "realista"]
FUNNY = ["kkk", "haha", "hehe", "rsrs", "risos", "zoeira", "que vergonha", "ridiculo", "palhaco", "kkkk",
         "to rindo", "morrendo de rir", "chorando de rir", "piada"]

WIN_BEFORE, WIN_AFTER = 10.0, 12.0     # janela ao redor do momento forte (segundos)
MODEL_PATH = C.DATA_DIR / "aprendizado.json"
FEATS = ["sinal", "fala", "reacao", "descoberta", "engracado", "sem_fala"]

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
        return {"known": False, "final": round(signal, 1), "content": None, "signal": signal, "reasons": [], "features": None}
    p = peak_rel if peak_rel is not None else (dur or 60) * 0.65
    a, b = p - WIN_BEFORE, p + WIN_AFTER
    near = [(s, e, t) for s, e, t in speech if e >= a and s <= b]
    talk = sum(min(e, b) - max(s, a) for s, e, _ in near)
    ratio = max(0.0, min(1.0, talk / (b - a)))
    text = _norm(" ".join(t for _, _, t in near))
    whole = _norm(" ".join(t for _, _, t in speech))
    react, disc, fun = _hits(text, REACTION), _hits(text, DISCOVERY), _hits(whole, FUNNY)
    excl = sum(t.count("!") + t.count("?") for _, _, t in near)
    reasons = []
    if not near:
        content = 0.5
        reasons.append("🔇 ninguém falou perto do momento (pode ser só barulho do jogo)")
    else:
        content = 2.0 + min(2.0, ratio * 3) + min(5.0, len(react) * 1.8) + min(3.5, len(disc) * 1.6) \
            + min(4.0, len(fun) * 1.6) + min(0.8, excl * 0.2)
        content = min(10.0, content)
        quote = max(near, key=lambda x: len(_hits(_norm(x[2]), REACTION + DISCOVERY + FUNNY)) * 10 + min(len(x[2]), 60))[2]
        if disc and len(disc) >= len(react):
            reasons.append(f"🔎 descoberta: “{quote.strip()[:60]}”")
        elif react:
            reasons.append(f"🗣 reação: “{quote.strip()[:60]}”")
        elif disc:
            reasons.append(f"🔎 descoberta: “{quote.strip()[:60]}”")
        elif fun:
            reasons.append(f"😂 engraçado: “{quote.strip()[:60]}”")
        elif ratio < 0.15:
            reasons.append("🤐 falou pouco no momento")
        else:
            reasons.append(f"🎙 falando: “{quote.strip()[:60]}”")
    feats = {"sinal": signal / 10, "fala": ratio, "reacao": min(3, len(react)) / 3, "descoberta": min(3, len(disc)) / 3,
             "engracado": min(3, len(fun)) / 3, "sem_fala": 0.0 if near else 1.0}
    final = 0.3 * signal + 0.7 * content      # o que ele fala pesa mais que o barulho
    learned = predict(feats)
    if learned is not None:
        final = 0.5 * final + 0.5 * learned * 10
        reasons.append("🧠 ajustada pelo que você aprova")
    return {"known": True, "final": round(min(10.0, final), 1), "content": round(content, 1), "signal": round(signal, 1),
            "reasons": reasons, "features": feats}


# ------------------------------------------------------------ aprender com você
def record(clip_id, features_json, label):
    """label 1 = você aprovou/postou · 0 = você excluiu sem usar."""
    if not features_json:
        return
    if db.query("SELECT id FROM feedback WHERE clip_id=?", (clip_id,)):
        return
    db.insert("feedback", {"clip_id": clip_id, "features": features_json, "label": int(label), "at": time.time()})
    train()


def stats():
    rows = db.query("SELECT label, COUNT(*) n FROM feedback GROUP BY label")
    d = {r["label"]: r["n"] for r in rows}
    return {"bons": d.get(1, 0), "ruins": d.get(0, 0), "ativo": MODEL_PATH.exists()}


def train():
    """Regressão logística simples com o que você aprovou e excluiu (precisa de 15 de cada)."""
    rows = db.query("SELECT features, label FROM feedback")
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
