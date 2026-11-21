"""Ajustes que dá pra mudar pelo painel (salvos em dados/ajustes.json)."""
import json
import threading

from . import config as C

DEFAULTS = {
    "min_score": C.MIN_SCORE,          # nota mínima pra cortar sozinho
    "dur": 60,                         # duração total do corte (segundos); 2/3 antes do pico, 1/3 depois
    "cooldown": C.COOLDOWN_SECONDS,    # intervalo mínimo entre cortes da mesma live
    "ov_on": True,                     # faixa branca com título dentro do vídeo
    "ov_secs": 10,                     # por quantos segundos (41 = vídeo todo)
    "tags": "#gta6 #gtavi #gta #gta6brasil #cortes #cortesdelive #fyp #viral",
    "vod_max": 15,                     # máximo de cortes por VOD
    "discard_below": 5.0,              # descarta sozinho cortes com nota final abaixo disso (0 = nunca)
    "posted_cleanup": True,            # ao marcar "postado", apaga os vídeos pra liberar espaço
    "audio_mode": "auto",              # auto: só mexe se estiver muito baixo ou estourando · off: nunca mexe
    "pad": 30,                         # sobra guardada antes e depois do corte (pra puxar mais no editor)
    "style": "padrao",                 # estilo dos cortes novos: padrao · dinamico (legenda, zoom e começo/fim esperto)
}
_lock = threading.Lock()


def get_all():
    data = dict(DEFAULTS)
    try:
        data.update({k: v for k, v in json.loads(C.SETTINGS_PATH.read_text(encoding="utf-8")).items() if k in DEFAULTS})
    except Exception:
        pass
    dur = max(20, min(90, int(data["dur"])))
    data["dur"] = dur
    data["before"] = round(dur * 2 / 3)        # mais tempo antes: o corte mostra o que levou ao momento
    data["after"] = dur - data["before"]
    return data


def get(key):
    return get_all()[key]


def update(changes: dict):
    with _lock:
        data = {k: v for k, v in get_all().items() if k in DEFAULTS}
        for k, v in changes.items():
            if k in DEFAULTS:
                data[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], bool) else bool(v)
        if data.get("style") not in ("padrao", "dinamico"):
            data["style"] = "padrao"
        data["pad"] = max(0, min(60, int(data.get("pad", 30))))
        if data.get("audio_mode") not in ("auto", "off"):
            data["audio_mode"] = "auto"
        C.SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return get_all()
