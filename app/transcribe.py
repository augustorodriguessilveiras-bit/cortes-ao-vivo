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
_lock = threading.Lock()
MODEL = "base"  # leve (~150 MB). Baixa sozinho na primeira vez.


def available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(path):
    """Retorna [(inicio, fim, texto)] em segundos, [] se ninguém falou, ou None se não deu pra ouvir."""
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
                                        condition_on_previous_text=False)
            return [(float(s.start), float(s.end), s.text.strip()) for s in segs if s.text.strip()]
    except Exception as e:
        _failed = True
        log.warning("⚠ O reconhecimento de fala não funcionou (%s). Os cortes continuam saindo normalmente, só sem ouvir a fala.", str(e)[:120])
        return None
