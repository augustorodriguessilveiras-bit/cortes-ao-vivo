"""Título, descrição e hashtags de cada corte, a partir do que o chat escreveu."""
import random
import re
import unicodedata
from collections import Counter

from . import rules, settings

# Tipo de momento, reconhecido pelas mensagens do chat logo depois dele
CATS = {
    "policia": dict(re=r"(pol[ií]cia|persegui[çc][aã]o|fuga|fugiu|estrelas?|procurado|swat|viatura|cops|preso|pris[aã]o)",
                    lead="Perseguição insana", tags=["#perseguicao", "#policia", "#fuga"],
                    titles=["A FUGA MAIS INSANA DO {N} NO GTA 6 🚓", "{N} VS A POLÍCIA INTEIRA 🚨", "5 ESTRELAS: {N} ENLOUQUECEU NO GTA 6 🚓",
                            "A POLÍCIA DO GTA 6 NÃO DEU PAZ PRO {N} 🚨", "{N} FUGINDO DA POLÍCIA IGUAL FILME 🎬", "NINGUÉM SEGURA O {N} NO GTA 6 🚓",
                            "O {N} VIROU O MAIS PROCURADO DE LEONIDA 🚨", "PERSEGUIÇÃO ABSURDA COM O {N} 🚓"]),
    "fail": dict(re=r"(^f+$|^f\s|\brip\b|morreu|morre|wasted|noob|^-1|perdeu tudo|que burro|burr[oa]|errou|eliminad)",
                 lead="O fail", tags=["#fail", "#gtafail", "#wasted"],
                 titles=["{N} MORREU DO JEITO MAIS BURRO 💀", "F NO CHAT PRO {N} 😭 GTA 6", "{N} PERDEU TUDO EM 1 SEGUNDO 💀",
                         "O MAIOR FAIL DO {N} NO GTA 6 😭", "WASTED: O {N} NÃO ACREDITOU 💀", "ERA SÓ NÃO FAZER ISSO, {N} 😭",
                         "O {N} SE SABOTOU NO GTA 6 💀", "DEU TUDO ERRADO PRO {N} 😂", "O {N} TINHA TUDO PRA DAR CERTO... 💀"]),
    "epico": dict(re=r"(pog|insan[oa]|brab[oa]|monstro|absurd[oa]|\bclip|clipa|🔥|que isso|goat|lenda|\bgg\b|mito|jogou muito)",
                  lead="Jogada insana", tags=["#insano", "#epico", "#jogadaincrivel"],
                  titles=["{N} FEZ O IMPOSSÍVEL NO GTA 6 🔥", "JOGADA INSANA DO {N} NO GTA 6 😱", "O CHAT PEDIU CLIP: {N} FOI BRABO 🔥",
                          "O {N} JOGA MUITO, OLHA ISSO 🔥", "ISSO FOI DE OUTRO NÍVEL, {N} 🐐", "O {N} ACERTOU A MAIS DIFÍCIL DO GTA 6",
                          "NINGUÉM FAZ ISSO IGUAL O {N} 🔥", "O {N} DEU AULA DE GTA 6 📚", "MOMENTO LENDÁRIO DO {N} NO GTA VI 🏆"]),
    "susto": dict(re=r"(wtf|monka|caralho|\bmds\b|meu deus|nossa|\boq\b|o que foi|\?\?\?|😱|susto|medo|jumpscare)",
                  lead="A reação", tags=["#susto", "#reacao", "#wtf"],
                  titles=["{N} TOMOU O SUSTO DA VIDA 😱", "O QUE ACONTECEU AQUI, {N}?! 😳", "A REAÇÃO DO {N} FOI SURREAL 😳",
                          "O {N} PULOU DA CADEIRA 😱", "NINGUÉM ESPERAVA ISSO, NEM O {N} 😳", "O GTA 6 ASSUSTOU O {N} 😱",
                          "O {N} FICOU SEM PALAVRAS 😶", "ISSO DEU MEDO ATÉ NO {N} 😨"]),
    "engracado": dict(re=r"(k{3,}|ha(ha)+|rs(rs)+|\blul\b|kekw|omegalul|icant|😂|🤣|💀|lmao)",
                      lead="Momento hilário", tags=["#humor", "#engracado", "#comedia"],
                      titles=["{N} NÃO AGUENTOU 😂 GTA 6", "O CHAT CHOROU DE RIR COM {N} 😂", "NINGUÉM ESPERAVA ISSO DO {N} 💀",
                              "O {N} PASSOU VERGONHA NO GTA 6 🤣", "ISSO SÓ ACONTECE COM O {N} 😂", "O {N} CHOROU DE RIR AQUI 🤣",
                              "MOMENTO MAIS ENGRAÇADO DA LIVE DO {N} 😂", "O GTA 6 ZOOU O {N} KKKKKKK", "O {N} NÃO SABIA SE RIA OU CHORAVA 😂"]),
    "geral": dict(re=None, lead="Melhor momento", tags=["#reacao", "#momentos"],
                  titles=["{N} PERDEU A CABEÇA NO GTA 6 🤯", "O MOMENTO MAIS INSANO DA LIVE DO {N}", "OLHA O QUE O {N} FEZ NO GTA 6 👀",
                          "O {N} NÃO ESPERAVA POR ISSO NO GTA VI 😳", "NINGUÉM ESTAVA PREPARADO PRA ISSO ({N}) 😳",
                          "OLHA O QUE ACONTECEU COM O {N} NO GTA 6 👀", "ISSO SÓ ACONTECE NA LIVE DO {N} 😂", "{N} SURTOU AO VIVO NO GTA 6 😱",
                          "O GTA 6 TROLLOU O {N} 💀", "O {N} NÃO ACREDITOU NO QUE VIU NO GTA VI", "A REAÇÃO DO {N} FOI TUDO 😂",
                          "O MOMENTO MAIS ALEATÓRIO DA LIVE DO {N}", "O {N} DESCOBRIU ISSO NO GTA 6 E SURTOU 🤯", "{N} PASSOU DO LIMITE NO GTA VI 💀",
                          "QUANDO O GTA 6 RESOLVE ZOAR O {N} 😂", "NINGUÉM ENTENDEU NADA NA LIVE DO {N} 😂", "O {N} VIVENDO O CAOS NO GTA 6 🔥",
                          "ATÉ O {N} FICOU CHOCADO COM O GTA 6", "O GTA 6 NÃO PERDOA NINGUÉM, NEM O {N} 💀", "SÓ O {N} PRA FAZER ISSO NO GTA VI 😂",
                          "O {N} ESTAVA TRANQUILO ATÉ QUE... 😳", "ESSE É O GTA 6 QUE O {N} CONHECE 😂", "{N} TESTOU OS LIMITES DO GTA 6",
                          "O DIA QUE O {N} QUEBROU O GTA 6 🤯", "VOCÊ NÃO VAI ACREDITAR NO QUE O {N} FEZ 😳", "O {N} E O GTA 6: UMA HISTÓRIA DE CAOS 😂"]),
}
# quando o áudio explode muito (grito, risada alta)
LOUD = ["O GRITO DO {N} NO GTA 6 😂", "O {N} QUASE QUEBROU O MICROFONE 😱", "{N} GRITOU TANTO QUE O CHAT ASSUSTOU 😂",
        "NUNCA VI O {N} GRITAR ASSIM 😱", "O {N} PERDEU O CONTROLE AQUI 🤯", "ESSE GRITO DO {N} FOI REAL 😂",
        "ABAIXA O VOLUME: O {N} SURTOU 🔊", "O {N} ESTOUROU O ÁUDIO DA LIVE 😂"]
