"""
Cortes de VODs (lives que já passaram), um VOD por vez:
  1. pega a versão mais leve do vídeo só pra ouvir o áudio (gasta pouca internet)
  2. acha os momentos em que o áudio explode, comparando com o normal daquele trecho
  3. baixa só os pedaços dos melhores momentos, em alta qualidade, e monta os cortes
"""
import logging
import queue
import subprocess
import threading
import time

import numpy as np

from . import config as C
import json
from pathlib import Path

from . import db, meta, quality, render, settings, sources, transcribe
from .recorder import after_insert, clip_paths, extra_fields, listen, rel, render_vertical_for

log = logging.getLogger("vod")
SR = 8000
_pending = []                 # fila (o primeiro é o próximo)
_running = set()
_cv = threading.Condition()
_stop_ids = set()
MAX_PARALLEL = 3


def _limit():
    try:
        return max(1, min(MAX_PARALLEL, int(settings.get("vod_parallel"))))
    except Exception:
        return 2


def _mark_queue():
    for i, vid in enumerate(_pending, 1):
        db.update("vods", vid, {"status": "na fila" if i == 1 else f"na fila ({i}º)", "progress": 0})


def enqueue(vod_id):
    with _cv:
        if vod_id not in _pending and vod_id not in _running:
            _pending.append(vod_id)
            _mark_queue()
        _cv.notify_all()


def to_front(vod_id):
    """Passa esse VOD na frente da fila."""
    with _cv:
        if vod_id in _pending:
            _pending.remove(vod_id)
            _pending.insert(0, vod_id)
            _mark_queue()
            return True
    return False


def cancel(vod_id):
    _stop_ids.add(vod_id)
    with _cv:
        if vod_id in _pending:
            _pending.remove(vod_id)
            _mark_queue()


def wake():
    """Chamar quando mudar quantos VODs rodam juntos."""
    with _cv:
        _cv.notify_all()


def _set(vod_id, **kw):
    db.update("vods", vod_id, kw)


def _listen(vod_id, info):
    """Lê o áudio do VOD inteiro e devolve o volume (dB) de cada segundo."""
    total = float(info.get("duration") or 0)
    (args, url), *rest = sources.ffmpeg_inputs(info)
    if rest:  # áudio separado (YouTube): ouve só ele
        args, url = rest[-1]
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, "-i", url, "-vn",
                          "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=render.NO_WINDOW)
    db_s, last = [], 0
    try:
        while True:
            if vod_id in _stop_ids:
                raise RuntimeError("cancelado")
            buf = p.stdout.read(SR * 2 * 10)  # 10 segundos por vez
            if not buf:
                break
            a = np.frombuffer(buf[: len(buf) // 2 * 2], np.int16).astype(np.float32) / 32768
            for i in range(0, len(a) - SR + 1, SR):
                db_s.append(float(20 * np.log10(np.sqrt(np.mean(a[i:i + SR] ** 2)) + 1e-6)))
            if total and time.time() - last > 2:
                last = time.time()
                _set(vod_id, status=f"ouvindo o áudio ({len(db_s) // 60} de {int(total // 60)} min)",
                     progress=min(0.7, 0.7 * len(db_s) / total))
    finally:
        p.kill()
    return np.array(db_s)


def _speech_at(info, start, dur, vod_id, i):
    """Baixa só o áudio desse trecho (versão leve) e ouve o que o streamer fala."""
    (args, url), *rest = sources.ffmpeg_inputs(info)
    if rest:
        args, url = rest[-1]
    from . import config as C
    tmp = C.DATA_DIR / f"_trecho_vod{vod_id}_{i}.wav"
    try:
        render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, "-ss", f"{start:.2f}", "-i", url,
                    "-t", f"{dur:.2f}", "-vn", "-ac", "1", "-ar", "16000", str(tmp)], timeout=300)
        return transcribe.transcribe(tmp)
    except Exception:
        return None
    finally:
        tmp.unlink(missing_ok=True)


