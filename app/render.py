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


# ------------------------------------------------------------ formato do vertical
LAYOUTS = {"cam": "Câmera em cima + gameplay", "full": "Tela cheia", "game": "Só gameplay"}


def detect_layout(h_path, cam):
    """
    Olha alguns quadros do corte e decide o formato:
      - 'full': o rosto do streamer aparece grande e fora da caixinha da webcam (full cam / só a câmera)
      - 'cam' : gameplay com a webcam no canto (precisa da câmera marcada)
      - 'game': só gameplay
    Retorna (formato, posição horizontal do rosto de 0 a 1).
    """
    default = ("cam" if cam else "game"), 0.5
    try:
        import cv2
    except ImportError:
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


def vertical_filter(vw, vh, layout, cam, focus_x, cap_h, cap_secs):
    """Monta o filtro do ffmpeg pro formato escolhido, com a faixa do título se tiver."""
    if layout == "full":
        # tela cheia: recorte vertical da imagem inteira, centrado no streamer
        cw = min(even(vh * W / H), even(vw))
        cx = min(max(0, focus_x * vw - cw / 2), vw - cw)
        f = f"[0:v]crop={cw}:{even(vh)}:{int(cx)}:0,scale={W}:{H},setsar=1[base]"
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
        f = (f"[0:v]split=2[a][b];[a]{crop(a)},scale={W}:{th},setsar=1[top];"
             f"[b]{crop(g)},scale={W}:{bh},setsar=1[bot];"
             f"[top][bot]vstack=2,drawbox=x=0:y={th - 3}:w={W}:h=6:color=black:t=fill[base]")
        y = th - cap_h // 2
    else:
        fit_h = even(W * vh / vw)
        f = (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
             f"boxblur=25:5,eq=brightness=-0.08[bg];[b]scale={W}:{fit_h},setsar=1[fg];"
             f"[bg][fg]overlay=0:{(H - fit_h) // 2}[base]")
        y = (H - fit_h) // 2 - cap_h // 2
    if cap_h:
        fade = f",fade=t=out:st={max(0.1, cap_secs - 0.4):.2f}:d=0.4:alpha=1" if cap_secs < 1e5 else ""
        f += f";[1:v]format=rgba{fade}[cap];[base][cap]overlay=0:{max(0, y)}:shortest=1[v]"
    else:
        f += ";[base]null[v]"
    return f


def make_vertical(h_path, out, thumb, cam=None, caption="", cap_secs=10, layout="auto"):
    """Monta o vertical. layout: 'auto' (decide sozinho), 'cam', 'full' ou 'game'. Retorna o formato usado."""
    vw, vh, dur = probe(h_path)
    if layout == "auto":
        layout, focus_x = detect_layout(h_path, cam)
    else:
        focus_x = 0.5
        if layout == "full":
            found, fx = detect_layout(h_path, None)
            focus_x = fx if found == "full" else (cam["x"] + cam["w"] / 2 if cam else 0.5)
        if layout == "cam" and not cam:
            layout = "game"
    cap_png = Path(out).with_suffix(".faixa.png")
    cap_h = caption_png(caption, cap_png) if caption else 0
    cap_secs = 1e9 if cap_secs > 40 else cap_secs
    flt = vertical_filter(vw, vh, layout, cam, focus_x, cap_h, cap_secs)
    inputs = ["-i", str(h_path)]
    if cap_h:
        inputs += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(cap_png)]
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", flt,
             "-map", "[v]", "-map", "0:a:0?", *venc(), "-c:a", "copy", "-movflags", "+faststart", str(out)],
            timeout=1800)
        frame_jpg(out, thumb, t=1.5 if cap_h else dur * 0.6, width=360)
    finally:
        cap_png.unlink(missing_ok=True)
    return layout
