"""
Um ChannelWorker por canal:
  - verifica se o canal está ao vivo
  - grava o vídeo ORIGINAL da live em pedaços (buffer rotativo), sem gravar tela
  - mede o volume do áudio e a velocidade do chat a cada segundo
  - dá uma nota de 0 a 10 pra cada segundo e gera o corte nos picos
"""
import logging
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config as C
import json

from . import db, meta, quality, render, rules, settings, smart, sources, transcribe
from .procs import safe_unlink
from .chat import TwitchChat
from .kickchat import KickChat

log = logging.getLogger("recorder")

# Cortes montados um de cada vez (não disputa o PC com as gravações)
CLIP_POOL = ThreadPoolExecutor(max_workers=1)
# Fila só das suas edições (editar, estilo, câmera, texto...): não espera os cortes automáticos
EDIT_POOL = ThreadPoolExecutor(max_workers=1)
_edit_q = []
_edit_now = [None]
_edit_lock = threading.Lock()


def queue_render(clip_id):
    """Põe o corte na fila das edições (se já estiver esperando, não duplica: ele usa a edição mais nova)."""
    with _edit_lock:
        if clip_id in _edit_q:
            return
        _edit_q.append(clip_id)
    EDIT_POOL.submit(_run_edit, clip_id)


def _run_edit(clip_id):
    with _edit_lock:
        if clip_id in _edit_q:
            _edit_q.remove(clip_id)
        _edit_now[0] = clip_id
    try:
        render_vertical_for(clip_id)
    finally:
        _edit_now[0] = None


def edit_queue():
    with _edit_lock:
        return _edit_now[0], list(_edit_q)


def make_horizontal_for(clip_id):
    """Horizontal pra baixar (com o pedaço escolhido e a marca d'água). Só é feito quando você pede."""
    c = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))[0]
    h = C.CLIPS_DIR / c["file_h"]
    wm = rules.mark_for(c["channel_name"])
    trim = effective_trim(c)
    if not wm and not trim:
        return h
    hw = h.with_name(h.name.replace("_h.mp4", "_hw.mp4"))
    v = C.CLIPS_DIR / c["file_v"] if c.get("file_v") else None
    if c.get("file_hw") and hw.exists() and (not v or not v.exists() or hw.stat().st_mtime >= v.stat().st_mtime):
        return hw                                            # já está feito e atualizado
    tmp_h = hw.with_name(hw.stem + ".novo.mp4")
    render.horizontal_final(h, tmp_h, wm, trim, audio_mode=settings.get("audio_mode"))
    tmp_h.replace(hw)
    db.update("clips", clip_id, {"file_hw": rel(hw)})
    return hw
SR = 8000  # taxa de amostragem usada para medir o áudio


def clip_paths(channel_id, name):
    d = C.CLIPS_DIR / str(channel_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}_h.mp4", d / f"{name}_v.mp4", d / f"{name}.jpg"


def rel(p):
    return Path(p).relative_to(C.CLIPS_DIR).as_posix()


def listen(h, cs, ce):
    """
    Ouve o vídeo guardado (que tem sobra antes e depois). Retorna:
      (frases do vídeo todo, frases só do corte com o tempo contando do começo do corte, palavras) ou (None, None, []).
    """
    r = transcribe.transcribe_words(h)
    if r is None:
        return None, None, []
    lines, words = r
    core = [(max(0.0, s - cs), min(ce, e) - cs, t) for s, e, t in lines if e >= cs and s <= ce]
    return lines, core, words


def extra_fields(h, cs, ce, peak, lines, words):
    """Campos novos do corte: onde está o corte dentro do vídeo guardado, começo/fim esperto e as palavras."""
    _, _, hdur = render.probe(h)
    ce = min(ce, hdur) if hdur else ce
    out = {"core_start": round(cs, 2), "core_end": round(ce, 2), "peak_rel": round(peak, 2) if peak is not None else None,
           "style": settings.get("style"), "words": json.dumps(words) if words else None}
    sw = smart.smart_window(lines, peak, hdur or ce, max_len=max(20.0, ce - cs)) if lines else None
    if sw:
        out.update(smart_start=sw[0], smart_end=sw[1])
    return out


