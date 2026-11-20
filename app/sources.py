"""Descobre de onde baixar o vídeo (live ou VOD) direto do servidor da plataforma."""
import logging
import re
from urllib.parse import urlparse, parse_qs

import yt_dlp

log = logging.getLogger("sources")


def parse_link(url: str):
    """Retorna (url_normalizada, nome_do_canal, plataforma, tipo) — tipo é 'live' ou 'vod'."""
    url = url.strip()
    if not re.match(r"^[a-z]+://", url, re.I):
        url = ("https://" + url) if "." in url else f"https://www.twitch.tv/{url.lstrip('@')}"
    u = urlparse(url)
    host = u.netloc.lower().removeprefix("www.").removeprefix("m.")
    parts = [p for p in u.path.split("/") if p]
    if "twitch.tv" in host:
        if parts and parts[0] == "videos" and len(parts) > 1:
            return f"https://www.twitch.tv/videos/{parts[1]}", "twitch", "twitch", "vod"
        if len(parts) >= 3 and parts[1] == "v":
            return f"https://www.twitch.tv/videos/{parts[2]}", parts[0].lower(), "twitch", "vod"
        if parts:
            return f"https://www.twitch.tv/{parts[0].lower()}", parts[0].lower(), "twitch", "live"
    if "kick.com" in host and parts:
        name = parts[0].lower()
        if name == "video" and len(parts) > 1:
            return url, "kick", "kick", "vod"
        if len(parts) >= 3 and parts[1] in ("videos", "video"):
            return f"https://kick.com/{name}/videos/{parts[2]}", name, "kick", "vod"
        return f"https://kick.com/{name}", name, "kick", "live"
    if "youtube.com" in host or host == "youtu.be":
        at = next((p for p in parts if p.startswith("@")), None)
        if at and (len(parts) == 1 or parts[-1] == "live"):
            return f"https://www.youtube.com/{at}/live", at[1:].lower(), "youtube", "live"
        vid = parse_qs(u.query).get("v", [None])[0] or (parts[0] if host == "youtu.be" and parts else None) \
            or (parts[1] if len(parts) > 1 and parts[0] in ("live", "shorts") else None)
        if vid:
            return f"https://www.youtube.com/watch?v={vid}", "youtube", "youtube", "vod"
    return url, (parts[-1] if parts else host), "outro", "vod"


class _Quiet:
    """Não imprime nada na janela preta (canal offline não é erro)."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): log.debug(msg)


def _ydl(fmt):
    return yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "format": fmt, "noplaylist": True, "logger": _Quiet()})


def ffmpeg_inputs(info):
    """Converte a resposta do yt-dlp em entradas do ffmpeg (com os cabeçalhos certos)."""
    fmts = info.get("requested_formats") or [info]
    out = []
    for f in fmts:
        hdr = f.get("http_headers") or info.get("http_headers") or {}
        ua = hdr.pop("User-Agent", None)
        args = []
        if ua:
            args += ["-user_agent", ua]
        if hdr:
            args += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in hdr.items())]
        out.append((args, f["url"]))
    return out


def resolve(url, quality="best"):
    """
    quality: 'best' (vídeo pro corte) ou 'worst' (só pra ouvir o áudio, gasta pouca internet).
    Retorna o info do yt-dlp (com is_live, duration, uploader, title...).
    """
    fmt = "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b" if quality == "best" else "worst*[acodec!=none]/worst"
    return _ydl(fmt).extract_info(url, download=False)


def is_live(url):
    try:
        info = resolve(url, "best")
        return info if info.get("is_live") else None
    except Exception as e:
        log.debug("%s offline: %s", url, str(e)[:120])
        return None
