"""
Montagem dos cortes com ffmpeg, na qualidade original:
  - horizontal (16:9, igual à live)
  - vertical 9:16: câmera em cima + gameplay embaixo (ou gameplay com fundo desfocado)
  - faixa branca com o título nos primeiros segundos
Usa a placa de vídeo (NVIDIA / Intel / AMD) quando existir.
"""
import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("render")
W, H = 1080, 1920
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # não abre janelas pretas no Windows


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou: {r.stderr[-600:]}")
    return r


# ------------------------------------------------------------ codificador
_enc = None
_enc_lock = threading.Lock()
ENCODERS = [
    ("NVIDIA", ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0"]),
    ("Intel", ["-c:v", "h264_qsv", "-global_quality", "20"]),
    ("AMD", ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "19", "-qp_p", "21"]),
]
X264 = ("processador", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"])


def encoder():
    """Descobre uma vez qual codificador funciona neste PC."""
    global _enc
    with _enc_lock:
        if _enc is None:
            _enc = X264
            for name, args in ENCODERS:
                try:
                    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                         "color=c=black:s=640x360:d=0.2", *args, "-pix_fmt", "yuv420p", "-f", "null", "-"],
                        timeout=20)
                    _enc = (name, args)
                    break
                except Exception:
                    continue
            log.info("🖥 Os vídeos vão ser montados usando: %s", "placa de vídeo " + _enc[0] if _enc[0] != "processador" else "o processador (sem placa de vídeo compatível)")
        return _enc


def venc():
    return [*encoder()[1], "-pix_fmt", "yuv420p"]


AENC = ["-c:a", "aac", "-b:a", "192k"]


# ------------------------------------------------------------ volume do áudio
def audio_fix(src, ts=0.0, dur=None, mode="auto"):
    """
    Decide o que fazer com o volume do corte, olhando separado:
      - o volume da FALA (o volume típico de cada segundo; um grito sozinho não muda isso)
      - o PICO (o ponto mais alto, normalmente um grito)
    Regras:
      - fala muito baixa e o grito tem espaço: aumenta só o que cabe (o grito nunca passa de -1,5 dB)
      - grito batendo no limite: abaixa o corte inteiro só o necessário (sem esmagar o grito, que distorce)
      - o resto: não mexe (som original da live)
    Retorna (lista de filtros de áudio do ffmpeg, explicação).
    """
    if mode == "off":
        return [], "áudio original"
    try:
        import numpy as np
        seek = ["-ss", f"{ts:.2f}"] + (["-t", f"{dur:.2f}"] if dur else [])
        r = subprocess.run(["ffmpeg", "-v", "error", *seek, "-i", str(src), "-vn", "-ac", "1", "-ar", "48000",
                            "-f", "f32le", "-"], capture_output=True, creationflags=NO_WINDOW, timeout=300)
        a = np.frombuffer(r.stdout, np.float32)
        if len(a) < 48000:
            return [], "áudio original"
        peak = 20 * np.log10(float(np.max(np.abs(a))) + 1e-9)
        secs = a[: len(a) // 48000 * 48000].reshape(-1, 48000)
        rms = 20 * np.log10(np.sqrt(np.mean(secs ** 2, axis=1)) + 1e-9)
        rms = rms[rms > -60]                          # ignora silêncio
        if len(rms) == 0:
            return [], "áudio original"
        speech = float(np.median(rms))                # volume típico (fala/jogo)
    except Exception:
        return [], "áudio original"
    if speech < -32:                                  # fala muito baixa
        gain = min(10.0, -24.0 - speech, -1.5 - peak)  # nunca deixa o pico passar de -1,5 dB
        if gain >= 2:
            return [f"volume={gain:.1f}dB"], f"fala estava baixa: aumentado {gain:.0f} dB (sem estourar)"
        if peak <= -1.0:
            return [], "áudio original (fala baixa, mas o grito já está alto; não deu pra aumentar sem estourar)"
    if peak > -1.0:                                   # grito batendo no limite
        gain = -1.5 - peak
        return [f"volume={gain:.1f}dB"], f"grito batendo no limite: abaixado {abs(gain):.1f} dB pra não estourar"
    return [], "áudio original"


# ------------------------------------------------------------ utilidades
def probe(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", str(path)])
    j = json.loads(r.stdout)
    st = (j.get("streams") or [{}])[0]
    return int(st.get("width", 1920)), int(st.get("height", 1080)), float(j.get("format", {}).get("duration", 0) or 0)


def frame_jpg(src, out, t=None, sseof=None, width=None):
    """Salva um quadro como JPG. Se o ponto pedido não tiver imagem, tenta pontos anteriores."""
    vf = ["-vf", f"scale={width}:-2"] if width else []
    tries = [["-sseof", str(sseof)]] if sseof is not None else []
    if t is not None:
        tries += [["-ss", f"{x:.2f}"] for x in (t, t * 0.6, t * 0.3)]
    tries.append([])
    Path(out).unlink(missing_ok=True)
    for pre in tries:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *pre, "-i", str(src),
             "-frames:v", "1", "-update", "1", *vf, "-q:v", "3", str(out)], timeout=60)
        if Path(out).exists() and Path(out).stat().st_size > 0:
            return True
    return False


