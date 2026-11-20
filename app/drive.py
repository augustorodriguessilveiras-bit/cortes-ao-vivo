"""Baixa arquivos de pastas/links públicos do Google Drive (usado pro Lower dos campeonatos)."""
import html
import re
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout)


def parse(url):
    """('folder'|'file', id) a partir de um link do Drive."""
    m = re.search(r"/folders/([\w-]+)", url)
    if m:
        return "folder", m.group(1)
    m = re.search(r"/file/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
    if m:
        return "file", m.group(1)
    raise ValueError("Esse link não parece ser do Google Drive.")


def list_folder(folder_id):
    """[(id, nome, é_pasta)] de uma pasta pública."""
    with _get(f"https://drive.google.com/embeddedfolderview?id={folder_id}") as r:
        page = r.read().decode("utf-8", "ignore")
    out = []
    for m in re.finditer(r'<a href="(https://drive\.google\.com/(?:file/d|drive/folders)/[^"]+)"[^>]*>.*?'
                         r'class="flip-entry-title">([^<]+)<', page, re.S):
        link, name = m.group(1), html.unescape(m.group(2)).strip()
        kind, fid = parse(link)
        out.append((fid, name, kind == "folder"))
    return out


def download(file_id, dest_dir, stem):
    """Baixa o arquivo; devolve o caminho salvo (com a extensão original)."""
    url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
    with _get(url, timeout=300) as r:
        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="([^"]+)"', cd)
        name = urllib.parse.unquote(m.group(1)) if m else ""
        ctype = r.headers.get("Content-Type", "")
        if "text/html" in ctype:
            raise ValueError("O Drive não liberou o download. Confira se o arquivo está público (qualquer pessoa com o link).")
        data = r.read()
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    out = dest_dir / f"{stem}{ext}"
    out.write_bytes(data)
    return out, name