_RE = {k: re.compile(v["re"], re.I) for k, v in CATS.items() if v["re"]}

# Coisas do GTA que o chat costuma citar: (artigo, o que o streamer "foi fazer")
THINGS = {
    "urso": ("O URSO", "MEXER COM O URSO"), "tubarao": ("O TUBARÃO", "NADAR COM TUBARÃO"),
    "jacare": ("O JACARÉ", "MEXER COM O JACARÉ"), "policia": ("A POLÍCIA", "FUGIR DA POLÍCIA"),
    "viatura": ("A VIATURA", "ROUBAR UMA VIATURA"), "swat": ("A SWAT", "ENFRENTAR A SWAT"),
    "carro": ("O CARRO", "PEGAR UM CARRO"), "moto": ("A MOTO", "DAR GRAU"), "grau": ("O GRAU", "DAR GRAU"),
    "bike": ("A BIKE", "DAR GRAU DE BIKE"), "aviao": ("O AVIÃO", "PILOTAR UM AVIÃO"),
    "helicoptero": ("O HELICÓPTERO", "PILOTAR UM HELICÓPTERO"), "heli": ("O HELI", "PILOTAR UM HELICÓPTERO"),
    "barco": ("O BARCO", "ANDAR DE BARCO"), "lancha": ("A LANCHA", "PILOTAR UMA LANCHA"),
    "caminhao": ("O CAMINHÃO", "ROUBAR UM CAMINHÃO"), "trem": ("O TREM", "PEGAR O TREM"),
    "banco": ("O BANCO", "ASSALTAR O BANCO"), "assalto": ("O ASSALTO", "FAZER UM ASSALTO"),
    "loja": ("A LOJA", "ASSALTAR A LOJA"), "posto": ("O POSTO", "ASSALTAR O POSTO"), "tiro": ("O TIRO", "TROCAR TIRO"),
    "tiroteio": ("O TIROTEIO", "ENTRAR NUM TIROTEIO"), "bomba": ("A BOMBA", "MEXER COM UMA BOMBA"),
    "explosao": ("A EXPLOSÃO", "EXPLODIR TUDO"), "praia": ("A PRAIA", "CURTIR A PRAIA"),
    "prisao": ("A PRISÃO", "FUGIR DA PRISÃO"), "hospital": ("O HOSPITAL", "IR PRO HOSPITAL"),
    "npc": ("O NPC", "ZOAR UM NPC"), "bug": ("O BUG", "TESTAR UM BUG"), "cachorro": ("O CACHORRO", "MEXER COM O CACHORRO"),
    "lucia": ("A LUCIA", "JOGAR COM A LUCIA"), "jason": ("O JASON", "JOGAR COM O JASON"),
    "corrida": ("A CORRIDA", "APOSTAR CORRIDA"), "rampa": ("A RAMPA", "PULAR DA RAMPA"), "ponte": ("A PONTE", "PULAR DA PONTE"),
}
ENDINGS = {
    "engracado": ["E NÃO ESPERAVA POR ISSO KKKKKKKKKK", "E DEU TUDO ERRADO KKKKKKKK"],
    "fail": ["E DEU MUITO RUIM 💀", "E SE ARREPENDEU NA HORA 💀"],
    "epico": ["E FEZ HISTÓRIA 🔥", "E MOSTROU COMO SE FAZ 🔥"],
    "susto": ["E TOMOU O SUSTO DA VIDA 😱", "E NINGUÉM ENTENDEU NADA 😳"],
    "policia": ["E VIROU O MAIS PROCURADO 🚨", "E A POLÍCIA NÃO PERDOOU 🚨"],
    "geral": ["E OLHA NO QUE DEU 😱", "E NÃO ESPERAVA POR ISSO 😳"],
}
EMO = {"engracado": "KKKKKKKKKK", "fail": "💀", "epico": "🔥", "susto": "😱", "policia": "🚨", "geral": "😳"}
PLAT = {"twitch": "Twitch", "kick": "Kick", "youtube": "YouTube"}