def even(n):
    return max(2, int(round(n / 2)) * 2)


def cover_crop(sx, sy, sw, sh, dw, dh):
    """Recorte central de (sx,sy,sw,sh) com a proporção dw:dh."""
    ar = dw / dh
    w, h = sw, sw / ar
    if h > sh:
        h, w = sh, sh * ar
    return sx + (sw - w) / 2, sy + (sh - h) / 2, w, h


# ------------------------------------------------------------ faixa do título
_EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200d]")
FONTS = [
    "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Black.ttf",
]


def _font(size):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def caption_png(text, out):
    """Faixa branca 1080 de largura com texto preto e forte. Retorna a altura."""
    text = re.sub(r"\s+", " ", _EMOJI.sub("", text)).strip().upper()
    if not text:
        return 0
    max_w = W * 0.92
    size = int(W * 0.056)
    dummy = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while True:
        font = _font(size)
        lines, cur = [], ""
        for word in text.split(" "):
            t = f"{cur} {word}".strip()
            if dummy.textlength(t, font=font) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        if (len(lines) <= 3 and all(dummy.textlength(l, font=font) <= max_w for l in lines)) or size <= 32:
            break
        size -= 2
    lh, pad = int(size * 1.18), int(size * 0.55)
    band_h = even(lh * len(lines) + pad * 2)
    img = Image.new("RGBA", (W, band_h), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        d.text((W / 2, pad + lh * (i + 0.5)), l, font=font, fill=(0, 0, 0, 255), anchor="mm")
    img.save(out)
    return band_h


# ------------------------------------------------------------ legenda palavra por palavra
SUB_YELLOW = (255, 221, 51, 255)
_PUNCT = re.compile(r"[\"“”«»(),.;:…]+")


def _clean_word(w):
    w = _PUNCT.sub("", _EMOJI.sub("", w or "")).strip().upper()
    return w


def sub_chunks(words, ts, te, max_words=3, max_chars=16):
    """Agrupa as palavras em pedacinhos de até 3 palavras (o que cabe na tela de uma vez). Tempos contando do ts."""
    ws = [(max(0.0, a - ts), min(te, b) - ts, _clean_word(w)) for a, b, w in (words or []) if b > ts and a < te]
    ws = [w for w in ws if w[2]]
    chunks, cur = [], []
    for w in ws:
        txt = " ".join(x[2] for x in cur + [w])
        if cur and (len(cur) >= max_words or len(txt) > max_chars or w[0] - cur[-1][1] > 0.5):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def sub_png(chunk, hi, out):
    """Pedacinho da legenda: letras brancas com contorno preto, a palavra falada agora em amarelo."""
    size = int(W * 0.078)
    font = _font(size)
    d0 = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = [w[2] for w in chunk]
    space = d0.textlength(" ", font=font)
    while sum(d0.textlength(w, font=font) for w in words) + space * (len(words) - 1) > W * 0.9 and size > 40:
        size -= 4
        font = _font(size)
        space = d0.textlength(" ", font=font)
    stroke = max(4, size // 9)
    hgt = int(size * 1.6)
    img = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    total = sum(d.textlength(w, font=font) for w in words) + space * (len(words) - 1)
    x = (W - total) / 2
    for i, w in enumerate(words):
        d.text((x, hgt / 2), w, font=font, anchor="lm", fill=SUB_YELLOW if i == hi else (255, 255, 255, 255),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        x += d.textlength(w, font=font) + space
    img.save(out)
    return hgt


def subs_track(words, ts, te, base):
    """
    Monta a legenda inteira como uma sequência de imagens com tempo (entra no ffmpeg como um vídeo transparente).
    Retorna (lista_concat, altura, arquivos criados) ou None se não tiver palavra.
    """
    chunks = sub_chunks(words, ts, te)
    if not chunks:
        return None
    dur = te - ts
    base = Path(base)
    files = []
    blank = base.with_name(base.name + ".sub_vazio.png")
    hgt = None
    events = []          # (início, fim, arquivo)
    n = 0
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0][0] if ci + 1 < len(chunks) else dur
        end_chunk = min(nxt, ch[-1][1] + 0.35)
        for wi, w in enumerate(ch):
            f = base.with_name(f"{base.name}.sub{n}.png")
            n += 1
            hgt = sub_png(ch, wi, f)
            files.append(f)
            a = w[0] if wi else min(w[0], ch[0][0])
            b = ch[wi + 1][0] if wi + 1 < len(ch) else end_chunk
            events.append((a, max(b, a + 0.06), f))
    Image.new("RGBA", (W, hgt), (0, 0, 0, 0)).save(blank)
    files.append(blank)
    lines, t = [], 0.0
    for a, b, f in events:
        a = max(a, t)
        if b <= a:
            continue
        if a - t > 0.01:
            lines += [f"file '{blank.resolve().as_posix()}'", f"duration {a - t:.3f}"]
        lines += [f"file '{Path(f).resolve().as_posix()}'", f"duration {b - a:.3f}"]
        t = b
    lines += [f"file '{blank.resolve().as_posix()}'", f"duration {max(0.1, dur - t):.3f}",
              f"file '{blank.resolve().as_posix()}'"]
    lst = base.with_name(base.name + ".subs.txt")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    files.append(lst)
    return lst, hgt, files


def zoom_expr(zooms, amount=0.16):
    """Expressão do zoom rápido nos momentos de reação (entra em 0,2 s, fica ~1,4 s e sai em 0,4 s)."""
    parts = [f"min(1,max(0,(in_time-{t - 0.15:.2f})/0.2))*min(1,max(0,({t + 1.6:.2f}-in_time)/0.4))" for t in zooms]
    return f"1+{amount}*min(1,{'+'.join(parts)})"


def fps_of(path):
    try:
        r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                 "-of", "csv=p=0", str(path)])
        a, b = (r.stdout.strip().split("/") + ["1"])[:2]
        f = float(a) / float(b)
        return r.stdout.strip() if 10 <= f <= 120 else "30"
    except Exception:
        return "30"