def find_peaks(levels, min_score, cooldown, max_clips):
    """Mesma nota da live (0 a 10), usando a base dos 10 minutos ao redor de cada trecho."""
    n = len(levels)
    if n < 120:
        return []
    block = 30
    med = np.zeros(n)
    mad = np.zeros(n)
    for b0 in range(0, n, block):
        win = levels[max(0, b0 - 300): min(n, b0 + 300)]
        m = np.median(win)
        med[b0:b0 + block] = m
        mad[b0:b0 + block] = np.median(np.abs(win - m)) * 1.4826 + 1.0
    loud = np.array([levels[t:t + 3].max() for t in range(n)])
    score = np.maximum(0, ((loud - med) / mad - 1) * 2.2)
    order = np.argsort(-score)
    picked = []
    for t in order:
        s = float(score[t])
        if s < 3 or len(picked) >= max_clips:
            break
        if all(abs(int(t) - p[0]) > cooldown for p in picked):
            picked.append((int(t), s, float(loud[t] - med[t])))
    good = [p for p in picked if p[1] >= min_score]
    # se a regra ficou exigente demais pra esse VOD, fica com os 5 melhores mesmo assim
    return good if len(good) >= 3 else picked[:5]


def _process(vod_id):
    v = db.query("SELECT * FROM vods WHERE id=?", (vod_id,))[0]
    cfg = settings.get_all()
    _set(vod_id, status="lendo informações do vídeo", progress=0.02, error=None)
    light = sources.resolve(v["url"], "worst")
    title = light.get("title") or ""
    name = v["name"]
    if name in ("kick", "twitch", "youtube"):
        name = (light.get("uploader_id") or light.get("channel") or light.get("uploader") or name).lower().replace(" ", "")
    _set(vod_id, title=title[:200], name=name)
    theme = sources.guess_theme(light)
    log.info("🎬 VOD de %s: ouvindo o áudio pra achar os melhores momentos…", name)

    levels = _listen(vod_id, light)
    if len(levels) < 60:
        raise RuntimeError("Não consegui ouvir o áudio do vídeo. Confira se o link abre no navegador e tente de novo.")
    vod_max = int(cfg["vod_max"])
    can_listen = transcribe.available()
    # com o reconhecimento de fala: pega mais candidatos e fica só com os melhores (o que ele fala conta mais)
    peaks = find_peaks(levels, cfg["min_score"], cfg["cooldown"], int(vod_max * 2.5) if can_listen else vod_max)
    if not peaks:
        _set(vod_id, status="pronto: nenhum momento forte achado", progress=1)
        return
    evals = {}
    if can_listen:
        thr = float(cfg.get("discard_below") or 0)
        for i, (t, score, gain) in enumerate(peaks, 1):
            if vod_id in _stop_ids:
                raise RuntimeError("cancelado")
            _set(vod_id, status=f"ouvindo o que ele fala nos momentos ({i} de {len(peaks)})",
                 progress=0.7 + 0.1 * (i - 1) / len(peaks))
            start = max(0, t - cfg["before"])
            speech = _speech_at(light, start, cfg["before"] + cfg["after"], vod_id, i)
            evals[t] = (quality.evaluate(score, speech, t - start), speech)
        ok = [p for p in peaks if not evals[p[0]][0]["known"] or thr <= 0 or evals[p[0]][0]["final"] >= thr]
        dropped = len(peaks) - len(ok)
        peaks = sorted(ok, key=lambda p: -evals[p[0]][0]["final"])[:vod_max]
        log.info("🎬 VOD de %s: %d momentos bons escolhidos (%d descartados por nota baixa)", name, len(peaks), dropped)
        if not peaks:
            _set(vod_id, status="pronto: nenhum momento bom o bastante", progress=1)
            return
    peaks.sort()
    best = sources.resolve(v["url"], "best")
    inputs = sources.ffmpeg_inputs(best)
    ch = db.query("SELECT * FROM channels WHERE name=? AND platform=?", (name, v["platform"]))
    cam = ch[0]["cam"] if ch else None
    channel_url = ch[0]["url"] if ch else v["url"]
    for i, (t, score, gain) in enumerate(peaks, 1):
        if vod_id in _stop_ids:
            raise RuntimeError("cancelado")
        _set(vod_id, status=f"montando corte {i} de {len(peaks)}", progress=0.7 + 0.3 * (i - 1) / len(peaks))
        pad = float(cfg.get("pad") or 0)          # sobra antes e depois (pra puxar mais no editor)
        core0 = max(0, t - cfg["before"])
        start = max(0, core0 - pad)
        cs = core0 - start
        dur = cs + cfg["before"] + cfg["after"] + pad
        hh, mm, ss = t // 3600, t % 3600 // 60, t % 60
        clip_name = f"{name}_vod{vod_id}_{hh:02d}h{mm:02d}m{ss:02d}s"
        h, vpath, thumb = clip_paths(f"vod{vod_id}", clip_name)
        args = []
        for a, u in inputs:  # busca direto no servidor: baixa só esse pedaço
            args += [*a, "-ss", f"{start:.2f}", "-i", u]
        maps = ["-map", "0:v:0", "-map", f"{1 if len(inputs) > 1 else 0}:a:0?"]
        render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, "-t", f"{dur:.2f}", *maps,
                    *render.venc(), *render.AENC, "-movflags", "+faststart", str(h)], timeout=1800)
        prev = db.query("SELECT title, overlay FROM clips WHERE channel_name=? ORDER BY created_at DESC LIMIT 60", (name,))
        ce = cs + cfg["before"] + cfg["after"]
        lines, speech, words = listen(h, cs, ce)   # o que o streamer falou (com o tempo de cada palavra)
        if t in evals and (speech is None or evals[t][0]["known"]):
            q = evals[t][0]
            speech = speech if speech is not None else evals[t][1]
        else:
            q = quality.evaluate(score, speech, t - core0)
        m = meta.make_meta(name, v["platform"], channel_url, [], gain=gain, avoid=[r["title"] for r in prev],
                           speech=speech or [], peak_rel=t - core0, avoid_hooks=[r["overlay"] for r in prev],
                           theme=theme)
        clip_id = db.insert("clips", {
            "channel_id": 0, "channel_name": name, "peak_time": time.time(), "created_at": time.time(),
            "score": q["final"],
            "reasons": " · ".join([f"VOD {hh:02d}:{mm:02d}:{ss:02d}", f"áudio +{gain:.0f} dB"] + q["reasons"]), "file_h": rel(h),
            "platform": v["platform"], "url": channel_url, "cam": cam, "rendering": 1,
            "source": "vod", "vod_id": vod_id, "features": json.dumps(q["features"]) if q["features"] else None,
            "signal_score": q["signal"], "content_score": q["content"], **m,
            **extra_fields(h, cs, ce, t - start, lines, words)})
        after_insert(clip_id)
        log.info("✂ corte %d de %d do VOD de %s pronto", i, len(peaks), name)
    _set(vod_id, status=f"pronto: {len(peaks)} cortes", progress=1)
    log.info("🎬 VOD de %s pronto: %d cortes", name, len(peaks))


def worker():
    while True:
        with _cv:
            while not _pending or len(_running) >= _limit():
                _cv.wait(timeout=5)
            vod_id = _pending.pop(0)
            _running.add(vod_id)
            _mark_queue()
        try:
            if vod_id not in _stop_ids:
                _process(vod_id)
        except Exception as e:
            log.exception("VOD %s", vod_id)
            msg = str(e)
            if "cancelado" in msg:
                _set(vod_id, status="cancelado", error=None)
            else:
                _set(vod_id, status="erro", error=msg[:300])
        finally:
            with _cv:
                _running.discard(vod_id)
                _cv.notify_all()


def start():
    for _ in range(MAX_PARALLEL):          # até 3 juntos; o ajuste "VODs ao mesmo tempo" decide quantos rodam
        threading.Thread(target=worker, daemon=True).start()
    for v in db.query("SELECT id FROM vods WHERE status NOT LIKE 'pronto%' AND status NOT IN ('erro','cancelado')"):
        enqueue(v["id"])