def _norm(w):
    return unicodedata.normalize("NFD", w.lower()).encode("ascii", "ignore").decode()


def find_subject(lines):
    seen = Counter()
    for line in lines:
        for w in set(re.findall(r"[a-z]+", _norm(line))):
            if w in THINGS:
                seen[w] += 1
    if seen:
        w, n = seen.most_common(1)[0]
        if n >= 2:
            return w
    return None


def title_list(cat, name, subject, gain=0):
    """Todos os títulos possíveis pra esse corte. Os ligados ao assunto da cena vêm primeiro."""
    N = name.upper()
    C = CATS.get(cat, CATS["geral"])
    ends = ENDINGS.get(cat, ENDINGS["geral"])
    out = []
    if subject:
        art, act = THINGS[subject]
        de = re.sub(r"^O ", "DO ", re.sub(r"^A ", "DA ", art))
        emo = EMO.get(cat, "😳")
        out += [f"{N} FOI {act} NO GTA VI {e}" for e in ends]
        out += [f"{N} TENTOU {act} E OLHA NO QUE DEU {emo}", f"QUANDO O {N} RESOLVEU {act}... {emo}",
                f"NUNCA DEIXE O {N} {act} NO GTA 6 💀", f"O {N} SÓ QUERIA {act} 😭", f"{art} NO GTA 6 E O {N} 😂"]
        extra = {
            "engracado": [f"{art} ACABOU COM O {N} KKKKKKKK", f"{N} E {art}: NINGUÉM ESPERAVA ISSO 😂"],
            "fail": [f"{N} MORREU POR CAUSA {de} 💀", f"{art} DESTRUIU O {N} 💀"],
            "epico": [f"{N} DOMINOU {art} NO GTA VI 🔥"],
            "susto": [f"{N} TOMOU SUSTO COM {art} 😱"],
            "geral": [f"OLHA {art} QUE O {N} ACHOU NO GTA VI 👀"],
        }
        out += extra.get(cat, [])
    general = [t.replace("{N}", N) for t in C["titles"]]
    if gain >= 18:
        general = [t.replace("{N}", N) for t in LOUD] + general
    if cat != "geral":
        general += [t.replace("{N}", N) for t in CATS["geral"]["titles"]]
    return out + [t for t in general if t not in out]


