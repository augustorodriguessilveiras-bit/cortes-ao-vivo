"""
Ouve o que o streamer fala no corte (reconhecimento de fala grátis, roda no próprio PC).
Serve pra deixar o texto do vídeo e o título ligados ao que acontece no corte.
Se o componente não estiver instalado, o programa funciona igual, só sem essa parte.
"""
import logging
import threading

log = logging.getLogger("recorder")
_model = None
_failed = False
_error = ""
_lock = threading.Lock()
MODEL = "base"  # leve (~150 MB). Baixa sozinho na primeira vez.


def status():
    """Pro painel: o reconhecimento de fala está funcionando?"""
    from . import config as C
    if not available():
        log_txt = ""
        try:
            log_txt = (C.DATA_DIR / "fala_instalacao.log").read_text(encoding="utf-8", errors="ignore").strip()[-400:]
        except OSError:
            pass
        return {"state": "nao_instalado", "error": log_txt}
    if _failed:
        return {"state": "erro", "error": _error}
    return {"state": "pronto" if _model is not None else "instalado", "error": ""}


def retry():
    """Tenta de novo depois de um erro (ex: a internet caiu enquanto baixava o modelo)."""
    global _failed, _error
    _failed, _error = False, ""


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(path):
    """Retorna [(inicio, fim, texto)] em segundos, [] se ninguém falou, ou None se não deu pra ouvir."""
    r = transcribe_words(path)
    return None if r is None else r[0]


def transcribe_words(path):
    """Igual ao transcribe, mas também com o tempo de cada palavra: (frases, [(inicio, fim, palavra)]) ou None."""
    global _model, _failed
    if _failed or not available():
        return None
    try:
        with _lock:
            if _model is None:
                from faster_whisper import WhisperModel
                log.info("🗣 Preparando o reconhecimento de fala (na 1ª vez baixa ~150 MB, pode demorar uns minutos)…")
                _model = WhisperModel(MODEL, device="cpu", compute_type="int8")
            segs, _ = _model.transcribe(str(path), language="pt", vad_filter=True, beam_size=1,
                                        condition_on_previous_text=False, word_timestamps=True)
            lines, words = [], []
            for s in segs:
                if s.text.strip():
                    lines.append((float(s.start), float(s.end), s.text.strip()))
                for w in (s.words or []):
                    if w.word.strip():
                        words.append((round(float(w.start), 2), round(float(w.end), 2), w.word.strip()))
            return lines, words
    except Exception as e:
        global _error
        _failed = True
        _error = str(e)[:300]
        log.warning("⚠ O reconhecimento de fala não funcionou (%s). Os cortes continuam saindo normalmente, só sem ouvir a fala.", str(e)[:120])
        return None
