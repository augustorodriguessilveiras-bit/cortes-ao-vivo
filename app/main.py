import base64
import json
import logging
import secrets
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as C
import urllib.parse

import re

from . import compile as compilado
from . import likes
from . import db, drive, meta, procs, quality, render, rules, settings, sources, transcribe, version, vod
from .recorder import CLIP_POOL, ChannelWorker, edit_queue, make_horizontal_for, queue_render, after_insert, clip_paths, effective_trim, extra_fields, listen, rel, render_vertical_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
for _n in ("httpx", "urllib3", "streamlink"):
    logging.getLogger(_n).setLevel(logging.WARNING)
workers: dict[int, ChannelWorker] = {}

# "O que está acontecendo": guarda as últimas mensagens do programa pra mostrar no painel
from collections import deque
ACTIVITY = deque(maxlen=40)


class _Activity(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.INFO and record.name in ("recorder", "vod", "render", "painel"):
            ACTIVITY.append({"t": record.created, "msg": record.getMessage(), "level": record.levelname})


logging.getLogger().addHandler(_Activity())
plog = logging.getLogger("painel")


def start_worker(ch):
    w = ChannelWorker(ch)
    workers[ch["id"]] = w
    w.start()


@asynccontextmanager
async def lifespan(app):
    procs.tie_children_to_me()   # gravadores fecham junto com o programa (Windows)
    # cortes que estavam sendo montados/refeitos quando o programa fechou: refaz agora (antes ficavam pela metade)
    for c in db.query("SELECT id, file_h, file_v FROM clips WHERE COALESCE(files_deleted,0)=0 AND "
                      "(rendering=1 OR (file_v IS NULL AND file_h IS NOT NULL))"):
        if c["file_h"] and (C.CLIPS_DIR / c["file_h"]).exists():
            db.update("clips", c["id"], {"rendering": 1})
            queue_render(c["id"])
        else:
            db.update("clips", c["id"], {"rendering": 0, "warn": "O vídeo desse corte se perdeu quando o programa fechou. Pode excluir."})
    # cortes de versões antigas: o texto que está no vídeo é o texto salvo
    db.execute("UPDATE clips SET overlay_applied=COALESCE(overlay,'') WHERE overlay_applied IS NULL")
    CLIP_POOL.submit(render.encoder)  # descobre a placa de vídeo logo no começo
    try:
        likes.rebuild()
    except Exception:
        plog.debug("não deu pra calcular os assuntos curtidos", exc_info=True)
    try:
        n = quality.backfill()
        if n:
            plog.info("🧠 %d cortes que você já tinha aprovado/postado passaram a contar pro aprendizado.", n)
    except Exception:
        plog.debug("backfill do aprendizado falhou", exc_info=True)
    for ch in db.query("SELECT * FROM channels"):
        start_worker(ch)
    vod.start()
    version.start_check()
    print("\n  Cortes ao Vivo rodando! Painel: http://localhost:8000")
    print("  Aqui embaixo aparece o que o programa estiver fazendo (gravando, cortes criados...).\n", flush=True)
    yield
    for w in workers.values():
        w.stop()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def auth(request: Request, call_next):
    if C.PANEL_PASSWORD:
        ok = False
        h = request.headers.get("authorization", "")
        if h.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(h[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, C.PANEL_USER) and secrets.compare_digest(pw, C.PANEL_PASSWORD)
            except Exception:
                pass
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="cortes"'})
    return await call_next(request)


class LinkIn(BaseModel):
    url: str


class CamIn(BaseModel):
    cam: dict | None = None
    remember: bool = True
    layout: str | None = None   # auto / cam / full / game


class ClipIn(BaseModel):
    title: str | None = None
    descr: str | None = None
    tags: str | None = None
    overlay: str | None = None
    status: str | None = None
    yt_tags: str | None = None
    overlay_on: bool | None = None


# ------------------------------------------------------------ estado geral
@app.get("/api/state")
def state():
    counts = {r["channel_id"]: r["n"] for r in db.query("SELECT channel_id, COUNT(*) n FROM clips GROUP BY channel_id")}
    chans = []
    for ch in db.query("SELECT * FROM channels ORDER BY added_at"):
        w = workers.get(ch["id"])
        chans.append({**ch, **(w.info() if w else {}), "clips": counts.get(ch["id"], 0)})
    vods = db.query("SELECT v.*, (SELECT COUNT(*) FROM clips c WHERE c.vod_id=v.id) AS clips FROM vods v ORDER BY added_at DESC LIMIT 30")
    disk = shutil.disk_usage(C.DATA_DIR)
    enc = render._enc[0] if render._enc else "verificando…"
    return {"channels": chans, "vods": vods, "settings": settings.get_all(), "activity": list(ACTIVITY)[::-1][:15],
            "version": version.status(), "learning": quality.stats(), "speech": transcribe.status(),
            "disk_free_gb": round(disk.free / 1e9, 1), "encoder": enc}


@app.post("/api/speech/test")
def speech_test():
    """Testa o reconhecimento de fala (na 1ª vez baixa o modelo, ~150 MB)."""
    if not transcribe.available():
        raise HTTPException(400, "O reconhecimento de fala não está instalado. Feche e abra o INICIAR.bat de novo; "
                                 "se aparecer o aviso de erro na janela preta, mande um print pro Claude.")
    transcribe.retry()

    def run():
        wav = C.DATA_DIR / "_teste_fala.wav"
        try:
            render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=16000:cl=mono", "-t", "2", str(wav)], timeout=60)
            r = transcribe.transcribe(wav)
            if r is None:
                plog.warning("⚠ O reconhecimento de fala deu erro: %s", transcribe.status()["error"][:200])
            else:
                plog.info("🗣 Reconhecimento de fala funcionando!")
        finally:
            procs.safe_unlink(wav)
    MANUAL_POOL.submit(run)
    plog.info("🗣 Testando o reconhecimento de fala (na 1ª vez baixa ~150 MB, pode levar uns minutos)…")
    return {"ok": True}


@app.post("/api/settings")
def save_settings(body: dict):
    out = settings.update(body)
    if "vod_parallel" in body:
        vod.wake()
    return out


@app.post("/api/vods/{vid}/front")
def vod_front(vid: int):
    if not vod.to_front(vid):
        raise HTTPException(400, "Esse VOD não está mais na fila (já começou ou terminou).")
    plog.info("⏫ VOD passou na frente da fila.")
    return {"ok": True}


# ------------------------------------------------------------ canais e VODs (um campo só)
@app.post("/api/links")
def add_link(body: LinkIn):
    url, name, platform, kind = sources.parse_link(body.url)
    if kind == "vod":
        vid = db.insert("vods", {"url": url, "name": name, "platform": platform, "added_at": time.time()})
        vod.enqueue(vid)
        plog.info("🎬 VOD adicionado (%s). Ele entra na fila e é cortado sozinho.", name)
        return {"kind": "vod", "id": vid}
    if db.query("SELECT id FROM channels WHERE url=?", (url,)):
        raise HTTPException(400, "Esse canal já está na lista")
    cid = db.add_channel(url, name, platform)
    start_worker(db.query("SELECT * FROM channels WHERE id=?", (cid,))[0])
    plog.info("➕ Canal %s (%s) adicionado. Verificando se está ao vivo…", name, platform)
    return {"kind": "live", "id": cid}


@app.delete("/api/channels/{cid}")
def remove_channel(cid: int):
    w = workers.pop(cid, None)
    if w:
        w.stop()
    db.execute("DELETE FROM channels WHERE id=?", (cid,))
    shutil.rmtree(C.SEGMENTS_DIR / str(cid), ignore_errors=True)
    return {"ok": True}


@app.post("/api/channels/{cid}/clip")
def clip_now(cid: int):
    w = workers.get(cid)
    if not w or not w.request_manual_clip():
        raise HTTPException(400, "O canal não está gravando agora")
    return {"ok": True}


@app.get("/api/channels/{cid}/frame")
def channel_frame(cid: int):
    w = workers.get(cid)
    out = C.DATA_DIR / f"quadro_{cid}.jpg"
    if not w or w.status != "gravando":
        raise HTTPException(400, "Esse canal não está gravando agora. A imagem aparece quando ele estiver ao vivo.")
    fresh = out.exists() and time.time() - out.stat().st_mtime < 4
    if not fresh and not w.latest_frame(out):
        raise HTTPException(400, "Ainda não tem imagem da live. Espere uns 20 segundos depois que começar a gravar.")
    return FileResponse(out, headers={"Cache-Control": "max-age=30"})


@app.post("/api/channels/{cid}/cam")
def channel_cam(cid: int, body: CamIn):
    db.update("channels", cid, {"cam": body.cam})
    name = (db.query("SELECT name FROM channels WHERE id=?", (cid,)) or [{"name": "?"}])[0]["name"]
    plog.info("📷 %s: %s", name, "posição da webcam salva. Os próximos cortes saem com a câmera em cima." if body.cam else "sem câmera. Os cortes saem só com a gameplay.")
    return {"ok": True}


@app.delete("/api/vods/{vid}")
def remove_vod(vid: int):
    vod.cancel(vid)
    db.execute("UPDATE vods SET status='cancelado' WHERE id=? AND status NOT LIKE 'pronto%'", (vid,))
    return {"ok": True}


@app.delete("/api/vods/{vid}/forget")
def forget_vod(vid: int):
    vod.cancel(vid)
    vod.forget_cache(vid)
    db.execute("DELETE FROM vods WHERE id=?", (vid,))
    return {"ok": True}


# ------------------------------------------------------------ cortes
@app.get("/api/clips")
def list_clips(status: str = "", channel: str = "", limit: int = 300):
    sql, params = "SELECT * FROM clips WHERE 1=1", []
    if status:
        sql += " AND status=?"
        params.append(status)
    if channel:
        sql += " AND channel_name=?"
        params.append(channel)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.query(sql, params)
    now_id, q_ids = edit_queue()
    for c in rows:
        c["rules"] = rules.public(c["channel_name"])
        c["ov_secs"] = settings.get("ov_secs")   # cortes feitos antes das tags do YouTube ganham as tags agora
        if not c.get("yt_tags"):
            c["yt_tags"] = meta.youtube_tags(c["channel_name"], c.get("platform") or "", c.get("cat") or "geral", c.get("subject"))
            db.update("clips", c["id"], {"yt_tags": c["yt_tags"]})
        if c.get("rendering"):                      # posição na fila das edições
            c["queue_pos"] = 0 if c["id"] == now_id else (q_ids.index(c["id"]) + 1 if c["id"] in q_ids else None)
        et = effective_trim(c)                       # pedaço que vira o corte (pro editor)
        c["eff_ts"], c["eff_te"] = (et if et else (None, None))
        c["has_words"] = bool(c.get("words"))
        c.pop("words", None)
        c.pop("features", None)
        c["posted_on"] = _js(c.get("posted_on"))
        c["views"] = _js(c.get("views"))
        if c.get("dup_of"):
            o = db.query("SELECT id, title, status FROM clips WHERE id=?", (c["dup_of"],))
            c["dup"] = o[0] if o else None
    return rows


def _js(v):
    try:
        return json.loads(v) if v else {}
    except Exception:
        return {}


PLATS = ("tiktok", "reels", "shorts")


class StyleIn(BaseModel):
    style: str


@app.post("/api/clips/{clip_id}/style")
def set_style(clip_id: int, body: StyleIn):
    """Padrão (como sempre foi) ou Dinâmico (zoom na reação e começo/fim esperto, sem legenda)."""
    c = _clip(clip_id)
    if body.style not in ("padrao", "dinamico"):
        raise HTTPException(400, "Estilo inválido")
    db.update("clips", clip_id, {"style": body.style, "trim_start": None, "trim_end": None, "subs_on": None,
                                 "zoom_on": None, "rendering": 1, "warn": None})
    queue_render(clip_id)
    if body.style == "dinamico" and not c.get("words") and not transcribe.available():
        return {"ok": True, "aviso": "Sem o reconhecimento de fala instalado, o dinâmico só consegue dar o zoom no momento forte."}
    return {"ok": True}


class PostedIn(BaseModel):
    platform: str
    on: bool = True
    views: int | None = None


@app.post("/api/clips/{clip_id}/posted")
def set_posted(clip_id: int, body: PostedIn):
    """Marca em qual rede você postou (TikTok, Reels, Shorts) e quantas visualizações teve."""
    c = _clip(clip_id)
    if body.platform not in PLATS:
        raise HTTPException(400, "Plataforma inválida")
    posted, views = _js(c.get("posted_on")), _js(c.get("views"))
    data = {}
    if body.views is not None:
        views[body.platform] = max(0, int(body.views))
        posted.setdefault(body.platform, time.time())
        data["views"] = json.dumps(views)
    elif body.on:
        posted[body.platform] = time.time()
    else:
        posted.pop(body.platform, None)
        views.pop(body.platform, None)
        data["views"] = json.dumps(views) if views else None
    data["posted_on"] = json.dumps(posted) if posted else None
    db.update("clips", clip_id, data)
    if posted:
        quality.record(clip_id, c.get("features"), 1)        # postou: esse é bom
        threading.Thread(target=likes.rebuild, daemon=True).start()
    if body.views is not None:
        quality.train()                                       # aprende com as views
    res = {"ok": True, "posted_on": posted, "views": views, "freed_mb": 0}
    if all(p in posted for p in PLATS) and c["status"] != "postado":
        res["freed_mb"] = edit_clip(clip_id, ClipIn(status="postado"))["freed_mb"]
        res["status"] = "postado"
    return res


@app.get("/api/likes")
def likes_get():
    d = likes.load()
    show = d.get("show") or {}
    return {"terms": [{"t": t, "show": show.get(t, t)} for t in (d.get("terms") or {})],
            "bad": [{"t": t, "show": show.get(t, t)} for t in (d.get("bad") or {})], "n_bad": d.get("n_bad", 0),
            "blocked": d.get("blocked", []), "n": d.get("n", 0),
            "min": likes.MIN_CLIPS}


class TermIn(BaseModel):
    term: str


@app.post("/api/likes/block")
def likes_block(body: TermIn):
    likes.block(body.term)
    return likes_get()


@app.post("/api/likes/reset")
def likes_reset():
    likes.unblock_all()
    return likes_get()


@app.get("/api/insights")
def insights():
    """O que dá mais visualização: por tipo de momento, por streamer e por estilo."""
    rows = [r for r in db.query("SELECT channel_name, cat, theme, style, views, core_start, core_end, trim_start, trim_end "
                                "FROM clips WHERE views IS NOT NULL")
            if quality.total_views(r["views"]) > 0]

    def group(key):
        g = {}
        for r in rows:
            k = key(r)
            if k:
                g.setdefault(k, []).append(quality.total_views(r["views"]))
        return sorted(([k, round(sum(v) / len(v)), len(v)] for k, v in g.items()), key=lambda x: -x[1])
    cats = {"policia": "Polícia", "fail": "Fail / deu ruim", "epico": "Épico", "susto": "Susto", "engracado": "Engraçado",
            "descoberta": "Descoberta / bug", "geral": "Outros"}
    plat = {}
    for r in rows:
        for p, n in _js(r["views"]).items():
            plat.setdefault(p, []).append(int(n or 0))
    return {"n": len(rows),
            "by_cat": group(lambda r: cats.get(r["cat"] or "geral", r["cat"])),
            "by_channel": group(lambda r: rules.display(r["channel_name"])),
            "by_style": group(lambda r: "Dinâmico" if r["style"] == "dinamico" else "Padrão"),
            "by_theme": group(lambda r: "React" if r["theme"] == "react" else "GTA"),
            "by_platform": sorted(([{"tiktok": "TikTok", "reels": "Reels", "shorts": "Shorts"}.get(k, k),
                                    round(sum(v) / len(v)), len(v)] for k, v in plat.items()), key=lambda x: -x[1])}


# ------------------------------------------------------------ compilado (YouTube, deitado)
@app.get("/api/compile")
def compile_state(channel: str = "", days: int = 7):
    cands = compilado.candidates(channel, max(1, min(60, days)))
    return {"candidates": [{"id": c["id"], "title": c["title"], "channel_name": c["channel_name"], "score": c["score"],
                            "views": c["total_views"], "thumb": c.get("thumb"), "status": c["status"],
                            "created_at": c["created_at"]} for c in cands],
            "items": db.query("SELECT * FROM compilations ORDER BY created_at DESC LIMIT 20")}


class CompileIn(BaseModel):
    clip_ids: list[int]
    title: str | None = None


@app.post("/api/compile")
def compile_start(body: CompileIn):
    try:
        cid = compilado.start(body.clip_ids[:40], body.title)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": cid}


@app.delete("/api/compile/{cid}")
def compile_delete(cid: int):
    compilado.remove(cid)
    return {"ok": True}


def _clip(clip_id):
    rows = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not rows:
        raise HTTPException(404, "Corte não encontrado")
    return rows[0]


@app.post("/api/clips/{clip_id}")
def edit_clip(clip_id: int, body: ClipIn):
    c = _clip(clip_id)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    freed = 0
    if data.get("status"):
        data["status_at"] = time.time()
        if data["status"] in ("aprovado", "postado"):
            quality.record(clip_id, c.get("features"), 1)      # aprende: esse você gostou
            db.update("clips", clip_id, {"status": data["status"]})
            threading.Thread(target=likes.rebuild, daemon=True).start()   # assuntos que você curte
        if data["status"] == "postado" and settings.get("posted_cleanup") and not c.get("files_deleted"):
            freed = _free_files(c, keep_thumb=True)      # já foi postado: libera o espaço do vídeo
            data["files_deleted"] = 1
            plog.info("📤 %s: marcado como postado; vídeo apagado (%s MB liberados)", c["channel_name"], round(freed / 1e6))
    if data:
        db.update("clips", clip_id, data)
    return {"ok": True, "freed_mb": round(freed / 1e6, 1)}


@app.post("/api/clips/{clip_id}/newtitle")
def new_title(clip_id: int):
    c = _clip(clip_id)
    import re as _re
    gain = max([float(x) for x in _re.findall(r"áudio \+(\d+) dB", c["reasons"] or "")] or [0])
    raw, n_subject = meta.titles_for(c["channel_name"], c["cat"] or "geral", c["subject"], gain, c.get("theme") or "gta")
    titles = [rules.title_with_tag(c["channel_name"], t) for t in raw]
    recent = [r["title"] for r in db.query("SELECT title FROM clips WHERE channel_name=? AND id<>? ORDER BY created_at DESC LIMIT 60",
                                           (c["channel_name"], clip_id))]
    title = meta.pick_title(titles, max(0, n_subject), recent, current=c["title"])
    db.update("clips", clip_id, {"title": title, "title_idx": titles.index(title)})
    return {"title": title}


@app.post("/api/clips/{clip_id}/rerender")
def rerender(clip_id: int, body: CamIn | None = None):
    c = _clip(clip_id)
    data = {"rendering": 1, "warn": None}
    if body is not None and body.layout in ("auto", "cam", "full", "game"):
        data["layout"] = body.layout
    if body is not None:
        data["cam"] = body.cam
        if body.remember:
            if c["channel_id"]:
                db.update("channels", c["channel_id"], {"cam": body.cam})
            else:
                for ch in db.query("SELECT id FROM channels WHERE name=? AND platform=?", (c["channel_name"], c["platform"])):
                    db.update("channels", ch["id"], {"cam": body.cam})
    db.update("clips", clip_id, data)
    queue_render(clip_id)
    return {"ok": True}


def _gain(c):
    import re as _re
    return max([float(x) for x in _re.findall(r"áudio \+(\d+) dB", c["reasons"] or "")] or [0])


_hook_tried: dict[int, set] = {}   # textos já sugeridos pra cada corte (não repetir no "Outro texto")


@app.post("/api/clips/{clip_id}/newhook")
def new_hook(clip_id: int):
    """Sugere outro texto pra faixa, diferente do atual e dos últimos usados nesse streamer."""
    import random
    c = _clip(clip_id)
    subject = c["subject"] or meta.find_subject([c["transcript"] or ""] * 2)
    disp = rules.display(c["channel_name"])
    theme = c.get("theme") or "gta"
    first, rest = meta.hooks_for(c["channel_name"], c["cat"] or "geral", subject if theme == "gta" else None, _gain(c), "", theme)
    quotes = rules.adapt(c["channel_name"], meta.transcript_quotes(c["transcript"], disp), "hook")
    recent = {r["overlay"] for r in db.query("SELECT overlay FROM clips WHERE channel_name=? AND id<>? ORDER BY created_at DESC LIMIT 60",
                                             (c["channel_name"], clip_id))}
    recent.add(c["overlay"])
    tried = _hook_tried.setdefault(clip_id, set())
    tried.add(c["overlay"])
    if len([h for h in quotes + first + rest if h not in recent | tried]) == 0:
        tried.clear()                       # já mostrou todas: começa a volta de novo
        tried.add(c["overlay"])
    avoid = recent | tried
    related = [h for h in quotes + first if h not in avoid]
    others = [h for h in rest if h not in avoid]
    # metade das vezes puxa algo ligado ao corte (fala/assunto), quando tiver; senão, varia entre os outros
    pool = related if related and (not others or random.random() < 0.6) else (others or related or rest)
    hook = random.choice(pool)
    tried.add(hook)
    db.update("clips", clip_id, {"overlay": hook})
    return {"overlay": hook}


class ThemeIn(BaseModel):
    theme: str


@app.post("/api/clips/{clip_id}/theme")
def set_theme(clip_id: int, body: ThemeIn):
    """Troca o tema do corte (GTA ou react/outros) e refaz título, descrição, hashtags, tags e texto."""
    if body.theme not in ("gta", "react"):
        raise HTTPException(400, "Tema inválido")
    c = _clip(clip_id)
    speech = [(0.0, 0.0, c["transcript"])] if c.get("transcript") else []
    prev = db.query("SELECT title, overlay FROM clips WHERE channel_name=? AND id<>? ORDER BY created_at DESC LIMIT 60",
                    (c["channel_name"], clip_id))
    m = meta.make_meta(c["channel_name"], c.get("platform") or "", c.get("url") or "", [], gain=_gain(c),
                       avoid=[r["title"] for r in prev], speech=speech, avoid_hooks=[r["overlay"] for r in prev],
                       theme=body.theme)
    data = {k: m[k] for k in ("title", "title_idx", "descr", "tags", "yt_tags", "theme", "subject")}
    if (c.get("overlay_on") is None or c.get("overlay_on")) and m.get("overlay"):
        data["overlay"] = m["overlay"]
    db.update("clips", clip_id, data)
    return data


@app.post("/api/clips/{clip_id}/yttags")
def regen_tags(clip_id: int):
    c = _clip(clip_id)
    subject = c["subject"] or meta.find_subject([c["transcript"] or ""] * 2)
    tags = meta.youtube_tags(c["channel_name"], c.get("platform") or "", c.get("cat") or "geral", subject, c.get("theme") or "gta")
    db.update("clips", clip_id, {"yt_tags": tags})
    return {"yt_tags": tags}


class EditIn(BaseModel):
    trim_start: float | None = None
    trim_end: float | None = None
    cap_start: float | None = None
    cap_end: float | None = None
    cap_y: float | None = None
    wm_x: float | None = None
    wm_y: float | None = None
    overlay: str | None = None
    overlay_on: bool | None = None
    subs_on: bool | None = None
    zoom_on: bool | None = None
    sub_y: float | None = None


@app.post("/api/clips/{clip_id}/edit")
def edit_clip_video(clip_id: int, body: EditIn):
    """Salva o que foi feito no editor (corte manual, tempo e posição do texto, posição da marca d'água) e refaz o vídeo."""
    c = _clip(clip_id)
    data = body.model_dump()
    if data["overlay"] is None:
        data.pop("overlay")
    if data["overlay_on"] is None:
        data.pop("overlay_on")
    data.update({"rendering": 1, "warn": None})
    db.update("clips", clip_id, data)
    queue_render(clip_id)
    plog.info("✂ %s: refazendo o corte com as suas edições…", c["channel_name"])
    return {"ok": True}


# ------------------------------------------------------------ Lower dos campeonatos
def _rerender_channel(key):
    """Refaz os cortes do canal (pra entrar o Lower novo)."""
    n = 0
    for c in db.query("SELECT id, channel_name FROM clips WHERE rendering=0"):
        if rules.key_for(c["channel_name"]) == key:
            db.update("clips", c["id"], {"rendering": 1})
            queue_render(c["id"])
            n += 1
    return n


def _save_lower(key, path, original_name):
    for old in rules.LOWERS_DIR.glob(f"{key}.*"):
        if old != path:
            old.unlink(missing_ok=True)
    n = _rerender_channel(key)
    plog.info("🖼 Lower de %s salvo (%s). Refazendo %d corte(s) com ele…", rules.RULES[key]["label"], original_name, n)
    return {"ok": True, "file": original_name, "rerendering": n}


@app.get("/api/rules/{key}/lower")
def get_lower(key: str):
    f = rules.lower_file(key)
    if not f:
        raise HTTPException(404, "Ainda não tem Lower pra esse canal")
    return FileResponse(f)


@app.get("/api/rules/{key}/lower_preview")
def lower_preview(key: str):
    """Lower já sem o fundo e recortado (PNG), pra prévia no painel e no editor."""
    f = rules.lower_file(key)
    if not f:
        raise HTTPException(404, "Ainda não tem Lower pra esse canal")
    out = rules.LOWERS_DIR / f"_previa_{key}.png"
    if not out.exists() or out.stat().st_mtime < f.stat().st_mtime:
        render.lower_preview_png(f, out)
    return FileResponse(out, headers={"Cache-Control": "max-age=3600"})


@app.post("/api/rules/{key}/lower")
async def upload_lower(key: str, request: Request):
    """Recebe o arquivo do Lower (imagem PNG/JPG ou vídeo MP4/MOV/WEBM) enviado pelo painel."""
    if key not in rules.RULES or not rules.RULES[key].get("lower"):
        raise HTTPException(400, "Esse canal não usa Lower")
    name = urllib.parse.unquote(request.headers.get("x-filename", "lower.png"))
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in rules.IMG_EXT + rules.VID_EXT:
        raise HTTPException(400, f"Formato {ext or '?'} não serve. Envie PNG, JPG, MP4, MOV ou WEBM.")
    data = await request.body()
    out = rules.LOWERS_DIR / f"{key}.new{ext}"
    out.write_bytes(data)
    final = rules.LOWERS_DIR / f"{key}{ext}"
    out.replace(final)
    return _save_lower(key, final, name)


@app.post("/api/rules/{key}/lower_link")
def lower_from_link(key: str, body: LinkIn):
    """Baixa o Lower de um link público do Google Drive (pasta ou arquivo)."""
    if key not in rules.RULES or not rules.RULES[key].get("lower"):
        raise HTTPException(400, "Esse canal não usa Lower")
    try:
        kind, fid = drive.parse(body.url)
        name = ""
        if kind == "folder":
            entries = drive.list_folder(fid)
            for _ in range(2):   # entra em subpastas (ex: "Lower - Luanz7")
                files = [e for e in entries if not e[2]]
                if files or not any(e[2] for e in entries):
                    break
                sub = next((e for e in entries if e[2] and "lower" in e[1].lower()), None) or next(e for e in entries if e[2])
                entries = drive.list_folder(sub[0])
            ok_ext = rules.IMG_EXT + rules.VID_EXT
            usable = [e for e in entries if not e[2] and e[1].lower().endswith(ok_ext)]
            if not usable:
                names = ", ".join(e[1] for e in entries) or "nenhum arquivo"
                raise ValueError(f"Não achei imagem ou vídeo do Lower nessa pasta (achei: {names}). "
                                 "Baixe o arquivo certo e use \"Enviar arquivo\".")
            pick = sorted(usable, key=lambda e: (0 if e[1].lower().endswith(".png") else 1, "lower" not in e[1].lower()))[0]
            fid, name = pick[0], pick[1]
        out, real_name = drive.download(fid, rules.LOWERS_DIR, f"{key}.new")
        if out.suffix.lower() not in rules.IMG_EXT + rules.VID_EXT:
            out.unlink(missing_ok=True)
            raise ValueError(f"O arquivo do Drive ({real_name or name}) não é imagem nem vídeo. Use \"Enviar arquivo\".")
        final = rules.LOWERS_DIR / f"{key}{out.suffix.lower()}"
        out.replace(final)
        return _save_lower(key, final, real_name or name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Não consegui baixar do Drive: {e}")


# ------------------------------------------------------------ corte enviado por você
UP_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".ts", ".flv")
PLATFORM_URL = {"kick": "https://kick.com/{n}", "twitch": "https://www.twitch.tv/{n}", "youtube": "https://www.youtube.com/@{n}"}


def _process_upload(raw, name, platform, theme):
    """Transforma o vídeo enviado num corte igual aos automáticos (roda em segundo plano)."""
    import json as _json
    stamp = time.strftime("%Y%m%d_%H%M%S")
    h, _, _ = clip_paths("enviados", f"{name}_enviado_{stamp}")
    clip_id = None
    try:
        vw, vh, dur = render.probe(raw)
        render.make_horizontal(["-i", str(raw)], h, 0, dur)        # deixa num formato padrão (mp4)
        lines, speech, words = listen(h, 0.0, dur)
        q = quality.evaluate(5.0, speech, dur * 0.5, dur)
        ch = db.query("SELECT * FROM channels WHERE name=?", (name,))
        url = ch[0]["url"] if ch else PLATFORM_URL.get(platform, "https://kick.com/{n}").format(n=name)
        cam = ch[0]["cam"] if ch else None
        prev = db.query("SELECT title, overlay FROM clips WHERE channel_name=? ORDER BY created_at DESC LIMIT 60", (name,))
        m = meta.make_meta(name, platform, url, [], speech=speech or [], peak_rel=dur * 0.5,
                           avoid=[r["title"] for r in prev], avoid_hooks=[r["overlay"] for r in prev], theme=theme)
        clip_id = db.insert("clips", {
            "channel_id": 0, "channel_name": name, "peak_time": time.time(), "created_at": time.time(),
            "score": q["final"], "reasons": " · ".join(["📤 enviado por você"] + q["reasons"]), "file_h": rel(h),
            "platform": platform, "url": url, "cam": cam, "rendering": 1, "source": "enviado",
            # vídeo que já veio em pé: só encaixa no 9:16 (tela cheia)
            "layout": "full" if vh / max(1, vw) > 1.2 else "auto",
            "features": _json.dumps(q["features"]) if q["features"] else None,
            "signal_score": q["signal"], "content_score": q["content"], **m,
            **extra_fields(h, 0.0, dur, None, lines, words)})
        after_insert(clip_id)
        plog.info("📤 Seu corte de %s está pronto no painel.", name)
    except Exception as e:
        plog.warning("⚠ Não deu pra montar o corte enviado (%s).", str(e)[:150])
        if clip_id:
            db.update("clips", clip_id, {"rendering": 0, "warn": f"Falhou ao montar: {str(e)[:200]}"})
    finally:
        procs.safe_unlink(raw)


# ------------------------------------------------------------ trecho de um VOD (você diz o tempo)
# fila própria pros cortes que você pede (trecho de VOD e corte enviado): não esperam os VODs nem as lives
from concurrent.futures import ThreadPoolExecutor
MANUAL_POOL = ThreadPoolExecutor(max_workers=1)
def parse_time(t):
    """'3:13:00', '3h13', '3h13m05s', '13:20' (min:seg) ou segundos -> segundos."""
    t = (t or "").strip().lower().replace(" ", "").replace(",", ".")
    if not t:
        raise ValueError
    t = re.sub(r"h(\d+)$", r"h\1m", t)          # "3h13" = 3 horas e 13 minutos
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m(?:in)?)?(?:(\d+(?:\.\d+)?)s?)?", t)
    if m and any(m.groups()) and ("h" in t or "m" in t or "s" in t):
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)
    parts = t.split(":")
    if not all(re.fullmatch(r"\d+(?:\.\d+)?", p) for p in parts) or len(parts) > 3:
        raise ValueError
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def _fmt_t(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _clip_from_file(h, cs, ce, peak, name, platform, ch_url, cam, theme, label):
    """Cria o corte a partir de um vídeo já baixado (com sobra). cs/ce: onde está o corte dentro dele."""
    import json as _json
    spoken, speech, words = listen(h, cs, ce)
    if peak is None:
        peak = render.loudest_second(h, cs, ce - cs)          # pro zoom do estilo dinâmico
    q = quality.evaluate(5.0, speech, (peak - cs) if peak is not None else (ce - cs) / 2, ce - cs)
    prev = db.query("SELECT title, overlay FROM clips WHERE channel_name=? ORDER BY created_at DESC LIMIT 60", (name,))
    m = meta.make_meta(name, platform, ch_url, [], speech=speech or [],
                       peak_rel=(peak - cs) if peak is not None else None,
                       avoid=[r["title"] for r in prev], avoid_hooks=[r["overlay"] for r in prev], theme=theme)
    ex = extra_fields(h, cs, ce, peak, None, words)          # sem "começo/fim esperto": o tempo foi você que escolheu
    clip_id = db.insert("clips", {
        "channel_id": 0, "channel_name": name, "peak_time": time.time(), "created_at": time.time(),
        "score": q["final"], "reasons": " · ".join([label] + q["reasons"]),
        "file_h": rel(h), "platform": platform, "url": ch_url, "cam": cam, "rendering": 1,
        "source": "trecho", "features": _json.dumps(q["features"]) if q["features"] else None,
        "signal_score": q["signal"], "content_score": q["content"], **m, **ex})
    try:
        after_insert(clip_id)
    except Exception as e:
        db.update("clips", clip_id, {"rendering": 0, "warn": f"Falhou ao montar: {str(e)[:200]}"})
        raise
    return clip_id


def _pick_moments(levels, n, length):
    """Os n segundos mais fortes do trecho, longe um do outro (cada um vira um corte)."""
    if not levels:
        return []
    sm = [max(levels[max(0, i - 1): i + 2]) for i in range(len(levels))]
    order = sorted(range(len(sm)), key=lambda i: -sm[i])
    out = []
    for i in order:
        if all(abs(i - o) >= length for o in out):         # um corte não repete pedaço do outro
            out.append(i)
        if len(out) >= n:
            break
    return sorted(out)


def _process_vodclip(url, a, b, theme_in, count=1):
    """Baixa só o pedaço escolhido do VOD (com a sobra antes e depois) e monta 1 corte, ou até 3 dentro dele."""
    h = None
    try:
        url, name, platform, _ = sources.parse_link(url)
        info = sources.resolve(url, "best")
        total = float(info.get("duration") or 0)
        if total and a >= total:
            raise RuntimeError(f"esse VOD tem só {_fmt_t(total)}, e o início ({_fmt_t(a)}) passa disso")
        if total:
            b = min(b, total)
        if name in ("kick", "twitch", "youtube"):
            name = (info.get("uploader_id") or info.get("channel") or info.get("uploader") or name).lower().replace(" ", "")
        name = re.sub(r"[^a-z0-9_]", "", name.lower()) or "vod"
        theme = theme_in if theme_in in ("gta", "react") else sources.guess_theme(info)
        pad = float(settings.get("pad") or 0)
        start = max(0.0, a - pad)
        end = min(total, b + pad) if total else b + pad
        cs, ce = a - start, b - start
        h, _, _ = clip_paths("trechos", f"{name}_{_fmt_t(a).replace(':', 'h', 1).replace(':', 'm')}s_{int(time.time())}")
        args = []
        inputs = sources.ffmpeg_inputs(info)
        for ar, u in inputs:                         # busca direto no servidor: baixa só esse pedaço
            args += [*ar, "-ss", f"{start:.2f}", "-i", u]
        maps = ["-map", "0:v:0", "-map", f"{1 if len(inputs) > 1 else 0}:a:0?"]
        render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, "-t", f"{end - start:.2f}", *maps,
                    *render.venc(), *render.AENC, "-movflags", "+faststart", str(h)], timeout=3600)
        _, _, hdur = render.probe(h)
        if hdur < 2:
            raise RuntimeError("o pedaço baixado veio vazio")
        ce = min(ce, hdur)
        ch = db.query("SELECT * FROM channels WHERE name=?", (name,))
        ch_url = ch[0]["url"] if ch else PLATFORM_URL.get(platform, "https://kick.com/{n}").format(n=name)
        cam = ch[0]["cam"] if ch else None
        label = f"✂ trecho escolhido por você: {_fmt_t(a)} até {_fmt_t(b)}"
        cfg = settings.get_all()
        length = float(cfg["dur"])
        if count <= 1 or ce - cs < length * 1.6:
            # 1 corte: o trecho todo (o vídeo baixado passa a ser o do corte)
            hh, h = h, None
            _clip_from_file(hh, cs, ce, None, name, platform, ch_url, cam, theme, label)
            plog.info("✂ Seu trecho do VOD de %s (%s até %s) está pronto no painel.", name, _fmt_t(a), _fmt_t(b))
            return
        # até 3 cortes: os momentos mais fortes dentro do trecho, cada um do tamanho do "Duração do corte"
        moments = _pick_moments(render.second_levels(h, cs, ce - cs), count, length)
        wins, prev_end = [], cs
        for sec in moments:
            p = cs + sec + 0.5
            ws = max(prev_end, min(max(cs, p - cfg["before"]), ce - length))
            if ws + length > ce + 0.5:           # não cabe sem repetir pedaço do anterior
                continue
            wins.append((p, ws, ws + length))
            prev_end = ws + length
        made = 0
        for k, (p, ws, we) in enumerate(wins, 1):
            s0, e0 = max(0.0, ws - pad), min(hdur, we + pad)
            hk, _, _ = clip_paths("trechos", f"{h.stem.removesuffix('_h')}_{k}")
            render.make_horizontal(["-i", str(h)], hk, s0, e0 - s0)
            when = f"{_fmt_t(start + ws)} até {_fmt_t(start + we)}"
            _clip_from_file(hk, ws - s0, we - s0, p - s0, name, platform, ch_url, cam, theme,
                            f"{label} · corte {k} de {len(wins)} ({when})")
            made += 1
        plog.info("✂ %d cortes do seu trecho do VOD de %s (%s até %s) prontos no painel.", made, name, _fmt_t(a), _fmt_t(b))
    except Exception as e:
        plog.warning("⚠ Não deu pra cortar o trecho do VOD (%s).", str(e)[:200])
    finally:
        if h is not None:
            procs.safe_unlink(h)        # o pedaço grande baixado (os cortes têm o vídeo deles)