def pick_title(titles, n_subject, avoid=(), current=None):
    """Escolhe um título ainda não usado (de preferência ligado à cena), sorteando entre os que sobraram."""
    strip = lambda t: re.sub(r"\s+#\w+$", "", (t or "").strip())
    avoid = {strip(t) for t in avoid} | ({strip(current)} if current else set())
    fresh_subject = [t for t in titles[:n_subject] if t not in avoid]
    fresh = [t for t in titles if t not in avoid]
    pool = fresh_subject or fresh or [t for t in titles if t != current] or titles
    return random.choice(pool)


def top_message(lines):
    count = Counter()
    first = {}
    for raw in lines:
        t = re.sub(r"\s+", " ", raw.strip())
        t = re.sub(r"k{4,}", "KKKK", t, flags=re.I)
        if len(t) < 2 or len(t) > 70 or re.search(r"https?:|www\.|@", t):
            continue
        key = t.lower()
        count[key] += 1
        first.setdefault(key, t)
    if not count:
        return ""
    best = max(count, key=lambda k: count[k] + (0.5 if " " in k else 0))
    return first[best]


# ------------------------------------------------------------ texto da faixa dentro do vídeo
# Estilo "gancho" de corte de TikTok. Diferente do título, pra não ficar tudo igual.
HOOKS = {
    "engracado": ["O {N} NÃO ESPERAVA POR ESSA NO GTA VI KKKKKKKKKK", "O CHAT NÃO AGUENTOU ESSA DO {N} KKKKKKK",
                  "SÓ O {N} PRA PASSAR ESSA VERGONHA NO GTA 6 KKKKK", "O {N} TENTOU SER SÉRIO MAS NÃO DEU KKKKKKK",
                  "ATÉ O {N} RIU DELE MESMO NESSA KKKKKKKK", "O GTA 6 ZOOU O {N} DE UM JEITO QUE NINGUÉM ESPERAVA KKKKK"],
    "fail": ["O {N} ACHOU QUE IA DAR CERTO... SÓ ACHOU 💀", "ERA SÓ NÃO FAZER ISSO, {N} 😭", "O {N} TINHA TUDO NA MÃO E JOGOU FORA 💀",
             "NINGUÉM CONTOU PRO {N} QUE ISSO IA DAR ERRADO 😭", "O {N} SE ARREPENDEU NA HORA 💀"],
    "epico": ["O {N} FEZ ISSO NO GTA VI E O CHAT FOI À LOUCURA 🔥", "PRESTA ATENÇÃO NO QUE O {N} FEZ AQUI 🔥",
              "ESSA JOGADA DO {N} MERECIA PRÊMIO 🏆", "O {N} MOSTROU QUEM MANDA NO GTA VI 🔥"],
    "susto": ["O {N} NÃO ESTAVA PRONTO PRA ISSO 😱", "PRESTA ATENÇÃO NA REAÇÃO DO {N} 😳", "O {N} QUASE CAIU DA CADEIRA 😱",
              "NINGUÉM ESPERAVA ISSO, NEM O {N} 😨"],
    "policia": ["O {N} RESOLVEU DESAFIAR A POLÍCIA DO GTA VI 🚨", "A POLÍCIA NÃO DEU NENHUMA CHANCE PRO {N} 🚓",
                "O {N} VIROU O MAIS PROCURADO EM 10 SEGUNDOS 🚨"],
    "geral": ["ESPERA ATÉ O FINAL 😳", "O {N} NÃO ESPERAVA POR ISSO NO GTA VI 😳", "OLHA O QUE ACONTECEU COM O {N} NO GTA VI 👀",
              "O FINAL DESSE CORTE DO {N} É INSANO 🤯", "O {N} ESTAVA TRANQUILO NO GTA VI ATÉ QUE...", "ISSO SÓ ACONTECE NA LIVE DO {N} 😂",
              "O GTA VI RESOLVEU TESTAR A PACIÊNCIA DO {N}", "VOCÊ NÃO VAI ACREDITAR NO QUE O {N} VIU NO GTA VI 😳",
              "A REAÇÃO DO {N} NO FINAL É TUDO 😂", "O {N} DESCOBRIU UMA COISA NO GTA VI E SURTOU 🤯"],
}
LOUD_HOOKS = ["O {N} GRITOU TANTO QUE ESTOUROU O ÁUDIO 🔊", "PREPARA O OUVIDO: O {N} SURTOU AQUI 😱",
              "O GRITO DO {N} NO FINAL É REAL KKKKK", "NUNCA VI O {N} GRITAR ASSIM NO GTA VI 😱"]