def after_insert(clip_id):
    """Depois de criar o corte: avisa se for repetido e monta o vertical."""
    try:
        other = smart.find_dup(clip_id)
        if other:
            log.info("♻ Esse corte parece repetido de outro que já existe (o mesmo momento). Marquei no painel.")
    except Exception:
        log.debug("não deu pra checar repetido", exc_info=True)
    render_vertical_for(clip_id)


def effective_trim(c):
    """Pedaço do vídeo guardado que vira o corte: o que você escolheu no editor > começo/fim esperto > o corte normal."""
    if c.get("trim_start") is not None or c.get("trim_end") is not None:
        return c.get("trim_start"), c.get("trim_end")
    if (c.get("style") == "dinamico") and c.get("smart_start") is not None:
        return c["smart_start"], c["smart_end"]
    if c.get("core_start") is not None:
        return c["core_start"], c["core_end"]
    return None


def render_vertical_for(clip_id):
    """(Re)faz o vertical de um corte a partir do horizontal, com a câmera e o texto atuais."""
    c = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))[0]
    h = C.CLIPS_DIR / c["file_h"]
    v = C.CLIPS_DIR / (c["file_v"] or c["file_h"].replace("_h.mp4", "_v.mp4"))
    thumb = C.CLIPS_DIR / (c["thumb"] or c["file_h"].replace("_h.mp4", ".jpg"))
    tmp = v.with_name(v.stem + ".novo.mp4")
    try:
        wm = rules.mark_for(c["channel_name"])   # marca d'água (texto) ou Lower (arquivo) do campeonato
        rule = rules.for_channel(c["channel_name"])
        if rule and rule.get("lower") and not wm:
            log.warning("⚠ %s: falta enviar o Lower do campeonato. O corte saiu sem ele; envie no painel e refaça.", c["channel_name"])
        on = c.get("overlay_on") is None or bool(c.get("overlay_on"))
        caption = (c["overlay"] or "") if on else ""
        trim = effective_trim(c)
        dyn = c.get("style") == "dinamico"
        subs_on = bool(c.get("subs_on"))     # legenda só se você ligar no editor (o dinâmico não legenda)
        zoom_on = bool(c["zoom_on"]) if c.get("zoom_on") is not None else dyn
        words = json.loads(c["words"]) if c.get("words") else None
        if (subs_on or zoom_on) and words is None and transcribe.available():
            r = transcribe.transcribe_words(h)            # corte antigo: ouve agora pra ter as palavras
            if r is not None:
                words = r[1]
                db.update("clips", clip_id, {"words": json.dumps(words)})
        zooms = []
        if zoom_on:
            _, _, hdur = render.probe(h)
            ts, te = (trim[0] or 0.0, trim[1] or hdur) if trim else (0.0, hdur)
            zooms = smart.zoom_moments(words, smart.group_words(words), ts, te, c.get("peak_rel"))
        cap_win = (c.get("cap_start"), c.get("cap_end")) if c.get("cap_start") is not None or c.get("cap_end") is not None else None
        wm_pos = (c["wm_x"], c["wm_y"]) if c.get("wm_x") is not None and c.get("wm_y") is not None else None
        used = render.make_vertical(h, tmp, thumb, cam=c["cam"], caption=caption,
                                    cap_secs=settings.get("ov_secs"), layout=c.get("layout") or "auto", watermark=wm,
                                    trim=trim, cap_win=cap_win, cap_y=c.get("cap_y"), wm_pos=wm_pos,
                                    audio_mode=settings.get("audio_mode"),
                                    subs=words if subs_on else None, sub_y=c.get("sub_y"), zooms=zooms)
        tmp.replace(v)
        # o horizontal pra baixar agora só é feito quando você clica em "⬇ Horizontal" (metade do trabalho a cada edição)
        if c.get("file_hw"):
            safe_unlink(C.CLIPS_DIR / c["file_hw"])
            db.update("clips", clip_id, {"file_hw": None})
        db.update("clips", clip_id, {"audio_info": getattr(render.make_vertical, "last_audio", None)})
        found = getattr(render.make_vertical, "last_cam", None)
        if found and not c["cam"]:
            db.update("clips", clip_id, {"cam": found})
            log.info("📷 %s: achei a webcam sozinho no corte (dá pra ajustar em 📐 Formato / câmera)", c["channel_name"])
        db.update("clips", clip_id, {"file_v": rel(v), "thumb": rel(thumb), "rendering": 0,
                                     "created_at": time.time(), "layout_used": used, "overlay_applied": caption,
                                     "style_used": ("legenda " if subs_on and words else "") + ("zoom" if zooms else "")})
        if used == "full" and (c.get("layout") or "auto") == "auto":
            log.info("🎥 %s: o streamer estava em tela cheia na câmera, então o corte saiu na tela toda (vertical)", c["channel_name"])
    except Exception as e:
        log.exception("falha ao refazer o vertical")
        db.update("clips", clip_id, {"rendering": 0, "warn": f"Falhou ao refazer: {str(e)[:200]}"})
        tmp.unlink(missing_ok=True)


