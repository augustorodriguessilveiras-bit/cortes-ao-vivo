"""Leitura do chat da Twitch (anônimo, sem precisar de conta ou chave)."""
import logging
import re
import socket
import threading
import time
from collections import defaultdict, deque

log = logging.getLogger("chat")

# Mensagens que indicam um momento bom
HYPE = re.compile(
    r"(k{3,}|ha(ha)+|rs(rs)+|lul|kekw|omegalul|icant|pog|clip|corta|cortes|"
    r"monka|wtf|caralho|mds|meu deus|nossa|aaa+|lmao|lol|😂|🤣|💀|\?\?\?|!!!)",
    re.IGNORECASE,
)


class TwitchChat(threading.Thread):
    def __init__(self, channel: str):
        super().__init__(daemon=True)
        self.channel = channel.lower()
        self.msgs = defaultdict(int)   # segundo -> nº de mensagens
        self.hype = defaultdict(int)   # segundo -> nº de mensagens "hype"
        self.lines = deque(maxlen=30000)  # (horário, texto) p/ título e descrição
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def window(self, start: int, end: int):
        """(mensagens, mensagens hype) entre start e end (segundos epoch)."""
        m = sum(self.msgs.get(s, 0) for s in range(start, end))
        h = sum(self.hype.get(s, 0) for s in range(start, end))
        return m, h

    def prune(self, before: int):
        for d in (self.msgs, self.hype):
            for k in [k for k in d if k < before]:
                d.pop(k, None)
        while self.lines and self.lines[0][0] < before:
            self.lines.popleft()

    def between(self, a, b):
        return [t for ts, t in list(self.lines) if a <= ts < b]

    def run(self):
        while not self._stop.is_set():
            try:
                self._loop()
            except Exception as e:  # reconecta
                log.warning("chat %s: %s", self.channel, e)
            self._stop.wait(5)

    def _loop(self):
        s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
        s.sendall(b"NICK justinfan%d\r\n" % (int(time.time()) % 100000))
        s.sendall(f"JOIN #{self.channel}\r\n".encode())
        buf = b""
        try:
            while not self._stop.is_set():
                try:
                    data = s.recv(8192)
                except socket.timeout:
                    s.sendall(b"PING :tmi.twitch.tv\r\n")
                    continue
                if not data:
                    return
                buf += data
                *lines, buf = buf.split(b"\r\n")
                for raw in lines:
                    line = raw.decode("utf-8", "ignore")
                    if line.startswith("PING"):
                        s.sendall(b"PONG :tmi.twitch.tv\r\n")
                    elif " PRIVMSG " in line:
                        text = line.split(" :", 1)[-1]
                        sec = int(time.time())
                        self.msgs[sec] += 1
                        self.lines.append((time.time(), text))
                        if HYPE.search(text):
                            self.hype[sec] += 1
        finally:
            s.close()
