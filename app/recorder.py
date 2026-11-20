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
from . import db, meta, render, rules, settings, sources, transcribe
from .chat import TwitchChat

log = logging.getLogger("recorder")

# Cortes montados um de cada vez (não disputa o PC com as gravações)
CLIP_POOL = ThreadPoolExecutor(max_workers=1)
SR = 8000  # taxa de amostragem usada para medir o áudio


def clip_paths(channel_id, name):
    d = C.CLIPS_DIR / str(channel_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}_h.mp4", d / f"{name}_v.mp4", d / f"{name}.jpg"


def rel(p):
    return Path(p).relative_to(C.CLIPS_DIR).as_posix()


def render_vertical_for(clip_id):
    """(Re)faz o vertical de um corte a partir do horizontal, com a câmera e o texto atuais."""
    c = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))[0]
    h = C.CLIPS_DIR / c["file_h"]
    v = C.CLIPS_DIR / (c["file_v"] or c["file_h"].replace("_h.mp4", "_v.mp4"))
    thumb = C.CLIPS_DIR / (c["thumb"] or c["file_h"].replace("_h.mp4", ".jpg"))
    tmp = v.with_name(v.stem + ".novo.mp4")
    try:
        rule = rules.for_channel(c["channel_name"])
        wm = rule.get("watermark") if rule else None
        on = c.get("overlay_on") is None or bool(c.get("overlay_on"))
        caption = (c["overlay"] or "") if on else ""
        used = render.make_vertical(h, tmp, thumb, cam=c["cam"], caption=caption,
                                    cap_secs=settings.get("ov_secs"), layout=c.get("layout") or "auto", watermark=wm)
        tmp.replace(v)
        if wm and not c.get("file_hw"):
            # horizontal pra baixar, com a marca d'água (o original fica limpo pra refazer o vertical)
            hw = h.with_name(h.name.replace("_h.mp4", "_hw.mp4"))
            render.add_watermark(h, hw, wm)
            db.update("clips", clip_id, {"file_hw": rel(hw)})
        db.update("clips", clip_id, {"file_v": rel(v), "thumb": rel(thumb), "rendering": 0,
                                     "created_at": time.time(), "layout_used": used, "overlay_applied": caption})
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
        self.segdir = C.SEGMENTS_DIR / str(self.id)
        self.status = "iniciando"
        self.live_since = None
        self.error = ""
        self.score = 0.0
        self.history = deque(maxlen=300)
        self.quality = ""
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
        self.segdir.mkdir(parents=True, exist_ok=True)
        for f in self.segdir.glob("*.ts"):
            f.unlink(missing_ok=True)
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

        self.status = "gravando"
        self.live_since = time.time()
        self.error = ""
        log.info("🔴 %s entrou ao vivo: gravando", self.name)
        try:
            while not self._stop.is_set() and all(p.poll() is None for p in self._procs[-1:]):
                self._tick(final=False)
                self._stop.wait(2)
        finally:
            self._kill()
            logf.close()
            self._tick(final=True)
            for f in self.segdir.glob("*.ts"):
                f.unlink(missing_ok=True)
            if self.chat:
                self.chat.stop()
            self.live_since = None
            self.score = 0.0
            log.info("⚫ %s: parou de gravar (live acabou)", self.name)

    def _tick(self, final):
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

    def _score_second(self, t):
        hist = [self.audio[s] for s in range(t - 600, t - 5) if s in self.audio]
        if len(hist) < 60:
            return None, []
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
                if score >= cfg["min_score"] and t - self.last_peak > cfg["cooldown"]:
                    self.pending = {"peak": t, "score": score, "reasons": reasons, "t0": t}
            elif t - p["t0"] <= 12:
                if score > p["score"]:
                    p.update(peak=t, score=score, reasons=reasons)
            else:
                self._queue_pending()

    def _queue_pending(self):
        p, self.pending = self.pending, None
        self.last_peak = p["peak"]
        cfg = settings.get_all()
        with self._lock:
            self.jobs.append({"start": p["peak"] - cfg["before"], "end": p["peak"] + cfg["after"],
                              "score": p["score"], "reasons": p["reasons"], "peak": p["peak"]})

    # ------------------------------------------------------------ cortes
    def _run_jobs(self, final):
        with self._lock:
            ready = [j for j in self.jobs if final or j["end"] <= self.analyzed_until]
            self.jobs = [j for j in self.jobs if j not in ready]
        for j in ready:
            segs = [(s, p) for s, p, d in self.segments if s < j["end"] and s + d > j["start"] and p.exists()]
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
            start = max(job["start"], segs[0][0])
            render.make_horizontal(["-f", "concat", "-safe", "0", "-i", str(lst)], h,
                                   start - segs[0][0], job["end"] - start)
            cam = (db.query("SELECT cam FROM channels WHERE id=?", (self.id,)) or [{}])[0].get("cam")
            prev = db.query("SELECT title, overlay FROM clips WHERE channel_name=? ORDER BY created_at DESC LIMIT 60", (self.name,))
            gain = max([float(x) for x in __import__("re").findall(r"áudio \+(\d+) dB", " ".join(job["reasons"]))] or [0])
            speech = transcribe.transcribe(h)   # o que o streamer falou no corte
            m = meta.make_meta(self.name, self.platform, self.url, lines, gain=gain, avoid=[r["title"] for r in prev],
                               speech=speech, peak_rel=job["peak"] - start, avoid_hooks=[r["overlay"] for r in prev])
            clip_id = db.insert("clips", {
                "channel_id": self.id, "channel_name": self.name, "peak_time": job["peak"],
                "created_at": time.time(), "score": round(min(job["score"], 10.0), 1),
                "reasons": " · ".join(job["reasons"]) or "pico detectado", "file_h": rel(h),
                "platform": self.platform, "url": self.url, "cam": cam, "rendering": 1, "source": "live", **m})
            render_vertical_for(clip_id)
            log.info("✂ corte pronto: %s (nota %.1f)", name, min(job["score"], 10))
        except Exception:
            log.exception("falha ao gerar corte %s", name)
        finally:
            lst.unlink(missing_ok=True)
            for _, p in segs:
                Path(p).unlink(missing_ok=True)

    def _cleanup(self):
        limit = time.time() - C.BUFFER_MINUTES * 60
        keep = []
        for s, p, d in self.segments:
            if s + d < limit:
                p.unlink(missing_ok=True)
                self.analyzed.discard(p)
            else:
                keep.append((s, p, d))
        self.segments = keep
        for k in [k for k in self.audio if k < limit - 600]:
            del self.audio[k]
        if self.chat:
            self.chat.prune(int(limit) - 600)
