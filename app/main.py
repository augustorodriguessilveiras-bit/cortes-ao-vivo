import base64
import logging
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config as C
from . import db, meta, render, settings, sources, vod
from .recorder import CLIP_POOL, ChannelWorker, render_vertical_for

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
    db.execute("UPDATE clips SET rendering=0 WHERE rendering=1")
    CLIP_POOL.submit(render.encoder)  # descobre a placa de vídeo logo no começo
    for ch in db.query("SELECT * FROM channels"):
        start_worker(ch)
    vod.start()
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
            "disk_free_gb": round(disk.free / 1e9, 1), "encoder": enc}


@app.post("/api/settings")
def save_settings(body: dict):
    return settings.update(body)


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
    return db.query(sql, params)


def _clip(clip_id):
    rows = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))
    if not rows:
        raise HTTPException(404, "Corte não encontrado")
    return rows[0]


@app.post("/api/clips/{clip_id}")
def edit_clip(clip_id: int, body: ClipIn):
    _clip(clip_id)
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if data:
        db.update("clips", clip_id, data)
    return {"ok": True}


@app.post("/api/clips/{clip_id}/newtitle")
def new_title(clip_id: int):
    c = _clip(clip_id)
    titles = meta.title_list(c["cat"] or "geral", c["channel_name"], c["subject"])
    idx = ((c["title_idx"] or 0) + 1) % len(titles)
    db.update("clips", clip_id, {"title": titles[idx], "title_idx": idx})
    return {"title": titles[idx]}


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
    CLIP_POOL.submit(render_vertical_for, clip_id)
    return {"ok": True}


@app.post("/api/clips/{clip_id}/retext")
def retext(clip_id: int):
    _clip(clip_id)
    db.update("clips", clip_id, {"rendering": 1, "warn": None})
    CLIP_POOL.submit(render_vertical_for, clip_id)
    return {"ok": True}


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


@app.delete("/api/clips/{clip_id}")
def delete_clip(clip_id: int):
    rows = db.query("SELECT * FROM clips WHERE id=?", (clip_id,))
    if rows:
        for k in ("file_h", "file_v", "thumb"):
            if rows[0][k]:
                (C.CLIPS_DIR / rows[0][k]).unlink(missing_ok=True)
        db.execute("DELETE FROM clips WHERE id=?", (clip_id,))
    return {"ok": True}


app.mount("/media", StaticFiles(directory=C.CLIPS_DIR), name="media")
STATIC = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