class VodClipIn(BaseModel):
    url: str
    start: str
    end: str
    theme: str = "auto"
    count: int = 1


@app.post("/api/vodclip")
def vod_clip(body: VodClipIn):
    try:
        a, b = parse_time(body.start), parse_time(body.end)
    except ValueError:
        raise HTTPException(400, "Não entendi o tempo. Escreva assim: 3:13:00 (horas:minutos:segundos).")
    if b <= a:
        raise HTTPException(400, "O fim tem que ser depois do começo.")
    if b - a < 3:
        raise HTTPException(400, "O trecho ficou curto demais (menos de 3 segundos).")
    many = body.count != 1
    if not many and b - a > 15 * 60:
        raise HTTPException(400, "Trecho muito longo pra 1 corte só (máximo 15 minutos). Pra um pedaço grande, "
                                 "escolha \"Vários cortes\" que o programa acha os melhores momentos dentro dele.")
    if many and b - a < 120:
        raise HTTPException(400, "Pra \"Vários cortes\", o trecho precisa ter pelo menos 2 minutos. "
                                 "Pra um momento curto, escolha \"1 corte\".")
    url = body.url.strip()
    if not url:
        raise HTTPException(400, "Cole o link do VOD.")
    _, _, platform, kind = sources.parse_link(url)
    if kind != "vod":
        raise HTTPException(400, "Esse link é de um canal. Cole o link do VÍDEO da live que já passou "
                                 "(ex: kick.com/nome/videos/..., twitch.tv/videos/... ou youtube.com/watch?v=...).")
    if many:
        # vários cortes: funciona igual ao VOD completo, só que dentro do trecho (ouve só ele, baixa só os cortes)
        nurl, name, plat, _ = sources.parse_link(url)
        vid = db.insert("vods", {"url": nurl, "name": name, "platform": plat, "added_at": time.time(),
                                 "range_start": a, "range_end": b, "title": f"Trecho {_fmt_t(a)} até {_fmt_t(b)}"})
        vod.enqueue(vid)
        vod.to_front(vid)                       # você pediu agora: passa na frente dos VODs completos
        plog.info("✂ Procurando os melhores momentos do trecho %s até %s do VOD…", _fmt_t(a), _fmt_t(b))
        return {"ok": True, "dur": b - a, "vod": vid}
    MANUAL_POOL.submit(_process_vodclip, url, a, b, body.theme, 1)
    plog.info("✂ Baixando o trecho %s até %s do VOD… (só esse pedaço, com a sobra)", _fmt_t(a), _fmt_t(b))
    return {"ok": True, "dur": b - a}


