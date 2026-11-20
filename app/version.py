"""Qual versão está rodando e se tem versão nova no GitHub (pra avisar no painel)."""
import json
import logging
import threading
import urllib.request
from pathlib import Path

log = logging.getLogger("painel")
REPO = "augustorodriguessilveiras-bit/cortes-ao-vivo"
ROOT = Path(__file__).resolve().parent.parent
STATE = {"local": None, "latest": None, "checked": False}


def local_version():
    try:
        return (ROOT / ".versao").read_text(encoding="utf-8", errors="ignore").strip() or None
    except Exception:
        return None


def _check():
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/commits/main",
                                     headers={"User-Agent": "cortes-ao-vivo"})
        with urllib.request.urlopen(req, timeout=15) as r:
            STATE["latest"] = json.load(r).get("sha")
    except Exception as e:
        log.debug("não deu pra ver a versão mais nova: %s", e)
    STATE["checked"] = True
    info = status()
    if info["outdated"]:
        log.warning("⚠ Tem versão nova do programa! Feche a janela preta e abra o INICIAR.bat de novo pra atualizar.")


def start_check():
    STATE["local"] = local_version()
    threading.Thread(target=_check, daemon=True).start()


def status():
    local, latest = STATE["local"], STATE["latest"]
    return {
        "local": (local or "")[:7] or None,
        "latest": (latest or "")[:7] or None,
        "outdated": bool(latest) and local != latest,
        "unknown": not local,
    }
