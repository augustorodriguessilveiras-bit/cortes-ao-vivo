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


live_count = lambda: 0       # o painel troca por quantas lives estão gravando agora


def _limit():
    try:
        n = max(1, min(MAX_PARALLEL, int(settings.get("vod_parallel"))))
    except Exception:
        n = 2
    try:
        if live_count() > 0:      # tem live gravando: 1 VOD por vez, pra live e a fala dela não atrasarem
            n = 1
    except Exception:
        pass
    return n


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


def _listen(vod_id, info, keep_audio=None, share=0.7, start=0.0, dur=None):
    """
    Lê o áudio do VOD inteiro e devolve o volume (dB) de cada segundo.
    keep_audio: se passado, guarda também o áudio (leve) nesse arquivo, pra depois ouvir a fala sem baixar de novo.
    """
    total = float(dur or 0) or max(0.0, float(info.get("duration") or 0) - start)
    (args, url), *rest = sources.ffmpeg_inputs(info)
    if rest:  # áudio separado (YouTube): ouve só ele
        args, url = rest[-1]
    extra = (["-vn", "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "48k", "-y", str(keep_audio)]
             if keep_audio else [])
    cut = (["-ss", f"{start:.2f}"] if start else [])
    lim = (["-t", f"{dur:.2f}"] if dur else [])
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, *cut, "-i", url, *lim, "-vn",
                          "-ac", "1", "-ar", str(SR), "-f", "s16le", "-", *extra],
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
                     progress=min(share, share * len(db_s) / total))
        p.wait(timeout=120)                      # deixa terminar de gravar o áudio guardado
    finally:
        if p.poll() is None:
            p.kill()
    return np.array(db_s)


# ------------------------------------------------------------ ouvir a fala do VOD inteiro
def _cache(vod_id, kind):
    from . import config as C
    d = C.DATA_DIR / "vod_fala"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"vod{vod_id}_{kind}"


def forget_cache(vod_id):
    for k in ("niveis.npy", "audio.m4a", "fala.json"):
        p = _cache(vod_id, k)
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


CHUNK = 120.0


def _speech_full(vod_id, audio, total, p0=0.4, p1=0.75):
    """
    Ouve tudo o que o streamer fala no VOD, de 2 em 2 minutos. Guarda o que já ouviu (se o programa fechar,
    continua de onde parou). Retorna [(início, fim, texto)] com o tempo do VOD, ou None se não der.
    """
    import json as _json
    cache = _cache(vod_id, "fala.json")
    try:
        data = _json.loads(cache.read_text(encoding="utf-8"))
    except Exception:
        data = {"upto": 0.0, "lines": [], "done": False}
    if data.get("done"):
        return [tuple(x) for x in data["lines"]]
    if not audio.exists():
        return None
    total = total or render.probe(audio)[2] or 0
    t = float(data.get("upto") or 0)
    tmp = _cache(vod_id, "pedaco.wav")
    try:
        while t < total - 1:
            if vod_id in _stop_ids:
                raise RuntimeError("cancelado")
            _set(vod_id, status=f"ouvindo tudo o que ele fala ({int(t // 60)} de {int(total // 60)} min)",
                 progress=p0 + (p1 - p0) * t / max(1.0, total))
            render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(audio),
                        "-t", f"{CHUNK + 4:.2f}", "-ac", "1", "-ar", "16000", str(tmp)], timeout=300)
            lines = transcribe.transcribe(tmp)
            if lines is None:
                return None
            last = t + CHUNK >= total - 1
            for s, e, text in lines:
                if s < CHUNK or last:                 # os 4 s a mais só servem pra não cortar palavra
                    data["lines"].append([round(t + s, 2), round(t + e, 2), text])
            t += CHUNK
            data["upto"] = t
            cache.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        data["done"] = True
        cache.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return [tuple(x) for x in data["lines"]]
    finally:
        tmp.unlink(missing_ok=True)


