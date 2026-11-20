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
from . import db, meta, render, settings, sources
from .recorder import clip_paths, rel, render_vertical_for

log = logging.getLogger("vod")
SR = 8000
_q = queue.Queue()
_stop_ids = set()


def enqueue(vod_id):
    _q.put(vod_id)


def cancel(vod_id):
    _stop_ids.add(vod_id)


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
    log.info("🎬 VOD de %s: ouvindo o áudio pra achar os melhores momentos…", name)

    levels = _listen(vod_id, light)
    if len(levels) < 60:
        raise RuntimeError("Não consegui ouvir o áudio do vídeo. Confira se o link abre no navegador e tente de novo.")
    peaks = find_peaks(levels, cfg["min_score"], cfg["cooldown"], int(cfg["vod_max"]))
    if not peaks:
        _set(vod_id, status="pronto: nenhum momento forte achado", progress=1)
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
        start = max(0, t - cfg["before"])
        dur = cfg["before"] + cfg["after"]
        hh, mm, ss = t // 3600, t % 3600 // 60, t % 60
        clip_name = f"{name}_vod{vod_id}_{hh:02d}h{mm:02d}m{ss:02d}s"
        h, vpath, thumb = clip_paths(f"vod{vod_id}", clip_name)
        args = []
        for a, u in inputs:  # busca direto no servidor: baixa só esse pedaço
            args += [*a, "-ss", f"{start:.2f}", "-i", u]
        maps = ["-map", "0:v:0", "-map", f"{1 if len(inputs) > 1 else 0}:a:0?"]
        render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, "-t", f"{dur:.2f}", *maps,
                    *render.venc(), *render.AENC, "-movflags", "+faststart", str(h)], timeout=1800)
        recent = [r["title"] for r in db.query("SELECT title FROM clips WHERE channel_name=? ORDER BY created_at DESC LIMIT 60", (name,))]
        m = meta.make_meta(name, v["platform"], channel_url, [], gain=gain, avoid=recent)
        clip_id = db.insert("clips", {
            "channel_id": 0, "channel_name": name, "peak_time": time.time(), "created_at": time.time(),
            "score": round(min(score, 10.0), 1),
            "reasons": f"VOD {hh:02d}:{mm:02d}:{ss:02d} · áudio +{gain:.0f} dB", "file_h": rel(h),
            "platform": v["platform"], "url": channel_url, "cam": cam, "rendering": 1,
            "source": "vod", "vod_id": vod_id, **m})
        render_vertical_for(clip_id)
        log.info("✂ corte %d de %d do VOD de %s pronto", i, len(peaks), name)
    _set(vod_id, status=f"pronto: {len(peaks)} cortes", progress=1)
    log.info("🎬 VOD de %s pronto: %d cortes", name, len(peaks))


def worker():
    while True:
        vod_id = _q.get()
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


def start():
    threading.Thread(target=worker, daemon=True).start()
    for v in db.query("SELECT id FROM vods WHERE status NOT LIKE 'pronto%' AND status NOT IN ('erro','cancelado')"):
        enqueue(v["id"])