class ChannelWorker(threading.Thread):
    def __init__(self, ch: dict):
        super().__init__(daemon=True)
        self.id = ch["id"]
        self.url = ch["url"]
        self.name = ch["name"]
        self.platform = ch["platform"]
        self.basedir = C.SEGMENTS_DIR / str(self.id)
        self.segdir = self.basedir
        self.status = "iniciando"
        self.live_since = None
        self.error = ""
        self.score = 0.0
        self.history = deque(maxlen=300)
        self.quality = ""
        self.theme, self._theme_at = "gta", 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._procs = []
        self._reset_state()

    # ------------------------------------------------------------ controle
    def _reset_state(self):
        self.audio = {}
        self.segments = []
        self.analyzed = set()
        self.analyzed_until = 0.0
        self.scored_until = 0
        self.pending = None
        self.last_peak = 0.0
        self.jobs = []
        self.chat = None
        self.speech = {}                 # segundo -> (nota da fala, frase)
        self.speech_until = 0.0          # até onde a fala já foi ouvida
        self.speech_on = False
        self.speech_lag = 0.0
        self.stats = {"momentos": 0, "cortes": 0, "descartados": 0, "pela_fala": 0}

    def stop(self):
        self._stop.set()
        self._kill()

    def request_manual_clip(self):
        if self.status != "gravando":
            return False
        now = time.time()
        dur = settings.get_all()["dur"]
        with self._lock:
            self.jobs.append({"start": now - (dur - 5), "end": now + 5, "score": 10.0,
                              "reasons": ["corte manual"], "peak": now})
        return True

    def latest_frame(self, out):
        """Salva um quadro recente da live (pra marcar a câmera)."""
        segs = [s for s in self.segments if s[1].exists()]
        if not segs:
            return False
        _, path, dur = segs[-1]
        Path(out).unlink(missing_ok=True)
        render.frame_jpg(path, out, t=max(0.0, dur - 1.5))
        return Path(out).exists()

    def info(self):
        return {
            "status": self.status, "live_since": self.live_since, "error": self.error,
            "score": round(min(self.score, 10.0), 1), "history": list(self.history)[::5],
            "buffer_min": round(sum(d for _, _, d in self.segments) / 60, 1),
            "chat": bool(self.chat), "quality": self.quality,
            "chat_status": getattr(self.chat, "status", "conectado") if self.chat else None,
            "speech": ("ouvindo" if self.speech_lag < 90 else f"atrasado {int(self.speech_lag)}s") if self.speech_on else None,
            "stats": dict(self.stats),
        }

    # ------------------------------------------------------------ loop principal
    def run(self):
        while not self._stop.is_set():
            try:
                src = self._check_live()
                if src:
                    self._record(src)
                    self._stop.wait(10)
                else:
                    if self.status != "offline":
                        log.info("⚫ %s está offline. Fico verificando a cada minuto e começo a gravar quando entrar ao vivo.", self.name)
                    self.status = "offline"
                    self._stop.wait(C.CHECK_INTERVAL)
            except Exception as e:
                log.exception("canal %s", self.name)
                log.warning("⚠ %s: erro (%s). Tento de novo em 30 segundos.", self.name, str(e)[:120])
                self.error = str(e)[:300]
                self.status = "erro"
                self._stop.wait(30)

    def _check_live(self):
        if self.status not in ("offline", "erro"):
            self.status = "verificando"
        if self.platform == "twitch":
            try:
                from streamlink import Streamlink
                if Streamlink().streams(self.url):
                    return "streamlink"
            except Exception:
                pass
            return None
        return sources.is_live(self.url)  # Kick / YouTube: info do yt-dlp

    def _kill(self):
        for p in self._procs:
            if p.poll() is None:
                p.terminate()
        for p in self._procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        self._procs = []

    def _record(self, src):
        self._reset_state()
        # cada gravação numa pasta nova: se sobrou arquivo preso de antes, não atrapalha
        self.basedir.mkdir(parents=True, exist_ok=True)
        for old in list(self.basedir.iterdir()):
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
            else:
                safe_unlink(old)
        self.segdir = self.basedir / f"g{int(time.time())}"
        self.segdir.mkdir(parents=True, exist_ok=True)
        out = ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
               "-f", "segment", "-segment_time", str(C.SEGMENT_SECONDS),
               "-reset_timestamps", "1", "-strftime", "1", str(self.segdir / "%Y%m%d%H%M%S.ts")]
        logf = open(self.segdir / "ffmpeg.log", "ab")
        if src == "streamlink":
            sl = subprocess.Popen([sys.executable, "-m", "streamlink", "--stdout", "--retry-open", "3",
                                   "--twitch-low-latency", self.url, C.QUALITY],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=render.NO_WINDOW)
            ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *out],
                                  stdin=sl.stdout, stderr=logf, creationflags=render.NO_WINDOW)
            sl.stdout.close()
            self._procs = [sl, ff]
            self.quality = "original"
        else:
            inputs = sources.ffmpeg_inputs(src)
            args = []
            for a, u in inputs:
                args += [*a, "-i", u]
            maps = ["-map", "0:v:0", "-map", f"{1 if len(inputs) > 1 else 0}:a:0?"]
            ff = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, *maps, *out[4:]],
                                  stderr=logf, creationflags=render.NO_WINDOW)
            self._procs = [ff]
            self.quality = f"{src['height']}p" if src.get("height") else "original"

        if self.platform == "twitch":
            self.chat = TwitchChat(self.name)
            self.chat.start()
        elif self.platform == "kick":
            self.chat = KickChat(self.name)
            self.chat.start()

        self._update_theme(src if isinstance(src, dict) else None)
        self.status = "gravando"
        self.live_since = time.time()
        self.error = ""
        log.info("🔴 %s entrou ao vivo: gravando", self.name)
        if settings.get("live_speech") and transcribe.available():
            self.speech_on = True
            threading.Thread(target=self._speech_loop, daemon=True).start()
        try:
            while not self._stop.is_set() and all(p.poll() is None for p in self._procs[-1:]):
                self._tick(final=False)
                self._stop.wait(2)
        finally:
            self._kill()
            logf.close()
            self._tick(final=True)
            for f in self.segdir.glob("*.ts"):
                safe_unlink(f)
            if self.chat:
                self.chat.stop()
            self.live_since = None
            self.score = 0.0
            log.info("⚫ %s: parou de gravar (live acabou)", self.name)

    def _update_theme(self, info=None):
        """GTA ou react, pelo título/categoria da live (o streamer pode trocar no meio)."""
        self._theme_at = time.time()
        try:
            info = info or sources.resolve(self.url, "worst")
            new = sources.guess_theme(info)
            if new != self.theme:
                log.info("🎮 %s: tema da live agora é %s", self.name, "GTA" if new == "gta" else "react/outros")
            self.theme = new
        except Exception:
            pass

    def _tick(self, final):
        if not final and time.time() - self._theme_at > 600:
            self._update_theme()
        self._analyze_new(final)
        self._score()
        if final and self.pending:
            self._queue_pending()
        self._run_jobs(final)
        self._cleanup()

    # ------------------------------------------------------------ análise
    def _analyze_new(self, final):
        files = sorted(self.segdir.glob("*.ts"), key=lambda p: p.stem)
        if not final:
            files = files[:-1]  # o último ainda está sendo escrito
        for p in files:
            if p in self.analyzed:
                continue
            self.analyzed.add(p)
            start = time.mktime(time.strptime(p.stem, "%Y%m%d%H%M%S"))
            r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-vn", "-ac", "1",
                                "-ar", str(SR), "-f", "s16le", "-"], capture_output=True,
                               creationflags=render.NO_WINDOW)
            a = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
            dur = len(a) / SR if len(a) else C.SEGMENT_SECONDS
            for i in range(len(a) // SR):
                chunk = a[i * SR:(i + 1) * SR]
                self.audio[int(start) + i] = float(20 * np.log10(np.sqrt(np.mean(chunk ** 2)) + 1e-6))
            self.segments.append((start, p, dur))
            self.analyzed_until = max(self.analyzed_until, start + dur)

    # ------------------------------------------------------------ ouvir a fala da live
    SPEECH_WIN = 30      # ouve de 30 em 30 s, com 10 s repetidos pra não cortar palavra no meio

    def _speech_loop(self):
        """Fica ouvindo o que o streamer fala. Reação/descoberta/bug/risada viram momento, mesmo sem grito."""
        live_started = self.live_since
        while not self._stop.is_set() and self.live_since == live_started and self.status == "gravando":
            segs = [(s, p, d) for s, p, d in list(self.segments) if p.exists()]
            if not segs:
                self._stop.wait(3)
                continue
            end = segs[-1][0] + segs[-1][2]
            start = max(self.speech_until - 10, segs[0][0], end - 120)    # atrasado demais: pula pro recente
            if end - start < self.SPEECH_WIN - 10 and end - self.speech_until < 20:
                self._stop.wait(3)
                continue
            use = [(s, p) for s, p, d in segs if s + d > start and s < start + self.SPEECH_WIN]
            if not use:
                self._stop.wait(3)
                continue
            wav = self.segdir / f"_fala_{int(start)}.wav"
            lst = self.segdir / f"_fala_{int(start)}.txt"
            try:
                lst.write_text("".join(f"file '{Path(p).resolve().as_posix()}'\n" for _, p in use), encoding="utf-8")
                t0 = use[0][0]
                render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-ss", f"{max(0.0, start - t0):.2f}", "-t", str(self.SPEECH_WIN), "-vn", "-ac", "1", "-ar", "16000",
                            str(wav)], timeout=120)
                lines = transcribe.transcribe(wav)
                if lines is None:                         # o reconhecimento de fala parou de funcionar
                    self.speech_on = False
                    return
                for s, e, text in lines:
                    sc = quality.speech_moment(text)
                    if sc:
                        sec = int(start + s)
                        if sc > self.speech.get(sec, (0, ""))[0]:
                            self.speech[sec] = (sc, text)
                self.speech_until = start + self.SPEECH_WIN
                self.speech_lag = max(0.0, time.time() - self.speech_until)
            except Exception:
                log.debug("falha ao ouvir a fala", exc_info=True)
                self.speech_until = start + self.SPEECH_WIN
            finally:
                safe_unlink(wav)
                safe_unlink(lst)

    def _score_second(self, t):
        hist = [self.audio[s] for s in range(t - 600, t - 5) if s in self.audio]
        if len(hist) < 60:
            return None, []
        base_score, reasons = self._score_signal(t, hist)
        best = max((self.speech[s] for s in range(t, t + 3) if s in self.speech), default=None, key=lambda x: x[0])
        if best and best[0] >= base_score:
            from . import likes
            liked = likes.match(best[1])
            tag = f"⭐ assunto que você curte ({', '.join(liked[:2])}): " if liked else "🗣 falou: "
            return best[0], reasons + [f"{tag}“{best[1].strip()[:50]}”"]
        return base_score, reasons

    def _score_signal(self, t, hist):
        hist = np.array(hist)
        med = float(np.median(hist))
        mad = float(np.median(np.abs(hist - med))) * 1.4826 + 1.0
        loud = max((self.audio[s] for s in range(t, t + 3) if s in self.audio), default=med)
        a_score = max(0.0, ((loud - med) / mad - 1) * 2.2)
        reasons = [f"áudio +{loud - med:.0f} dB"] if a_score >= 3 else []
        if not self.chat:
            return a_score, reasons
        cur_m, cur_h = self.chat.window(t + 3, t + 18)
        base_m, _ = self.chat.window(t - 600, t - 30)
        base = max(base_m / 38, 2.0)
        ratio = cur_m / base
        c_score = max(0.0, (ratio - 1) * 2.5 + (cur_h / max(cur_m, 1)) * 4 * min(cur_m / 5, 1))
        if ratio >= 1.8:
            reasons.append(f"chat {ratio:.1f}x mais rápido")
        if cur_h >= 3:
            reasons.append(f"{cur_h} msgs de hype/risada")
        return max(c_score, a_score * 0.8) + 0.3 * min(a_score, c_score), reasons

    def _score(self):
        limit = int(self.analyzed_until) - 3
        if self.chat:
            limit = min(limit, int(time.time()) - 18)
        if self.speech_on and self.speech_lag < 90:
            # espera a fala ser ouvida (se o PC estiver atrasado demais, segue só com áudio e chat)
            limit = min(limit, int(self.speech_until) - 3) if self.speech_until else min(limit, int(self.analyzed_until) - 60)
        if not self.scored_until and self.segments:
            self.scored_until = int(self.segments[0][0])
        cfg = settings.get_all()
        for t in range(self.scored_until, limit):
            score, reasons = self._score_second(t)
            self.scored_until = t + 1
            if score is None:
                continue
            self.score = score
            self.history.append(round(min(score, 10.0), 1))
            p = self.pending
            if p is None:
                if score >= cfg["min_score"] and t - self.last_peak > cfg["gap"]:
                    self.pending = {"peak": t, "score": score, "reasons": reasons, "t0": t}
            elif t - p["t0"] <= 12:
                if score > p["score"]:
                    p.update(peak=t, score=score, reasons=reasons)
            else:
                self._queue_pending()

    def _queue_pending(self):
        p, self.pending = self.pending, None
        self.last_peak = p["peak"]
        self.stats["momentos"] += 1
        if any(r.startswith("🗣") for r in p["reasons"]):
            self.stats["pela_fala"] += 1
        cfg = settings.get_all()
        with self._lock:
            self.jobs.append({"start": p["peak"] - cfg["before"], "end": p["peak"] + cfg["after"],
                              "score": p["score"], "reasons": p["reasons"], "peak": p["peak"]})

    # ------------------------------------------------------------ cortes
    def _run_jobs(self, final):
        pad = float(settings.get("pad") or 0)     # sobra antes e depois (pra puxar mais no editor)
        with self._lock:
            ready = [j for j in self.jobs if final or j["end"] + pad <= self.analyzed_until]
            self.jobs = [j for j in self.jobs if j not in ready]
        for j in ready:
            j["pad"] = pad
            segs = [(s, p) for s, p, d in self.segments if s < j["end"] + pad and s + d > j["start"] - pad and p.exists()]
            if not segs:
                continue
            tmp = C.CLIPS_DIR / str(self.id) / "tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            copied = []
            for s, p in segs:
                dst = tmp / f"{int(j['peak'])}_{p.name}"
                shutil.copy2(p, dst)
                copied.append((s, dst))
            lines = self.chat.between(j["start"], j["end"] + 15) if self.chat else []
            log.info("✂ %s: momento forte (%s). Montando o corte…", self.name, " · ".join(j["reasons"]) or "pico")
            CLIP_POOL.submit(self._render, j, copied, lines)

    def _render(self, job, segs, lines):
        name = f"{self.name}_{datetime.fromtimestamp(job['peak']).strftime('%Y%m%d_%H%M%S')}"
        h, v, thumb = clip_paths(self.id, name)
        lst = h.with_suffix(".txt")
        try:
            lst.write_text("".join(f"file '{Path(p).resolve().as_posix()}'\n" for _, p in segs), encoding="utf-8")
            pad = job.get("pad", 0)
            start = max(job["start"] - pad, segs[0][0])
            render.make_horizontal(["-f", "concat", "-safe", "0", "-i", str(lst)], h,
                                   start - segs[0][0], job["end"] + pad - start)
            cs, ce = max(0.0, job["start"] - start), job["end"] - start     # onde está o corte dentro do vídeo guardado
            cam = (db.query("SELECT cam FROM channels WHERE id=?", (self.id,)) or [{}])[0].get("cam")
            prev = db.query("SELECT title, overlay FROM clips WHERE channel_name=? ORDER BY created_at DESC LIMIT 60", (self.name,))
            gain = max([float(x) for x in __import__("re").findall(r"áudio \+(\d+) dB", " ".join(job["reasons"]))] or [0])
            spoken, speech, words = listen(h, cs, ce)   # o que o streamer falou (só o pedaço do corte conta pra nota)
            peak_rel = job["peak"] - start - cs
            q = quality.evaluate(job["score"], speech, peak_rel)
            manual = "corte manual" in job["reasons"]
            thr = float(settings.get("discard_below") or 0)
            if q["known"] and not manual and thr > 0 and q["final"] < thr:
                log.info("🗑 %s: momento descartado (nota %.1f, abaixo de %.1f). %s", self.name, q["final"], thr,
                         " ".join(q["reasons"]))
                safe_unlink(h)
                self.stats["descartados"] += 1
                return
            m = meta.make_meta(self.name, self.platform, self.url, lines, gain=gain, avoid=[r["title"] for r in prev],
                               speech=speech or [], peak_rel=peak_rel, avoid_hooks=[r["overlay"] for r in prev],
                               theme=self.theme)
            clip_id = db.insert("clips", {
                "channel_id": self.id, "channel_name": self.name, "peak_time": job["peak"],
                "created_at": time.time(), "score": q["final"] if not manual else 10.0,
                "reasons": " · ".join(list(job["reasons"]) + q["reasons"]) or "pico detectado", "file_h": rel(h),
                "platform": self.platform, "url": self.url, "cam": cam, "rendering": 1, "source": "live",
                "features": json.dumps(q["features"]) if q["features"] else None,
                "signal_score": q["signal"], "content_score": q["content"], **m,
                **extra_fields(h, cs, ce, job["peak"] - start, spoken, words)})
            self.stats["cortes"] += 1
            after_insert(clip_id)
            log.info("✂ corte pronto: %s (nota %.1f)", name, q["final"])
        except Exception:
            log.exception("falha ao gerar corte %s", name)
        finally:
            lst.unlink(missing_ok=True)
            for _, p in segs:
                safe_unlink(p)

    def _cleanup(self):
        limit = time.time() - C.BUFFER_MINUTES * 60
        keep = []
        for s, p, d in self.segments:
            if s + d < limit:
                safe_unlink(p)
                self.analyzed.discard(p)
            else:
                keep.append((s, p, d))
        self.segments = keep
        for k in [k for k in self.audio if k < limit - 600]:
            del self.audio[k]
        for k in [k for k in self.speech if k < limit - 600]:
            self.speech.pop(k, None)
        if self.chat:
            self.chat.prune(int(limit) - 600)