SUBJECT_HOOKS = ["O {N} FOI {ACT} NO GTA VI E NÃO ESPERAVA POR ISSO KKKKKKKKKK", "O {N} SÓ QUERIA {ACT} NO GTA VI... 😭",
                 "O {N} TENTOU {ACT} E OLHA NO QUE DEU 😳", "NUNCA DEIXE O {N} {ACT} NO GTA VI 💀",
                 "O {N} RESOLVEU {ACT} E O GTA VI NÃO PERDOOU 💀", "{ART} NO GTA VI E A REAÇÃO DO {N} 😂"]


def quote_near(segments, peak_rel):
    """Uma frase que o streamer falou perto do momento forte (boa pra virar o texto do vídeo)."""
    if not segments or peak_rel is None:
        return ""
    best = None
    for st, en, text in segments:
        t = re.sub(r"\s+", " ", text).strip(" .,-")
        if not (8 <= len(t) <= 70) or len(t.split()) < 2:
            continue
        dist = 0 if st - 3 <= peak_rel <= en + 3 else min(abs(st - peak_rel), abs(en - peak_rel))
        if dist <= 12 and (best is None or dist < best[0]):
            best = (dist, t)
    return best[1] if best else ""


def hook_options(cat, name, subject, gain=0, quote=""):
    """Textos possíveis pra faixa. Os mais ligados ao corte vêm primeiro."""
    N = name.upper()
    first, rest = [], []
    if quote:
        q = quote.upper().rstrip("!?. ")
        first += [f'O {N}: "{q}"', f'"{q}" — O {N} NO GTA VI']
    if subject:
        art, act = THINGS[subject]
        first += [h.replace("{N}", N).replace("{ACT}", act).replace("{ART}", art) for h in SUBJECT_HOOKS]
    if gain >= 18:
        rest += [h.replace("{N}", N) for h in LOUD_HOOKS]
    rest += [h.replace("{N}", N) for h in HOOKS.get(cat, [])]
    if cat != "geral":
        rest += [h.replace("{N}", N) for h in HOOKS["geral"]]
    return first, rest


