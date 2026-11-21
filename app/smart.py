"""
Partes "espertas" dos cortes, todas baseadas no que o streamer fala:
  - começo e fim esperto: começa no início de uma frase e termina quando a reação acaba
  - momentos de zoom: onde ele reage forte (grito, "meu deus", bug...)
  - corte repetido: o mesmo momento cortado duas vezes (ex: da live e do VOD da mesma live)
"""
import json

from . import db
from .quality import BUG, DISCOVERY, FUNNY, REACTION, _hits, _norm

MIN_LEN = 15.0


def smart_window(lines, peak, h_dur, max_len=60.0):
    """
    lines: [(início, fim, texto)] do vídeo guardado · peak: segundo do momento forte nesse vídeo.
    Retorna (início, fim) ou None quando não tem fala suficiente pra decidir.
    """
    if not lines or peak is None:
        return None
    lines = sorted(lines)
    max_len = max(MIN_LEN + 5, float(max_len))
    # começo: início de uma frase de 4 a 25 s antes do momento, de preferência depois de uma pausa
    best, best_cost = None, 1e9
    for i, (s, e, _) in enumerate(lines):
        if not (peak - 25 <= s <= peak - 3):
            continue
        gap = s - lines[i - 1][1] if i else 9.0
        cost = abs((peak - s) - 11) - (4 if gap >= 0.6 else 0)
        if cost < best_cost:
            best, best_cost = s, cost
    start = best - 0.35 if best is not None else peak - 10
    # fim: a primeira pausa de verdade (1,2 s sem fala) depois que a reação acabou
    end = None
    for i, (s, e, _) in enumerate(lines):
        if e < peak + 3:
            continue
        nxt = lines[i + 1][0] if i + 1 < len(lines) else h_dur
        if nxt - e >= 1.2 or e - peak >= 25:
            end = e + 0.7
            break
    if end is None:
        end = peak + 8
    start, end = max(0.0, start), min(h_dur, end)
    if end - start > max_len:
        end = start + max_len
    if end - start < MIN_LEN:                       # curto demais: completa dos dois lados
        falta = MIN_LEN - (end - start)
        start = max(0.0, start - falta * 0.6)
        end = min(h_dur, start + MIN_LEN)
    return round(start, 2), round(end, 2)


def group_words(words, gap=0.6):
    """Junta as palavras em frases (quando não tem as frases guardadas)."""
    out, cur = [], []
    for w in (words or []):
        if cur and w[0] - cur[-1][1] > gap:
            out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
            cur = []
        cur.append(w)
    if cur:
        out.append((cur[0][0], cur[-1][1], " ".join(x[2] for x in cur)))
    return out


def zoom_moments(words, lines, ts, te, peak=None, limit=2):
    """Segundos (contando do começo do corte) pra dar o zoom na reação."""
    hits = []
    strong = REACTION + BUG + FUNNY + ["olha isso", "olha so", "descobri"]
    for s, e, t in (lines or []):
        if e < ts or s > te:
            continue
        found = _hits(_norm(t), strong)
        if found:
            w_at = s
            for ws, we, w in (words or []):         # o momento exato da palavra forte, se tiver
                if s <= ws <= e and any(_norm(w) and _norm(w) in f.split() for f in found):
                    w_at = ws
                    break
            hits.append((len(found), w_at - ts))
    if peak is not None and ts <= peak <= te:
        hits.append((1.5, peak - ts))
    out = []
    for _, t in sorted(hits, key=lambda h: -h[0]):
        if 0.5 <= t <= (te - ts) - 1.5 and all(abs(t - o) > 6 for o in out):
            out.append(round(t, 2))
        if len(out) >= limit:
            break
    return sorted(out)


# ------------------------------------------------------------ corte repetido
def _shingles(text, n=3):
    w = _norm(text).split()
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def similarity(a, b):
    sa, sb = _shingles(a), _shingles(b)
    if len(sa) < 6 or len(sb) < 6:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def _text_of(c):
    try:
        lines = json.loads(c.get("transcript") or "[]")
        if lines and isinstance(lines[0], (list, tuple)):
            return " ".join(str(x[2]) for x in lines)
        return " ".join(map(str, lines))
    except Exception:
        return c.get("transcript") or ""


def find_dup(clip_id):
    """Procura um corte do mesmo streamer com a mesma fala. Marca e retorna o id do outro (ou None)."""
    c = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not c:
        return None
    c = c[0]
    me = _text_of(c)
    if len(me.split()) < 12:
        return None
    for o in db.query("SELECT id, transcript FROM clips WHERE channel_name=? AND id<>? ORDER BY created_at DESC LIMIT 300",
                      (c["channel_name"], clip_id)):
        if similarity(me, _text_of(o)) >= 0.45:
            db.update("clips", clip_id, {"dup_of": o["id"]})
            return o["id"]
    return None