# ------------------------------------------------------------ marca d'água
def watermark_png(text, out, width, frac=0.034):
    """Selo legível com o texto (ex: kick.com/orenatovicente): fundo escuro, texto branco grosso."""
    size = max(18, int(width * frac))
    font = _font(size)
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tw = d.textlength(text, font=font)
    pad_x, pad_y = int(size * 0.7), int(size * 0.38)
    w, h = even(tw + pad_x * 2), even(size * 1.2 + pad_y * 2)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(img)
    g.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=(0, 0, 0, 165))
    g.text((w / 2, h / 2), text, font=font, fill=(255, 255, 255, 255), anchor="mm",
           stroke_width=max(1, size // 18), stroke_fill=(0, 0, 0, 255))
    img.save(out)
    return w, h


VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")


def lower_input(path, dur):
    """Entrada do ffmpeg pro Lower (imagem fica parada, vídeo repete) + (largura, altura) dele."""
    path = Path(path)
    if path.suffix.lower() in VIDEO_EXT:
        w, h, _ = probe(path)
        return ["-stream_loop", "-1", "-t", f"{dur:.2f}", "-i", str(path)], (w, h)
    with Image.open(path) as im:
        w, h = im.size
    return ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(path)], (w, h)


_lower_cache = {}


def lower_info(path):
    """
    Analisa o Lower: cor de fundo pra tirar (ex: azul/verde de chroma key), a área que tem o desenho de verdade
    e onde ele fica no original. Retorna dict com: size (w,h), key (cor hex ou None), box (x,y,w,h em px),
    cx, cy (centro do desenho, 0 a 1) e wfrac (largura do desenho em relação à largura do quadro).
    """
    import numpy as np
    path = Path(path)
    stamp = (str(path), path.stat().st_mtime)
    if stamp in _lower_cache:
        return _lower_cache[stamp]
    is_vid = path.suffix.lower() in VIDEO_EXT
    frames = []
    if is_vid:
        lw, lh, dur = probe(path)
        for frac in (0.05, 0.25, 0.5, 0.75, 0.95):
            tmp = path.with_name(f"_analise_{int(frac * 100)}.png")
            try:
                run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, dur * frac):.2f}", "-i", str(path),
                     "-frames:v", "1", "-update", "1", str(tmp)], timeout=60)
                if tmp.exists():
                    with Image.open(tmp) as im:
                        frames.append(np.asarray(im.convert("RGBA")).astype(np.int16))
            finally:
                tmp.unlink(missing_ok=True)
    else:
        with Image.open(path) as im:
            lw, lh = im.size
            frames.append(np.asarray(im.convert("RGBA")).astype(np.int16))
    if not frames:
        info = {"size": (lw, lh), "key": None, "box": (0, 0, lw, lh), "cx": 0.5, "cy": 0.5, "wfrac": 1.0}
        _lower_cache[stamp] = info
        return info
    f0 = frames[0]
    h, w = f0.shape[:2]
    has_alpha = bool((f0[..., 3] < 250).mean() > 0.2)
    key = None
    if not has_alpha:
        k = max(4, min(w, h) // 40)
        corners = np.concatenate([f0[:k, :k, :3].reshape(-1, 3), f0[:k, -k:, :3].reshape(-1, 3),
                                  f0[-k:, :k, :3].reshape(-1, 3), f0[-k:, -k:, :3].reshape(-1, 3)])
        med = np.median(corners, axis=0)
        if np.abs(corners - med).max(axis=1).mean() < 25:      # cantos da mesma cor: é fundo pra tirar
            key = med.astype(int)
    mask = np.zeros((h, w), bool)
    for fr in frames:
        if key is not None:
            mask |= np.abs(fr[..., :3] - key).sum(axis=2) > 90
        else:
            mask |= fr[..., 3] > 20
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        x0, y0, x1, y1 = 0, 0, w, h
    else:
        pad = int(min(w, h) * 0.01)
        x0, y0 = max(0, xs.min() - pad), max(0, ys.min() - pad)
        x1, y1 = min(w, xs.max() + pad + 1), min(h, ys.max() + pad + 1)
    bw, bh = even(x1 - x0), even(y1 - y0)
    x0, y0 = min(x0, w - bw), min(y0, h - bh)
    info = {"size": (lw, lh), "key": ("0x%02X%02X%02X" % tuple(int(c) for c in key)) if key is not None else None,
            "box": (int(x0), int(y0), int(bw), int(bh)), "cx": float((x0 + bw / 2) / w), "cy": float((y0 + bh / 2) / h),
            "wfrac": float(bw / w)}
    _lower_cache[stamp] = info
    return info


def lower_filter(info, target_w):
    """Filtro: recorta só o desenho, tira o fundo (se tiver) e deixa na largura certa."""
    x, y, bw, bh = info["box"]
    f = f"crop={bw}:{bh}:{x}:{y},"
    if info["key"]:
        f += f"colorkey={info['key']}:0.30:0.12,"
    return f + f"scale={even(target_w)}:-2,"


def lower_preview_png(path, out):
    """Imagem do Lower já sem fundo e recortada (pra prévia no painel)."""
    info = lower_info(path)
    vid = Path(path).suffix.lower() in VIDEO_EXT
    seek = ["-ss", f"{probe(path)[2] * 0.5:.2f}"] if vid else []
    x, y, bw, bh = info["box"]
    vf = f"crop={bw}:{bh}:{x}:{y}" + (f",colorkey={info['key']}:0.30:0.12" if info["key"] else "") + ",format=rgba"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *seek, "-i", str(path), "-frames:v", "1", "-update", "1",
         "-vf", vf, str(out)], timeout=60)
    return info