def transcript_quotes(text, name):
    """Pedaços curtos do que o streamer falou, no formato da faixa."""
    if not text:
        return []
    N = name.upper()
    out = []
    for chunk in re.split(r"[.!?…]+", text):
        words = chunk.strip(" ,-").split()
        if len(words) < 3:
            continue
        q = " ".join(words[:10]).upper()
        if 8 <= len(q) <= 70:
            out.append(f'O {N}: "{q}"')
    return list(dict.fromkeys(out))


def pick_hook(first, rest, avoid=()):
    avoid = set(avoid)
    f = [h for h in first if h not in avoid]
    if f:
        return f[0] if f[0].startswith(("O ", '"')) and '"' in f[0] else random.choice(f)
    r = [h for h in rest if h not in avoid]
    return random.choice(r or rest or first or [""])


# ------------------------------------------------------------ tags do YouTube
YT_CAT = {"engracado": ["gta 6 engraçado", "momentos engraçados gta 6", "gta 6 comédia"],
          "fail": ["gta 6 fail", "gta 6 fails", "wasted gta 6"],
          "epico": ["gta 6 jogada insana", "gta 6 épico", "melhores momentos gta 6"],
          "susto": ["gta 6 susto", "reação gta 6", "gta 6 reação"],
          "policia": ["gta 6 perseguição", "gta 6 polícia", "gta 6 fuga da polícia"],
          "geral": ["melhores momentos gta 6", "gta 6 momentos"]}


def youtube_tags(channel, platform, cat, subject=None):
    """Tags pro campo "Tags" do YouTube (separadas por vírgula, até 500 caracteres)."""
    n = channel.lower()
    plat = PLAT.get(platform, "").lower()
    r = rules.for_channel(channel)
    tags = list(r.get("yt_tags", [])) if r else []
    tags += ["gta 6", "gta vi", "gta 6 gameplay", "gta 6 brasil", "gta 6 ao vivo", "grand theft auto 6",
            n, f"{n} gta 6", f"{n} gta vi", f"cortes {n}", f"cortes do {n}", f"{n} cortes"]
    tags += YT_CAT.get(cat, YT_CAT["geral"])
    if subject:
        word = THINGS[subject][0].split(" ", 1)[-1].lower()
        tags += [f"{word} gta 6", f"gta 6 {word}"]
    if plat:
        tags += [f"{n} {plat}", f"live {plat}"]
    tags += ["gta 6 shorts", "shorts gta 6", "cortes de live", "gta 6 cortes"]
    out, size = [], 0
    for t in tags:
        if t not in out and size + len(t) + 2 <= 480:
            out.append(t)
            size += len(t) + 2
    return ", ".join(out)


