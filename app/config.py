import os
from pathlib import Path

# Lê o arquivo .env da pasta do projeto (no PC; no Docker ele já vem pelo compose)
_env = Path(__file__).resolve().parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _k, _, _v = _line.partition("=")
        if _k.strip() and not _k.strip().startswith("#") and _:
            os.environ.setdefault(_k.strip(), _v.strip())


def _int(name, default):
    return int(os.getenv(name, default))


DATA_DIR = Path(os.getenv("DATA_DIR", "./dados")).resolve()
# As gravações temporárias podem ficar fora do DATA_DIR (ex: DATA_DIR no Google Drive
# e as gravações no disco local, pra não ficar sincronizando vídeo bruto)
SEGMENTS_DIR = Path(os.getenv("SEGMENTS_DIR", "") or DATA_DIR / "gravacoes").resolve()
CLIPS_DIR = DATA_DIR / "cortes"
DB_PATH = DATA_DIR / "banco.sqlite3"

# Quantos minutos de cada live ficam guardados (o resto é apagado sozinho)
BUFFER_MINUTES = _int("BUFFER_MINUTES", 20)
# Tamanho de cada pedaço de gravação
SEGMENT_SECONDS = _int("SEGMENT_SECONDS", 10)
# Segundos antes/depois do pico que entram no corte
CLIP_BEFORE = _int("CLIP_BEFORE", 25)
CLIP_AFTER = _int("CLIP_AFTER", 12)
# Tempo mínimo entre dois cortes automáticos da mesma live
COOLDOWN_SECONDS = _int("COOLDOWN_SECONDS", 90)
# Nota mínima (0 a 10) para virar corte automático
MIN_SCORE = float(os.getenv("MIN_SCORE", "6.5"))
# A cada quantos segundos verifica se um canal offline entrou ao vivo
CHECK_INTERVAL = _int("CHECK_INTERVAL", 60)
# Qualidade preferida (a primeira disponível é usada)
QUALITY = os.getenv("QUALITY", "1080p60,1080p,720p60,720p,best")

# Senha do painel (deixe vazio só se rodar no seu PC)
PANEL_USER = os.getenv("PANEL_USER", "admin")
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")

VODS_DIR = DATA_DIR / "vods"
SETTINGS_PATH = DATA_DIR / "ajustes.json"

for d in (SEGMENTS_DIR, CLIPS_DIR, VODS_DIR):
    d.mkdir(parents=True, exist_ok=True)