def horizontal_final(src, out, text=None, trim=None, audio_mode="auto"):
    """Horizontal pra baixar: com o corte manual (trim) e a marca d'água, se tiver."""
    vw, vh, full = probe(src)
    ts, te = (trim or (0, full))
    ts, te = max(0.0, ts or 0.0), min(full, te or full)
    if te - ts < 1:
        ts, te = 0.0, full
    dur = te - ts
    png = Path(out).with_suffix(".marca.png")
    try:
        inputs = ["-ss", f"{ts:.2f}", "-t", f"{dur:.2f}", "-i", str(src)]
        if isinstance(text, Path):          # Lower (imagem/vídeo do campeonato), sem fundo e recortado
            args, _ = lower_input(text, dur)
            inputs += args
            info = lower_info(text)
            tw = min(vw * 0.45, vw * info["wfrac"] * 0.6)
            flt = f"[1:v]{lower_filter(info, tw)}format=rgba[lw];[0:v][lw]overlay=(W-w)/2:H-h-H*0.04:shortest=1[v]"
        elif text:
            _, h = watermark_png(text, png, vw, frac=0.026)
            y = int(vh - h - vh * 0.05)
            inputs += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(png)]
            flt = f"[0:v][1:v]overlay=(W-w)/2:{y}:shortest=1[v]"
        else:
            flt = "[0:v]null[v]"
        afx, _ = audio_fix(src, ts, dur, audio_mode)
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", flt,
             "-map", "[v]", "-map", "0:a:0?", *venc(), *(["-af", ",".join(afx)] if afx else []), *AENC,
             "-movflags", "+faststart", str(out)], timeout=1800)
    finally:
        png.unlink(missing_ok=True)