def titles_for(channel, cat, subject, gain=0):
    """Títulos possíveis já ajustados pras regras do canal. Retorna (lista, quantos do começo são ligados à cena)."""
    disp = rules.display(channel)
    full = rules.adapt(channel, title_list(cat, disp, subject, gain), "title")
    if not subject:
        return full, 0
    base = set(rules.adapt(channel, title_list(cat, disp, None, gain), "title"))
    n = 0
    for t in full:
        if t in base:
            break
        n += 1
    return full, n


def hooks_for(channel, cat, subject, gain=0, quote=""):
    """Textos da faixa ajustados pras regras do canal. Retorna (ligados ao corte, outros)."""
    disp = rules.display(channel)
    first, rest = hook_options(cat, disp, subject, gain, quote)
    return rules.adapt(channel, first, "hook"), rules.adapt(channel, rest, "hook")


def make_meta(channel, platform, url, lines=(), manual=False, gain=0, avoid=(), speech=(), peak_rel=None, avoid_hooks=()):
    """lines: mensagens do chat · speech: o que o streamer falou no corte [(inicio, fim, texto)]"""
    lines = list(lines)
    speech = list(speech or [])
    spoken = [t for _, _, t in speech]
    cat, best = "geral", 1
    for k, rx in _RE.items():
        n = sum(1 for l in lines if rx.search(l))
        if n > best:
            cat, best = k, n
    # o que o streamer fala perto do momento forte pesa mais que o resto
    near = [t for st, en, t in speech if peak_rel is not None and st - 4 <= peak_rel <= en + 4]
    subject = find_subject(lines + spoken + near * 3)
    rule = rules.for_channel(channel)
    disp = rules.display(channel)            # ex: "orenatovicente" aparece como "Renato" nos textos
    titles, n_subject = titles_for(channel, cat, subject, gain)
    raw_title = pick_title(titles, max(0, n_subject), avoid)
    title = rules.title_with_tag(channel, raw_title)
    chat_top = top_message(lines)
    Nn = disp[:1].upper() + disp[1:]
    plat = PLAT.get(platform, "live")
    fem = bool(rule and rule.get("fem"))
    o, do = ("a", "da") if fem else ("o", "do")
    lead = CATS[cat]["lead"]
    if rules.is_safe(channel) and cat in ("fail", "susto"):
        lead = "Melhor momento"
    desc = f"{lead} {do} {Nn} ao vivo no GTA 6 🎮"
    if chat_top and not rules.is_safe(channel):   # canais "safe": nada de comentário do chat na legenda
        desc += f'\n💬 O chat: "{chat_top}"'
    desc += f"\n🔴 Acompanhe {o} {Nn} na {plat}: {url}"
    if rule and rule.get("mention"):
        desc += f"\n📌 {rule['mention']}"
    name_tag = "#" + re.sub(r"[^a-z0-9_]", "", channel.lower())
    tags = []
    base = (rule.get("hashtags", []) if rule else []) + settings.get("tags").split() \
        + [name_tag, name_tag + "cortes", "#" + plat.lower()] + CATS[cat]["tags"]
    # campeonatos pedem hashtags ligadas ao conteúdo: sem #fyp/#viral e, nos canais "safe", sem #fail etc.
    drop = {"#fyp", "#viral"} if rule else set()
    if rules.is_safe(channel):
        drop |= {"#fail", "#gtafail", "#wasted", "#susto", "#wtf"}
    for t in base:
        t = t if t.startswith("#") else "#" + t
        if t not in tags and t.lower() not in drop:
            tags.append(t)
    quote = quote_near(speech, peak_rel)
    first, rest = hooks_for(channel, cat, subject, gain, quote)
    hook = pick_hook(first, rest, set(avoid_hooks) | {title, raw_title})
    return {
        "cat": cat, "subject": subject, "title": title, "title_idx": titles.index(raw_title), "descr": desc,
        "tags": " ".join(tags), "chat_top": chat_top, "yt_tags": youtube_tags(channel, platform, cat, subject),
        "overlay": hook if settings.get("ov_on") else "",
        "transcript": " ".join(spoken)[:2000] or None,
    }