@app.post("/api/upload")
async def upload_clip(request: Request, name: str, platform: str = "kick", theme: str = "gta"):
    """Recebe um vídeo cortado por você e monta no mesmo estilo dos automáticos."""
    fname = urllib.parse.unquote(request.headers.get("x-filename", "video.mp4"))
    ext = ("." + fname.rsplit(".", 1)[-1].lower()) if "." in fname else ".mp4"
    if ext not in UP_EXT:
        raise HTTPException(400, f"Formato {ext} não serve. Envie MP4, MOV, MKV, WEBM ou AVI.")
    name = re.sub(r"[^a-z0-9_]", "", sources.parse_link(name)[1].lower()) if ("." in name or "/" in name) \
        else re.sub(r"[^a-z0-9_]", "", name.lower().lstrip("@"))
    if not name:
        raise HTTPException(400, "Escreva de qual streamer é o corte.")
    if platform not in PLATFORM_URL:
        platform = "kick"
    theme = theme if theme in ("gta", "react") else "gta"
    up = C.CLIPS_DIR / "enviados"
    up.mkdir(parents=True, exist_ok=True)
    raw = up / f"_recebendo_{int(time.time() * 1000)}{ext}"
    size = 0
    with open(raw, "wb") as f:                          # grava aos pouquinhos (vídeo grande não enche a memória)
        async for chunk in request.stream():
            f.write(chunk)
            size += len(chunk)
    if size < 10_000:
        procs.safe_unlink(raw)
        raise HTTPException(400, "O arquivo veio vazio ou incompleto. Tente de novo.")
    plog.info("📤 Recebi seu corte de %s (%d MB). Montando no estilo dos cortes…", name, size // 1_000_000)
    MANUAL_POOL.submit(_process_upload, raw, name, platform, theme)
    return {"ok": True, "name": name}


@app.post("/api/clips/{clip_id}/retext")
def retext(clip_id: int):
    _clip(clip_id)
    db.update("clips", clip_id, {"rendering": 1, "warn": None})
    queue_render(clip_id)
    return {"ok": True}


@app.get("/api/clips/{clip_id}/horizontal")
def clip_horizontal(clip_id: int):
    """Baixar o horizontal: monta na hora (com o pedaço escolhido e a marca d'água) se ainda não estiver pronto."""
    c = _clip(clip_id)
    if c.get("files_deleted") or not c.get("file_h") or not (C.CLIPS_DIR / c["file_h"]).exists():
        raise HTTPException(404, "O vídeo desse corte não está mais no computador.")
    try:
        f = make_horizontal_for(clip_id)
    except Exception as e:
        raise HTTPException(500, f"Não deu pra montar o horizontal: {str(e)[:200]}")
    return FileResponse(f, media_type="video/mp4", filename=f"{c['channel_name']}_{clip_id}_horizontal.mp4")


@app.get("/api/clips/{clip_id}/frame")
def clip_frame(clip_id: int, t: float = 10):
    c = _clip(clip_id)
    out = C.DATA_DIR / f"quadro_corte_{clip_id}.jpg"
    out.unlink(missing_ok=True)
    render.frame_jpg(C.CLIPS_DIR / c["file_h"], out, t=t)
    if not out.exists():
        render.frame_jpg(C.CLIPS_DIR / c["file_h"], out, t=1)
    if not out.exists():
        raise HTTPException(400, "Não deu pra pegar a imagem desse corte")
    return FileResponse(out, headers={"Cache-Control": "no-store"})


def _clip_files(c):
    files = [C.CLIPS_DIR / c[k] for k in ("file_h", "file_v", "file_hw", "thumb") if c.get(k)]
    if c.get("file_h"):
        h = C.CLIPS_DIR / c["file_h"]
        files += [h.with_name(h.name.replace("_h.mp4", s)) for s in ("_v.mp4", "_hw.mp4", ".jpg", ".srt", "_v.novo.mp4")]
    files.append(C.DATA_DIR / f"quadro_corte_{c['id']}.jpg")
    return list(dict.fromkeys(files))   # sem repetir (não conta nem apaga o mesmo arquivo duas vezes)


def _free_files(c, keep_thumb=False):
    """Apaga os arquivos de vídeo do corte. Retorna quantos bytes liberou."""
    freed = 0
    for f in _clip_files(c):
        if keep_thumb and c.get("thumb") and f == C.CLIPS_DIR / c["thumb"]:
            continue
        try:
            if f.exists():
                freed += f.stat().st_size
                f.unlink()
        except OSError:
            pass
    return freed


@app.delete("/api/clips/{clip_id}")
def delete_clip(clip_id: int):
    rows = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))
    if rows:
        if rows[0]["status"] == "pendente":
            quality.record(clip_id, rows[0].get("features"), 0)   # aprende: esse você não quis
        _free_files(rows[0])
        db.execute("DELETE FROM clips WHERE id=?", (clip_id,))
    return {"ok": True}