# ------------------------------------------------------------ cortes
def make_horizontal(inputs, out, offset, dur):
    """
    inputs: lista de argumentos de entrada do ffmpeg já prontos, ex:
      ["-f", "concat", "-safe", "0", "-i", "lista.txt"]   (gravação ao vivo)
      ["-ss", "120", "-i", url]                           (VOD, busca direto no servidor)
    """
    seek = ["-ss", f"{offset:.2f}"] if offset else []
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, *seek, "-t", f"{dur:.2f}",
         "-map", "0:v:0", "-map", "0:a:0?", *venc(), *AENC, "-movflags", "+faststart", str(out)], timeout=1800)


def second_levels(src, ts=0.0, dur=None):
    """Volume (RMS) de cada segundo do trecho. Lista vazia se não der pra ouvir."""
    try:
        import numpy as np
        seek = ["-ss", f"{ts:.2f}"] + (["-t", f"{dur:.2f}"] if dur else [])
        r = subprocess.run(["ffmpeg", "-v", "error", *seek, "-i", str(src), "-vn", "-ac", "1", "-ar", "8000",
                            "-f", "f32le", "-"], capture_output=True, creationflags=NO_WINDOW, timeout=600)
        a = np.frombuffer(r.stdout, np.float32)
        n = len(a) // 8000
        return [float(x) for x in np.sqrt(np.mean(a[: n * 8000].reshape(n, 8000) ** 2, axis=1))] if n else []
    except Exception:
        return []


def loudest_second(src, ts=0.0, dur=None):
    """Segundo mais alto (grito/reação) do trecho, contando do começo do arquivo. None se não der pra ouvir."""
    try:
        import numpy as np
        seek = ["-ss", f"{ts:.2f}"] + (["-t", f"{dur:.2f}"] if dur else [])
        r = subprocess.run(["ffmpeg", "-v", "error", *seek, "-i", str(src), "-vn", "-ac", "1", "-ar", "8000",
                            "-f", "f32le", "-"], capture_output=True, creationflags=NO_WINDOW, timeout=300)
        a = np.frombuffer(r.stdout, np.float32)
        n = len(a) // 8000
        if n < 2:
            return None
        rms = np.sqrt(np.mean(a[: n * 8000].reshape(n, 8000) ** 2, axis=1))
        return ts + float(np.argmax(rms)) + 0.5
    except Exception:
        return None


# ------------------------------------------------------------ formato do vertical
LAYOUTS = {"cam": "Câmera em cima + gameplay", "full": "Tela cheia", "game": "Só gameplay"}


def _frames_faces(h_path, fracs=(0.15, 0.3, 0.45, 0.6, 0.75, 0.9)):
    """Rostos encontrados em alguns quadros do corte: lista (por quadro) de (cx, cy, w, h) de 0 a 1."""
    import cv2
    _, _, dur = probe(h_path)
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    out = []
    for frac in fracs:
        tmp = Path(h_path).with_suffix(f".det{int(frac * 100)}.jpg")
        try:
            if not frame_jpg(h_path, tmp, t=max(0.5, dur * frac), width=960):
                continue
            img = cv2.imread(str(tmp), cv2.IMREAD_GRAYSCALE)
        finally:
            tmp.unlink(missing_ok=True)
        if img is None:
            continue
        ih, iw = img.shape
        faces = casc.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(int(iw * 0.025), int(iw * 0.025)))
        out.append([((x + w / 2) / iw, (y + h / 2) / ih, w / iw, h / ih) for x, y, w, h in faces])
    return out


