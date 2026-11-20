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
    Decide o que fazer com o volume do corte:
      - áudio bom: não mexe (som original da live)
      - muito baixo: aumenta até um volume normal, sem estourar
      - alto demais / batendo no limite: segura só os picos pra não sair estourado
    Retorna (lista de filtros de áudio do ffmpeg, explicação).
    """
    if mode == "off":
        return [], "áudio original"
    try:
        seek = ["-ss", f"{ts:.2f}"] + (["-t", f"{dur:.2f}"] if dur else [])
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *seek, "-i", str(src), "-vn",
                            "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, creationflags=NO_WINDOW, timeout=300)
        j = json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1])
        lufs, peak = float(j["input_i"]), float(j["input_tp"])
    except Exception:
        return [], "áudio original"
    if lufs == float("-inf") or lufs < -60:
        return [], "áudio original"
    limiter = "alimiter=limit=0.89:attack=5:release=60:level=0"   # nada passa de -1 dB
    if lufs < -28:                                   # muito baixo mesmo: sobe pra um volume normal (no máximo +10 dB)
        gain = min(10.0, -18.0 - lufs)
        return [f"volume={gain:.1f}dB", limiter], f"áudio baixo: aumentado {gain:.0f} dB"
    if lufs > -10:                                   # alto demais: abaixa um pouco
        gain = -14.0 - lufs
        return [f"volume={gain:.1f}dB", limiter], f"áudio muito alto: abaixado {abs(gain):.0f} dB"
    if peak > -1.0:                                  # volume bom, mas os gritos batem no limite
        return [limiter], "picos do áudio segurados pra não estourar"
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
        if isinstance(text, Path):          # Lower (imagem/vídeo do campeonato)
            args, (lw, lh) = lower_input(text, dur)
            inputs += args
            if lh / lw > 1.2:                # Lower feito pra tela inteira em pé: centraliza na altura
                flt = f"[1:v]scale=-2:{even(vh)},format=rgba[lw];[0:v][lw]overlay=(W-w)/2:0:shortest=1[v]"
            else:
                tw = even(vw * 0.45)
                flt = f"[1:v]scale={tw}:-2,format=rgba[lw];[0:v][lw]overlay=(W-w)/2:H-h-H*0.04:shortest=1[v]"
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


def vertical_filter(vw, vh, layout, cam, focus_x, cap_h, cap_secs, dur=0, wm_idx=None, wm_y=0,
                    cap_win=None, cap_yc=None, wm_xc=None, wm_pre=""):
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
    if wm_idx is not None:   # marca d'água por cima de tudo, o corte inteiro
        x = f"{int(wm_xc)}-w/2" if wm_xc is not None else "(W-w)/2"
        f += f";[{wm_idx}:v]{wm_pre}format=rgba[wm];[v0][wm]overlay='max(0,min(W-w,{x}))':'max(0,min(H-h,{wm_y}))':shortest=1[v1]"
    else:
        f += ";[v0]null[v1]"
    # escurece suavemente no último meio segundo, pro corte não acabar do nada
    f += f";[v1]fade=t=out:st={max(0.0, dur - 0.6):.2f}:d=0.6[v]" if dur > 3 else ";[v1]null[v]"
    return f


def make_vertical(h_path, out, thumb, cam=None, caption="", cap_secs=10, layout="auto", watermark=None,
                  trim=None, cap_win=None, cap_y=None, wm_pos=None, audio_mode="auto"):
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
    if cap_win:
        a, b = max(0.0, cap_win[0] or 0.0), cap_win[1] if cap_win[1] is not None else 1e9
        cap_win = (min(a, dur), max(min(b, dur if b < 1e5 else b), min(a, dur) + 0.5))
    wm_png = Path(out).with_suffix(".marca.png")
    wm_idx, wm_y, wm_xc, wm_pre, wm_args = None, 0, None, "", []
    if isinstance(watermark, Path):      # Lower do campeonato (imagem ou vídeo)
        wm_args, (lw, lh) = lower_input(watermark, dur)
        wx, wy = wm_pos if wm_pos else (0.5, 0.80)
        if lh / lw > 1.2:                # feito pra tela inteira em pé
            wm_pre, wm_y, wm_xc = f"scale={W}:{H},", 0, None
        else:
            tw = even(W * 0.86)
            th = int(tw * lh / lw)
            wm_pre, wm_y, wm_xc = f"scale={tw}:-2,", int(H * wy) - th // 2, W * wx
        wm_idx = 2 if cap_h else 1
    elif watermark:
        _, wm_h = watermark_png(watermark, wm_png, W, frac=0.052)   # grande o bastante pra ler no celular
        wx, wy = wm_pos if wm_pos else (0.5, 0.80)
        wm_idx, wm_y, wm_xc = (2 if cap_h else 1), int(H * wy) - wm_h // 2, W * wx
        wm_args = ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(wm_png)]
    flt = vertical_filter(vw, vh, layout, cam, focus_x, cap_h, cap_secs, dur, wm_idx, wm_y,
                          cap_win=cap_win, cap_yc=(cap_y * H if cap_y is not None else None), wm_xc=wm_xc, wm_pre=wm_pre)
    afx, ainfo = audio_fix(h_path, ts, dur, audio_mode)
    afx += [f"afade=t=out:st={max(0.0, dur - 0.6):.2f}:d=0.6"] if dur > 3 else []
    afade = ["-af", ",".join(afx)] if afx else []
    inputs = ["-ss", f"{ts:.2f}", "-t", f"{dur:.2f}", "-i", str(h_path)]
    if cap_h:
        inputs += ["-loop", "1", "-t", f"{dur:.2f}", "-i", str(cap_png)]
    inputs += wm_args
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", flt,
             "-map", "[v]", "-map", "0:a:0?", *venc(), *afade, *AENC, "-movflags", "+faststart", str(out)],
            timeout=1800)
        thumb_t = ((cap_win[0] if cap_win else 0) + 1.0) if cap_h else dur * 0.6
        frame_jpg(out, thumb, t=min(thumb_t, max(0.5, dur - 0.5)), width=360)
    finally:
        cap_png.unlink(missing_ok=True)
        wm_png.unlink(missing_ok=True)
    make_vertical.last_audio = ainfo
    return layout