# ------------------------------------------------------------ espaço no computador
def _size(path):
    total = 0
    for f in Path(path).rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


@app.get("/api/storage")
def storage():
    by = {"pendente": 0, "aprovado": 0, "postado": 0}
    count = {"pendente": 0, "aprovado": 0, "postado": 0}
    for c in db.query("SELECT * FROM clips"):
        st = c["status"] if c["status"] in by else "pendente"
        count[st] += 1
        for f in _clip_files(c):
            try:
                if f.exists():
                    by[st] += f.stat().st_size
            except OSError:
                pass
    known = sum(by.values())
    cortes = _size(C.CLIPS_DIR)
    disk = shutil.disk_usage(C.DATA_DIR)
    return {"cortes": by, "count": count, "outros_cortes": max(0, cortes - known),
            "gravacoes": _size(C.SEGMENTS_DIR), "modelo_lowers": _size(rules.LOWERS_DIR),
            "total": _size(C.DATA_DIR) + (_size(C.SEGMENTS_DIR) if not str(C.SEGMENTS_DIR).startswith(str(C.DATA_DIR)) else 0),
            "disk_free": disk.free}


class CleanupIn(BaseModel):
    what: str
    days: int = 3


@app.post("/api/cleanup")
def cleanup(body: CleanupIn):
    """Libera espaço: vídeos dos postados, novos não aprovados antigos ou arquivos esquecidos."""
    freed, n = 0, 0
    if body.what == "postados":
        for c in db.query("SELECT * FROM clips WHERE status='postado' AND COALESCE(files_deleted,0)=0"):
            freed += _free_files(c, keep_thumb=True)
            db.update("clips", c["id"], {"files_deleted": 1})
            n += 1
    elif body.what == "novos_antigos":
        limit = time.time() - body.days * 86400
        for c in db.query("SELECT * FROM clips WHERE status='pendente' AND created_at < ? AND rendering=0", (limit,)):
            # (não conta como "descartado": você nem chegou a olhar esses)
            freed += _free_files(c)
            db.execute("DELETE FROM clips WHERE id=?", (c["id"],))
            n += 1
    elif body.what == "lixo":
        # arquivos que nenhum corte usa mais (sobras de versões antigas, cortes que deram erro, temporários)
        used = set()
        for c in db.query("SELECT * FROM clips"):
            used |= {str(f) for f in _clip_files(c)}
        used |= {str(C.CLIPS_DIR / r["file"]) for r in db.query("SELECT file FROM compilations WHERE file IS NOT NULL")}
        recent = time.time() - 30 * 60       # não mexe em nada usado nos últimos 30 min (pode ser um corte sendo montado)
        for f in list(C.CLIPS_DIR.rglob("*")):
            if f.is_file() and str(f) not in used and f.stat().st_mtime < recent:
                try:
                    freed += f.stat().st_size
                    f.unlink()
                    n += 1
                except OSError:
                    pass
        for f in C.DATA_DIR.glob("quadro_*.jpg"):
            if f.stat().st_mtime > recent:
                continue
            try:
                freed += f.stat().st_size
                f.unlink()
            except OSError:
                pass
        busy = {w.id for w in workers.values() if w.status == "gravando"}
        for d in C.SEGMENTS_DIR.iterdir() if C.SEGMENTS_DIR.exists() else []:
            if d.is_dir() and not (d.name.isdigit() and int(d.name) in busy):
                for f in d.rglob("*.ts"):
                    try:
                        freed += f.stat().st_size
                        f.unlink()
                    except OSError:
                        pass
    else:
        raise HTTPException(400, "Opção de limpeza desconhecida")
    plog.info("🧹 Limpeza: %s MB liberados (%d item(ns))", round(freed / 1e6), n)
    return {"freed_mb": round(freed / 1e6, 1), "items": n}


app.mount("/media", StaticFiles(directory=C.CLIPS_DIR), name="media")
STATIC = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
