"""
Leitura do chat da Kick (anônimo, sem conta). Mesmo jeito de usar do chat da Twitch:
  window(início, fim) -> (mensagens, mensagens de hype) · between(a, b) -> textos · prune(antes)

Como funciona: a Kick manda o chat por um servidor "Pusher". Descobrimos o número da sala de chat do canal
(pela API da Kick) e ficamos ouvindo as mensagens dela.
"""
import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque

from .chat import HYPE

log = logging.getLogger("chat")

PUSHER_KEY = "32cbd69e4b950bf97679"
PUSHER_URL = f"wss://ws-us2.pusher.com/app/{PUSHER_KEY}?protocol=7&client=js&version=8.4.0&flash=false"


def chatroom_id(slug):
    """Número da sala de chat do canal (a API da Kick precisa parecer um navegador de verdade)."""
    from curl_cffi import requests
    r = requests.get(f"https://kick.com/api/v2/channels/{slug}", impersonate="chrome", timeout=20)
    r.raise_for_status()
    return int(r.json()["chatroom"]["id"])


class KickChat(threading.Thread):
    def __init__(self, channel: str, url=PUSHER_URL, room=None):
        super().__init__(daemon=True)
        self.channel = channel.lower()
        self.url = url
        self.room = room
        self.msgs = defaultdict(int)
        self.hype = defaultdict(int)
        self.lines = deque(maxlen=30000)
        self.status = "conectando"
        self.total = 0
        self._stop = threading.Event()

    # ---- mesma interface do chat da Twitch
    def stop(self):
        self._stop.set()

    def window(self, start: int, end: int):
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

    # ---- recebendo
    def add(self, text):
        sec = int(time.time())
        self.msgs[sec] += 1
        self.total += 1
        self.lines.append((time.time(), text))
        if HYPE.search(text):
            self.hype[sec] += 1

    def run(self):
        fails = 0
        while not self._stop.is_set():
            try:
                if self.room is None:
                    self.room = chatroom_id(self.channel)
                asyncio.run(self._listen())
                fails = 0
            except Exception as e:
                fails += 1
                self.status = f"sem chat ({str(e)[:60]})"
                if fails in (1, 5):
                    log.info("💬 %s: não consegui ler o chat da Kick agora (%s). Os cortes continuam pelo áudio e pela fala.",
                             self.channel, str(e)[:80])
            self._stop.wait(min(300, 10 * fails))

    async def _listen(self):
        import websockets
        async with websockets.connect(self.url, open_timeout=20, ping_interval=None, max_size=2 ** 20) as ws:
            await ws.send(json.dumps({"event": "pusher:subscribe",
                                      "data": {"auth": "", "channel": f"chatrooms.{self.room}.v2"}}))
            last_ping = time.time()
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    raw = None
                if time.time() - last_ping > 60:          # mantém a conexão viva
                    await ws.send(json.dumps({"event": "pusher:ping", "data": {}}))
                    last_ping = time.time()
                if raw is None:
                    continue
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                name = ev.get("event", "")
                if name == "pusher_internal:subscription_succeeded":
                    if self.status != "conectado":
                        log.info("💬 %s: lendo o chat da Kick", self.channel)
                    self.status = "conectado"
                elif name.endswith("ChatMessageEvent"):
                    try:
                        data = ev.get("data")
                        data = json.loads(data) if isinstance(data, str) else (data or {})
                        text = str(data.get("content") or "")
                    except ValueError:
                        continue
                    if text:
                        self.add(text)
                elif name == "pusher:error":
                    raise RuntimeError(str(ev.get("data"))[:80])