def _speech_peaks(lines, min_score, gap):
    """Momentos achados pela fala (reação, descoberta, bug, risada, assunto que você curte): [(segundo, nota, 0)]."""
    cands = []
    for s, e, text in lines:
        sc = quality.speech_moment(text)
        if sc >= min_score:
            cands.append((int(s), sc, 0.0))
    picked = []
    for c in sorted(cands, key=lambda c: -c[1]):
        if all(abs(c[0] - p[0]) > gap for p in picked):
            picked.append(c)
    return picked


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


def _hms(t):
    t = int(t or 0)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


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
    # trecho escolhido por você (de/até): só essa parte do VOD é ouvida e cortada
    rs = float(v.get("range_start") or 0)
    re_ = float(v["range_end"]) if v.get("range_end") else None
    if re_ and light.get("duration"):
        re_ = min(re_, float(light["duration"]))
    rdur = (re_ - rs) if re_ else None
    ranged = bool(rs or re_)
    log.info("🎬 VOD de %s: ouvindo o áudio pra achar os melhores momentos%s…", name,
             f" (do {_hms(rs)} até o {_hms(re_)})" if ranged else "")

    can_listen = transcribe.available()
    full = can_listen and bool(cfg.get("vod_listen_all"))
    niv, aud = _cache(vod_id, "niveis.npy"), _cache(vod_id, "audio.m4a")
    if niv.exists() and (not full or aud.exists() or _cache(vod_id, "fala.json").exists()):
        levels = np.load(niv)                     # já ouvido antes do programa fechar
    else:
        levels = _listen(vod_id, light, keep_audio=aud if full else None, share=0.4 if full else 0.7, start=rs, dur=rdur)
        if len(levels) >= 60:
            np.save(niv, levels)
    if len(levels) < 60:
        raise RuntimeError("Não consegui ouvir o áudio do vídeo. Confira se o link abre no navegador e tente de novo.")
    vod_max = int(cfg["vod_max"])
    if ranged:   # trecho: sem limite fixo, sai quantos momentos bons tiver (no máximo 1 a cada "intervalo")
        vod_max = max(1, int(len(levels) / max(15, cfg["cooldown"])))
    # com o reconhecimento de fala: pega mais candidatos e fica só com os melhores (o que ele fala conta mais)
    peaks = find_peaks(levels, cfg["min_score"], cfg["cooldown"], int(vod_max * 2.5) if can_listen else vod_max)
    if len(levels) < 120:          # trecho curto: o momento mais alto
        peaks = [(int(np.argmax(levels)), 5.0, 0.0)]
    all_lines = None
    if full:
        log.info("🎬 VOD de %s: ouvindo tudo o que ele fala (acha reação sem grito; leva um tempo)…", name)
        all_lines = _speech_full(vod_id, aud, float(rdur or light.get("duration") or len(levels)))
        if all_lines is None:
            log.warning("⚠ VOD de %s: não deu pra ouvir a fala do vídeo inteiro; seguindo só pelos picos de áudio.", name)
        else:
            aud.unlink(missing_ok=True)           # já ouviu tudo: o áudio guardado não precisa mais
            sp = _speech_peaks(all_lines, cfg["min_score"], cfg["cooldown"])
            known = [p for p in peaks]
            added = 0
            for c in sp:                          # junta os momentos da fala com os do áudio (sem repetir)
                if all(abs(c[0] - p[0]) > cfg["cooldown"] for p in known):
                    known.append(c)
                    added += 1
            peaks = known
            log.info("🎬 VOD de %s: ouvi tudo. %d momentos a mais achados pela fala.", name, added)
    if not peaks:
        _set(vod_id, status="pronto: nenhum momento forte achado", progress=1)
        forget_cache(vod_id)
        return
    evals = {}
    if all_lines is not None:
        thr = float(cfg.get("discard_below") or 0)
        for t, score, gain in peaks:
            start = max(0, t - cfg["before"])
            end = start + cfg["before"] + cfg["after"]
            speech = [(max(0.0, s - start), min(end, e) - start, x) for s, e, x in all_lines if e >= start and s <= end]
            evals[t] = (quality.evaluate(score, speech, t - start), speech)
        ok = [p for p in peaks if thr <= 0 or evals[p[0]][0]["final"] >= thr]
        if ranged and not ok and peaks:
            ok = [max(peaks, key=lambda p: evals[p[0]][0]["final"])]
        dropped = len(peaks) - len(ok)
        peaks = sorted(ok, key=lambda p: -evals[p[0]][0]["final"])[:vod_max]
        log.info("🎬 VOD de %s: %d momentos bons escolhidos (%d descartados por nota baixa)", name, len(peaks), dropped)
        if not peaks:
            _set(vod_id, status="pronto: nenhum momento bom o bastante", progress=1)
            forget_cache(vod_id)
            return
    elif can_listen:
        thr = float(cfg.get("discard_below") or 0)
        for i, (t, score, gain) in enumerate(peaks, 1):
            if vod_id in _stop_ids:
                raise RuntimeError("cancelado")
            _set(vod_id, status=f"ouvindo o que ele fala nos momentos ({i} de {len(peaks)})",
                 progress=0.7 + 0.1 * (i - 1) / len(peaks))
            start = max(0, t - cfg["before"])
            speech = _speech_at(light, start + rs, cfg["before"] + cfg["after"], vod_id, i)
            evals[t] = (quality.evaluate(score, speech, t - start), speech)
        ok = [p for p in peaks if not evals[p[0]][0]["known"] or thr <= 0 or evals[p[0]][0]["final"] >= thr]
        dropped = len(peaks) - len(ok)
        peaks = sorted(ok, key=lambda p: -evals[p[0]][0]["final"])[:vod_max]
        log.info("🎬 VOD de %s: %d momentos bons escolhidos (%d descartados por nota baixa)", name, len(peaks), dropped)
        if not peaks:
            _set(vod_id, status="pronto: nenhum momento bom o bastante", progress=1)
            forget_cache(vod_id)
            return
    peaks.sort()
    if rs:             # volta pro tempo do VOD (o áudio ouvido começou no início do trecho)
        evals = {t + int(rs): e for t, e in evals.items()}
        peaks = [(t + int(rs), s, g) for t, s, g in peaks]
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
        if db.query("SELECT id FROM clips WHERE vod_id=? AND file_h=?", (vod_id, rel(h))):
            continue                     # já feito antes do programa fechar: não repete
        args = []
        for a, u in inputs:  # busca direto no servidor: baixa só esse pedaço
            args += [*a, "-ss", f"{start:.2f}", "-i", u]
        maps = ["-map", "0:v:0", "-map", f"{1 if len(inputs) > 1 else 0}:a:0?"]
        render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, "-t", f"{dur:.2f}", *maps,
                    *render.venc("master"), *render.AENC, "-movflags", "+faststart", str(h)], timeout=1800)
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
            "reasons": " · ".join([f"VOD {hh:02d}:{mm:02d}:{ss:02d}"] + ([f"áudio +{gain:.0f} dB"] if gain else ["achado pela fala"])
                                  + q["reasons"]), "file_h": rel(h),
            "platform": v["platform"], "url": channel_url, "cam": cam, "rendering": 1,
            "source": "vod", "vod_id": vod_id, "features": json.dumps(q["features"]) if q["features"] else None,
            "signal_score": q["signal"], "content_score": q["content"], **m,
            **extra_fields(h, cs, ce, t - start, lines, words)})
        after_insert(clip_id)
        log.info("✂ corte %d de %d do VOD de %s pronto", i, len(peaks), name)
    _set(vod_id, status=f"pronto: {len(peaks)} cortes", progress=1)
    forget_cache(vod_id)
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
