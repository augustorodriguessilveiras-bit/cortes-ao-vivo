"""
Garante que os gravadores (ffmpeg/streamlink) fecham junto com o programa.

No Windows, quando a janela preta é fechada, os programas que o Cortes ao Vivo abriu continuavam rodando
escondidos (gravando e travando arquivos). Aqui o programa entra num "Job" do Windows marcado pra
encerrar tudo junto: quando ele fecha, o Windows fecha todos os gravadores que ele abriu.
"""
import logging
import os
from pathlib import Path

log = logging.getLogger("painel")
_job = None


def tie_children_to_me():
    """Chamar uma vez no começo do programa. Não faz nada fora do Windows."""
    global _job
    if os.name != "nt" or _job:
        return
    try:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        k32.GetCurrentProcess.restype = wintypes.HANDLE

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000           # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):   # 9 = ExtendedLimitInformation
            return
        if k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            _job = job   # guardar o handle: quando o programa fechar, o Windows fecha o Job e todos os gravadores
    except Exception as e:   # se não der, o INICIAR.bat ainda limpa os que sobrarem
        log.debug("não deu pra ligar os gravadores ao programa: %s", e)


def lower_my_priority():
    """
    O programa (ouvir a fala, montar os vídeos) roda com prioridade BAIXA no Windows: usa só a sobra do processador,
    e o PC continua liso pra você. A gravação das lives é aberta com prioridade normal (não perde nada).
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00004000)     # BELOW_NORMAL_PRIORITY_CLASS
    except Exception as e:
        log.debug("não deu pra baixar a prioridade: %s", e)


def safe_unlink(path):
    """Apaga sem quebrar se o Windows disser que o arquivo está em uso."""
    try:
        Path(path).unlink(missing_ok=True)
        return True
    except OSError:
        return False
