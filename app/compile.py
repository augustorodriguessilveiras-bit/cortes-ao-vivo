"""
Compilado: junta vários cortes num vídeo deitado (16:9) pro YouTube, com o título de cada momento
aparecendo no começo dele, a marca d'água do campeonato e os capítulos prontos pra descrição.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from . import config as C
from . import db, render, rules, settings
from .procs import safe_unlink

log = logging.getLogger("painel")
POOL = ThreadPoolExecutor(max_workers=1)
OUT_DIR = C.CLIPS_DIR / "compilados"
CW, CH = 1920, 1080

with db._lock:
    db._conn.execute("CREATE TABLE IF NOT EXISTS compilations (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL, "
                     "name TEXT, title TEXT, descr TEXT, file TEXT, status TEXT, progress REAL, clip_ids TEXT, error TEXT)")
    db._conn.commit()


def _fmt(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def _clean_title(t):
    import re
    t = re.sub(r"#\S+", "", t or "")
    return render._EMOJI.sub("", t).strip(" -·|")


def candidates(channel="", days=7):
    """Cortes que dá pra usar: aprovados ou postados, com o vídeo ainda no computador."""
    sql = "SELECT * FROM clips WHERE status IN ('aprovado','postado') AND COALESCE(files_deleted,0)=0 AND created_at>=?"
    params = [time.time() - days * 86400]     # (created_at muda quando o vídeo é refeito; serve como "recente")
    if channel:
        sql += " AND channel_name=?"
        params.append(channel)
    out = []
    from .quality import total_views
    for c in db.query(sql + " ORDER BY id", params):
        if c.get("file_h") and (C.CLIPS_DIR / c["file_h"]).exists():
            c["total_views"] = total_views(c.get("views"))
            out.append(c)
    return out


def _title_png(text, out):
    """Título do momento no canto de baixo (faixa branca como a dos cortes, menor)."""
    tmp = Path(out).with_suffix(".big.png")
    h = render.caption_png(text, tmp)
    if not h:
        return 0
    img = Image.open(tmp)
    w2 = int(CW * 0.46)
    img = img.resize((w2, int(img.height * w2 / img.width)), Image.LANCZOS)
    img.save(out)
    safe_unlink(tmp)
    return img.height


def _segment(c, out, idx):
    """Um pedaço do compilado: o corte deitado em 1920x1080, com o título nos primeiros segundos."""
    from .recorder import effective_trim
    src = C.CLIPS_DIR / c["file_h"]
    trim = effective_trim(c)
    tmp = Path(out).with_suffix(".marca.mp4")
    wm = rules.mark_for(c["channel_name"])
    render.horizontal_final(src, tmp, wm, trim, audio_mode=settings.get("audio_mode"))
    _, _, dur = render.probe(tmp)
    png = Path(out).with_suffix(".titulo.png")
    th = _title_png(_clean_title(c.get("overlay") or c.get("title")), png)
    vw, vh, _ = render.probe(tmp)
    if abs(vw / max(1, vh) - CW / CH) < 0.05:          # já é 16:9: só ajusta o tamanho
        base = f"[0:v]scale={CW}:{CH},setsar=1"
    else:                                              # vídeo em pé ou outro formato: fundo desfocado em vez de faixa preta
        base = (f"[0:v]split=2[x][y];[x]scale={CW}:{CH}:force_original_aspect_ratio=increase,crop={CW}:{CH},"
                f"boxblur=25:5,eq=brightness=-0.1[bg];[y]scale={CW}:{CH}:force_original_aspect_ratio=decrease,setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")
    flt = (f"{base},fps=30,format=yuv420p,fade=t=in:st=0:d=0.3,fade=t=out:st={max(0, dur - 0.4):.2f}:d=0.4[b]")
    inputs = ["-i", str(tmp)]
    if th:
        inputs += ["-loop", "1", "-t", "4.5", "-i", str(png)]
        flt += (f";[1:v]format=rgba,fade=t=in:st=0.2:d=0.3:alpha=1,fade=t=out:st=4:d=0.5:alpha=1[t];"
                f"[b][t]overlay=60:{CH - th - 70}:eof_action=pass[v]")
    else:
        flt += ";[b]null[v]"
    try:
        render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", flt,
                    "-map", "[v]", "-map", "0:a:0?", "-af",
                    f"aresample=48000,aformat=channel_layouts=stereo,afade=t=in:d=0.2,afade=t=out:st={max(0, dur - 0.4):.2f}:d=0.4",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", str(out)],
                   timeout=3600)
    finally:
        safe_unlink(tmp)
        safe_unlink(png)
    return render.probe(out)[2]


def suggest_title(names):
    names = sorted(set(names))
    if len(names) == 1:
        disp = rules.display(names[0]).upper()
        n = db.query("SELECT COUNT(*) n FROM compilations WHERE name=? AND status='pronto'", (names[0],))[0]["n"] + 1
        return f"MELHORES MOMENTOS DO {disp} NO GTA 6 #{n}"
    return "MELHORES MOMENTOS DA SEMANA NO GTA 6"


def start(clip_ids, title=None):
    clips = [c for c in (db.query("SELECT * FROM clips WHERE id=?", (i,)) for i in clip_ids) if c]
    clips = [c[0] for c in clips]
    if len(clips) < 2:
        raise ValueError("Escolha pelo menos 2 cortes.")
    names = [c["channel_name"] for c in clips]
    name = names[0] if len(set(names)) == 1 else "varios"
    title = (title or "").strip() or suggest_title(names)
    cid = db.insert("compilations", {"created_at": time.time(), "name": name, "title": title, "status": "na fila",
                                     "progress": 0, "clip_ids": json.dumps([c["id"] for c in clips])})
    POOL.submit(_run, cid, clips, title)
    return cid


def _run(cid, clips, title):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"compilado_{cid}_{stamp}.mp4"
    parts, chapters, t = [], [], 0.0
    try:
        log.info("🎬 Montando o compilado com %d cortes…", len(clips))
        for i, c in enumerate(clips):
            db.update("compilations", cid, {"status": f"montando {i + 1} de {len(clips)}", "progress": i / (len(clips) + 1)})
            seg = OUT_DIR / f"_parte_{cid}_{i}.mp4"
            d = _segment(c, seg, i)
            parts.append(seg)
            chapters.append((t, _clean_title(c.get("title")) or f"Momento {i + 1}"))
            t += d
        db.update("compilations", cid, {"status": "juntando", "progress": len(clips) / (len(clips) + 1)})
        lst = OUT_DIR / f"_lista_{cid}.txt"
        lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
        render.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(out)], timeout=3600)
        safe_unlink(lst)
        chap = "\n".join(f"{_fmt(a)} {b}" for a, b in chapters)
        names = sorted({c["channel_name"] for c in clips})
        tags, mentions = [], []
        for n in names:
            r = rules.for_channel(n)
            if r:
                tags += r.get("hashtags", [])
                if r.get("mention"):
                    mentions.append(r["mention"])
        disp = ", ".join(rules.display(n) for n in names)
        descr = (f"Os melhores momentos de {disp} no GTA 6! 🎮\n"
                 + (f"Canal: {' '.join(mentions)}\n" if mentions else "")
                 + f"\n⏱ Capítulos:\n{chap}\n\n"
                 + " ".join(dict.fromkeys(tags + ["#gta6", "#gtavi", "#gta6brasil", "#melhoresmomentos"])))
        if title and rules.for_channel(names[0]) and len(names) == 1:
            title = rules.title_with_tag(names[0], title)
        db.update("compilations", cid, {"status": "pronto", "progress": 1, "file": out.relative_to(C.CLIPS_DIR).as_posix(),
                                        "descr": descr, "title": title})
        log.info("🎬 Compilado pronto! (%s)", _fmt(t))
    except Exception as e:
        log.warning("⚠ Não deu pra montar o compilado (%s).", str(e)[:150])
        db.update("compilations", cid, {"status": "erro", "error": str(e)[:300]})
        safe_unlink(out)
    finally:
        for p in parts:
            safe_unlink(p)


def remove(cid):
    r = db.query("SELECT * FROM compilations WHERE id=?", (cid,))
    if r and r[0].get("file"):
        safe_unlink(C.CLIPS_DIR / r[0]["file"])
    db.execute("DELETE FROM compilations WHERE id=?", (cid,))
