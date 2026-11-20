"""Ajustes que dá pra mudar pelo painel (salvos em dados/ajustes.json)."""
import json
import threading

from . import config as C

DEFAULTS = {
    "min_score": C.MIN_SCORE,          # nota mínima pra cortar sozinho
    "before": C.CLIP_BEFORE,           # segundos antes do pico
    "after": C.CLIP_AFTER,             # segundos depois do pico
    "cooldown": C.COOLDOWN_SECONDS,    # intervalo mínimo entre cortes da mesma live
    "ov_on": True,                     # faixa branca com título dentro do vídeo
    "ov_secs": 10,                     # por quantos segundos (41 = vídeo todo)
    "tags": "#gta6 #gtavi #gta #gta6brasil #cortes #cortesdelive #fyp #viral",
    "vod_max": 15,                     # máximo de cortes por VOD
}
_lock = threading.Lock()


def get_all():
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(C.SETTINGS_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return data


def get(key):
    return get_all()[key]


def update(changes: dict):
    with _lock:
        data = get_all()
        for k, v in changes.items():
            if k in DEFAULTS:
                data[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], bool) else bool(v)
        C.SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return data
