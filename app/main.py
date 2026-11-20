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
import urllib.parse

from . import db, drive, meta, procs, quality, render, rules, settings, sources, version, vod
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
    procs.tie_children_to_me()   # gravadores fecham junto com o programa (Windows)
    db.execute("UPDATE clips SET rendering=0 WHERE rendering=1")
    # cortes de versões antigas: o texto que está no vídeo é o texto salvo
    db.execute("UPDATE clips SET overlay_applied=COALESCE(overlay,'') WHERE overlay_applied IS NULL")
    CLIP_POOL.submit(render.encoder)  # descobre a placa de vídeo logo no começo
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
            "version": version.status(), "learning": quality.stats(),
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
    rows = db.query(sql, params)
    for c in rows:
        c["rules"] = rules.public(c["channel_name"])
        c["ov_secs"] = settings.get("ov_secs")   # cortes feitos antes das tags do YouTube ganham as tags agora
        if not c.get("yt_tags"):
            c["yt_tags"] = meta.youtube_tags(c["channel_name"], c.get("platform") or "", c.get("cat") or "geral", c.get("subject"))
            db.update("clips", c["id"], {"yt_tags": c["yt_tags"]})
    return rows


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
    raw, n_subject = meta.titles_for(c["channel_name"], c["cat"] or "geral", c["subject"], gain)
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
    CLIP_POOL.submit(render_vertical_for, clip_id)
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
    first, rest = meta.hooks_for(c["channel_name"], c["cat"] or "geral", subject, _gain(c))
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


@app.post("/api/clips/{clip_id}/yttags")
def regen_tags(clip_id: int):
    c = _clip(clip_id)
    subject = c["subject"] or meta.find_subject([c["transcript"] or ""] * 2)
    tags = meta.youtube_tags(c["channel_name"], c.get("platform") or "", c.get("cat") or "geral", subject)
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
    CLIP_POOL.submit(render_vertical_for, clip_id)
    plog.info("✂ %s: refazendo o corte com as suas edições…", c["channel_name"])
    return {"ok": True}


# ------------------------------------------------------------ Lower dos campeonatos
def _rerender_channel(key):
    """Refaz os cortes do canal (pra entrar o Lower novo)."""
    n = 0
    for c in db.query("SELECT id, channel_name FROM clips WHERE rendering=0"):
        if rules.key_for(c["channel_name"]) == key:
            db.update("clips", c["id"], {"rendering": 1})
            CLIP_POOL.submit(render_vertical_for, c["id"])
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
            quality.record(c["id"], c.get("features"), 0)
            freed += _free_files(c)
            db.execute("DELETE FROM clips WHERE id=?", (c["id"],))
            n += 1
    elif body.what == "lixo":
        # arquivos que nenhum corte usa mais (sobras de versões antigas, cortes que deram erro, temporários)
        used = set()
        for c in db.query("SELECT * FROM clips"):
            used |= {str(f) for f in _clip_files(c)}
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