def find_webcam(frames, vw, vh):
    """
    Acha a webcam do streamer: um rosto pequeno que fica PARADO no mesmo lugar em vários quadros
    (rostos do jogo se mexem). Monta a caixa da webcam ao redor dele. Retorna o retângulo (0 a 1) ou None.
    """
    small = [[f for f in fr if 0.022 <= f[2] <= 0.12] for fr in frames]
    best, best_n = None, 0
    for fr in small:
        for f in fr:
            near = [g for other in small for g in other if abs(g[0] - f[0]) < 0.03 and abs(g[1] - f[1]) < 0.04]
            n = len({id(other) for other in small for g in other if g in near})
            if n > best_n:
                best, best_n = near, n
    if not best or best_n < max(3, len(frames) // 2):
        return None
    cx = sum(g[0] for g in best) / len(best)
    cy = sum(g[1] for g in best) / len(best)
    fw = sum(g[2] for g in best) / len(best) * vw          # tamanho do rosto em pixels
    cam_w = min(vw * 0.5, fw * 3.6)                        # webcam mostra cabeça e ombros
    cam_h = min(vh * 0.6, cam_w * 9 / 16)
    x0 = cx * vw - cam_w / 2
    y0 = cy * vh - cam_h * 0.42                             # o rosto fica um pouco acima do meio da webcam
    x0 = max(0.0, min(vw - cam_w, x0))
    y0 = max(0.0, min(vh - cam_h, y0))
    return {"x": float(x0 / vw), "y": float(y0 / vh), "w": float(cam_w / vw), "h": float(cam_h / vh), "auto": True}


def detect_layout(h_path, cam):
    """
    Olha alguns quadros do corte e decide o formato:
      - 'full': o rosto do streamer aparece grande e fora da caixinha da webcam (full cam / só a câmera)
      - 'cam' : gameplay com a webcam no canto (marcada por você ou achada sozinha)
      - 'game': só gameplay
    Retorna (formato, posição horizontal do rosto de 0 a 1, webcam achada sozinha ou None).
    """
    default = ("cam" if cam else "game"), 0.5, None
    try:
        import cv2  # noqa: F401
        frames = _frames_faces(h_path)
    except Exception:
        return default
    hits, xs = 0, []
    for fr in frames:
        if not fr:
            continue
        fx, fy, w, _ = max(fr, key=lambda f: f[2] * f[3])
        in_cam = bool(cam) and cam["x"] - 0.03 <= fx <= cam["x"] + cam["w"] + 0.03 \
            and cam["y"] - 0.03 <= fy <= cam["y"] + cam["h"] + 0.03
        if w >= 0.08 and not in_cam:
            hits += 1
            xs.append(fx)
    if hits >= max(2, len(frames) // 3):
        return "full", sum(xs) / len(xs), None
    if not cam:
        vw, vh, _ = probe(h_path)
        found = find_webcam(frames, vw, vh)
        if found:
            return "cam", 0.5, found
    return default
    _, _, dur = probe(h_path)
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    hits, xs = 0, []
    for frac in (0.2, 0.45, 0.7, 0.9):
        tmp = Path(h_path).with_suffix(f".det{int(frac * 100)}.jpg")
        try:
            if not frame_jpg(h_path, tmp, t=max(0.5, dur * frac), width=640):
                continue
            img = cv2.imread(str(tmp), cv2.IMREAD_GRAYSCALE)
        finally:
            tmp.unlink(missing_ok=True)
        if img is None:
            continue
        ih, iw = img.shape
        faces = casc.detectMultiScale(img, scaleFactor=1.1, minNeighbors=5, minSize=(int(iw * 0.05), int(iw * 0.05)))
        if len(faces) == 0:
            continue
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        fx, fy = (x + w / 2) / iw, (y + h / 2) / ih
        in_cam = bool(cam) and cam["x"] - 0.03 <= fx <= cam["x"] + cam["w"] + 0.03 \
            and cam["y"] - 0.03 <= fy <= cam["y"] + cam["h"] + 0.03
        if w / iw >= 0.08 and not in_cam:
            hits += 1
            xs.append(fx)
    if hits >= 2:
        return "full", sum(xs) / len(xs)
    return default


def vertical_filter(vw, vh, layout, cam, focus_x, cap_h, cap_secs, dur=0, wm_idx=None, wm_y=0,
                    cap_win=None, cap_yc=None, wm_xc=None, wm_pre="", zooms=None, fps="30", sub_idx=None, sub_y=None):
    """Monta o filtro do ffmpeg pro formato escolhido, com a faixa do título se tiver."""
    zp = lambda w, h: (f",zoompan=z='{zoom_expr(zooms)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}"
                       if zooms else "")
    if layout == "full":
        # tela cheia: recorte vertical da imagem inteira, centrado no streamer
        cw = min(even(vh * W / H), even(vw))
        cx = min(max(0, focus_x * vw - cw / 2), vw - cw)
        f = f"[0:v]crop={cw}:{even(vh)}:{int(cx)}:0,scale={W}:{H},setsar=1{zp(W, H)}[base]"
        y = int(H * 0.70) - cap_h // 2
    elif layout == "cam" and cam:
        cx, cy, cw, ch = cam["x"] * vw, cam["y"] * vh, cam["w"] * vw, cam["h"] * vh
        th = even(min(H * 0.42, max(H * 0.28, W / (cw / ch))))
        bh = H - th
        a = cover_crop(cx, cy, cw, ch, W, th)
        g = list(cover_crop(0, 0, vw, vh, W, bh))
        # se a câmera estiver num canto e invadir o recorte da gameplay, desloca o recorte pro outro lado
        if cam["w"] < 0.5 and g[0] < cx + cw and g[0] + g[2] > cx:
            if cx + cw / 2 >= vw / 2:
                g[0] = max(0.0, min(g[0], cx - g[2]))
            else:
                g[0] = min(vw - g[2], max(g[0], cx + cw))
        crop = lambda r: f"crop={even(r[2])}:{even(r[3])}:{int(r[0])}:{int(r[1])}"
        f = (f"[0:v]split=2[a][b];[a]{crop(a)},scale={W}:{th},setsar=1{zp(W, th)}[top];"
             f"[b]{crop(g)},scale={W}:{bh},setsar=1[bot];"
             f"[top][bot]vstack=2,drawbox=x=0:y={th - 3}:w={W}:h=6:color=black:t=fill[base]")
        y = th - cap_h // 2
    else:
        fit_h = even(W * vh / vw)
        f = (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             f"boxblur=25:5,eq=brightness=-0.08[bg];[b]scale={W}:{fit_h},setsar=1{zp(W, fit_h)}[fg];"
             f"[bg][fg]overlay=0:{(H - fit_h) // 2}[base]")
        y = (H - fit_h) // 2 - cap_h // 2
    if cap_yc is not None:          # posição escolhida no editor (centro da faixa)
        y = int(cap_yc) - cap_h // 2
    y = max(0, min(H - cap_h, y))
    if cap_h:
        a, b = cap_win if cap_win else (0.0, cap_secs)
        b = min(b, dur) if dur else b
        fades = ""
        if a > 0.05:
            fades += f",fade=t=in:st={a:.2f}:d=0.3:alpha=1"
        if b < 1e5 and (not dur or b < dur - 0.1):
            fades += f",fade=t=out:st={max(a, b - 0.4):.2f}:d=0.4:alpha=1"
        f += (f";[1:v]format=rgba{fades}[cap];"
              f"[base][cap]overlay=0:{y}:shortest=1:enable='between(t,{a:.2f},{b:.2f})'[v0]")
    else:
        f += ";[base]null[v0]"
    if sub_idx is not None:          # legenda palavra por palavra
        f += f";[{sub_idx}:v]format=rgba[subs];[v0][subs]overlay=0:{int(sub_y)}:eof_action=pass[v0s]"
    else:
        f += ";[v0]null[v0s]"
    if wm_idx is not None:   # marca d'água por cima de tudo, o corte inteiro
        x = f"{int(wm_xc)}-w/2" if wm_xc is not None else "(W-w)/2"
        f += f";[{wm_idx}:v]{wm_pre}format=rgba[wm];[v0s][wm]overlay='max(0,min(W-w,{x}))':'max(0,min(H-h,{wm_y}))':shortest=1[v1]"
    else:
        f += ";[v0s]null[v1]"
    # escurece suavemente no último meio segundo, pro corte não acabar do nada
    f += f";[v1]fade=t=out:st={max(0.0, dur - 0.6):.2f}:d=0.6[v]" if dur > 3 else ";[v1]null[v]"
    return f


def make_vertical(h_path, out, thumb, cam=None, caption="", cap_secs=10, layout="auto", watermark=None,
                  trim=None, cap_win=None, cap_y=None, wm_pos=None, audio_mode="auto", subs=None, sub_y=None, zooms=None):
    """
    Monta o vertical. layout: 'auto' (decide sozinho), 'cam', 'full' ou 'game'. Retorna o formato usado.
    trim: (início, fim) em segundos dentro do corte · cap_win: (aparece, some) do texto, contando do início do corte
    cap_y: centro da faixa (0 a 1 da altura) · wm_pos: (x, y) do centro da marca d'água (0 a 1)
    """
    vw, vh, full = probe(h_path)
    ts, te = (trim or (0, full))
    ts, te = max(0.0, ts or 0.0), min(full, te or full)
    if te - ts < 1:
        ts, te = 0.0, full
    dur = te - ts
    make_vertical.last_cam = None
    if layout == "auto":
        layout, focus_x, auto_cam = detect_layout(h_path, cam)
        if auto_cam:
            cam = auto_cam
            make_vertical.last_cam = auto_cam      # o programa achou a webcam sozinho
    else:
        focus_x = 0.5
        if layout == "full":
            found, fx, _ = detect_layout(h_path, None)
            focus_x = fx if found == "full" else (cam["x"] + cam["w"] / 2 if cam else 0.5)
        if layout == "cam" and not cam:
            found, _, auto_cam = detect_layout(h_path, None)
            if auto_cam:
                cam = auto_cam
                make_vertical.last_cam = auto_cam
            else:
                layout = "game"
    cap_png = Path(out).with_suffix(".faixa.png")
    cap_h = caption_png(caption, cap_png) if caption else 0
    cap_secs = 1e9 if cap_secs > 40 else cap_secs
    if cap_win:
        a, b = max(0.0, cap_win[0] or 0.0), cap_win[1] if cap_win[1] is not None else 1e9
        cap_win = (min(a, dur), max(min(b, dur if b < 1e5 else b), min(a, dur) + 0.5))
    wm_png = Path(out).with_suffix(".marca.png")
    wm_idx, wm_y, wm_xc, wm_pre, wm_args = None, 0, None, "", []
    if isinstance(watermark, Path):      # Lower do campeonato (imagem ou vídeo), sem fundo e recortado
        wm_args, (lw, lh) = lower_input(watermark, dur)
        info = lower_info(watermark)
        full_design = lh / lw > 1.2      # feito pra tela inteira em pé: mantém o tamanho do desenho original
        tw = W * info["wfrac"] if full_design else W * 0.86
        th = tw * info["box"][3] / max(1, info["box"][2])
        wx, wy = wm_pos if wm_pos else ((info["cx"], info["cy"]) if full_design else (0.5, 0.80))
        wm_pre, wm_y, wm_xc = lower_filter(info, tw), int(H * wy - th / 2), W * wx
        wm_idx = 2 if cap_h else 1
    elif watermark:
        _, wm_h = watermark_png(watermark, wm_png, W, frac=0.052)   # grande o bastante pra ler no celular
        wx, wy = wm_pos if wm_pos else (0.5, 0.80)
        wm_idx, wm_y, wm_xc = (2 if cap_h else 1), int(H * wy) - wm_h // 2, W * wx
        wm_args = ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(wm_png)]
    sub_args, sub_files, sub_idx, sub_yc = [], [], None, None
    st = subs_track(subs, ts, te, Path(out).with_suffix("")) if subs else None
    if st:
        lst, sh, sub_files = st
        sub_idx = 1 + (1 if cap_h else 0) + (1 if wm_args else 0)
        sub_args = ["-f", "concat", "-safe", "0", "-i", str(lst)]
        # lugar padrão: no meio da gameplay (sem brigar com a faixa do título nem com a marca d'água)
        yc = sub_y if sub_y is not None else (0.56 if layout == "full" else 0.64)
        sub_yc = max(0, min(H - sh, int(H * yc - sh / 2)))
    flt = vertical_filter(vw, vh, layout, cam, focus_x, cap_h, cap_secs, dur, wm_idx, wm_y,
                          cap_win=cap_win, cap_yc=(cap_y * H if cap_y is not None else None), wm_xc=wm_xc, wm_pre=wm_pre,
                          zooms=[z for z in (zooms or []) if z < dur - 1], fps=fps_of(h_path) if zooms else "30",
                          sub_idx=sub_idx, sub_y=sub_yc)
    afx, ainfo = audio_fix(h_path, ts, dur, audio_mode)
    afx += [f"afade=t=out:st={max(0.0, dur - 0.6):.2f}:d=0.6"] if dur > 3 else []
    afade = ["-af", ",".join(afx)] if afx else []
    inputs = ["-ss", f"{ts:.2f}", "-t", f"{dur:.2f}", "-i", str(h_path)]
    if cap_h:
        inputs += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(cap_png)]
    inputs += wm_args + sub_args
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", flt,
             "-map", "[v]", "-map", "0:a:0?", *venc(), *afade, *AENC, "-movflags", "+faststart", str(out)],
            timeout=1800)
        thumb_t = ((cap_win[0] if cap_win else 0) + 1.0) if cap_h else dur * 0.6
        frame_jpg(out, thumb, t=min(thumb_t, max(0.5, dur - 0.5)), width=360)
    finally:
        cap_png.unlink(missing_ok=True)
        wm_png.unlink(missing_ok=True)
        for f in sub_files:
            Path(f).unlink(missing_ok=True)
    make_vertical.last_audio = ainfo
    return layout
