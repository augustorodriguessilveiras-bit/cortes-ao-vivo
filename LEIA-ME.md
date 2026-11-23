# ✂ Cortes ao Vivo (versão instalada)

Grava as lives que você escolher **direto do servidor da Twitch/Kick/YouTube, na qualidade original**, sem gravar a tela e sem travar. Quando o **chat explode** ou o **áudio dispara**, o corte sai sozinho:

- **Vertical 9:16** no estilo TikTok: **câmera em cima, gameplay embaixo** (você marca a câmera uma vez por streamer)
- **Faixa branca com o título** dentro do vídeo nos primeiros segundos (editável)
- **Título, descrição e hashtags** prontos pra copiar
- **Horizontal 16:9** também
- **VODs:** cole o link de uma live que já passou e ele acha os melhores momentos sozinho
- Usa a **placa de vídeo** (NVIDIA, Intel ou AMD) quando o PC tiver, pra montar os cortes mais rápido

## Instalar no Windows (uma vez só, ~10 min)
1. Instale o **Python**: https://www.python.org/downloads/ (na 1ª tela, marque **"Add python.exe to PATH"**).
2. Extraia este zip numa pasta (ex: `Documentos\cortes-gta`).
3. Dê **dois cliques no `INICIAR.bat`**. Na 1ª vez ele instala o ffmpeg e pede pra abrir de novo; depois instala o resto sozinho.
4. O painel abre no Chrome em **http://localhost:8000**.

## Atualizações automáticas
Toda vez que você abre o `INICIAR.bat`, ele confere aqui no GitHub se tem versão nova e **se atualiza sozinho**.
Seus cortes, canais e ajustes (pasta `dados`) não são mexidos. Pra pegar uma melhoria, é só fechar a janela preta e abrir de novo.

## Usar
- **Canal:** cole `kick.com/nome` ou `twitch.tv/nome`. Grava sozinho sempre que entrar ao vivo.
- **VOD:** cole o link do vídeo (ex: `kick.com/nome/videos/...`). Ele ouve o áudio do vídeo inteiro, acha os picos e baixa só esses pedaços em alta qualidade.
- **📷 Marcar câmera:** com o canal gravando, arraste em cima da webcam. Os próximos cortes saem com a cam em cima.
- **✂ Editar corte** (em cada corte): corte o vídeo no começo e no fim, escolha de quando até quando o texto aparece, e arraste o texto e a marca d'água pra onde quiser, vendo a prévia. Ao salvar ele refaz o vídeo; o original fica guardado pra editar de novo.
- **📐 Formato / câmera** (em cada corte): escolha **Automático**, **Câmera em cima + gameplay**, **Tela cheia (full cam)** ou **Só gameplay**, corrija a posição da câmera e refaça o vertical.
- **Full cam automático:** quando o streamer está em tela cheia na câmera (sem gameplay), o corte sai na tela toda, centrado nele.
- **Texto no vídeo** (em cada corte, logo abaixo do vídeo): botão pra ligar/desligar o texto, prévia do vídeo, **🔄 Outro texto** pra sugerir outro (sem repetir), edição à mão e **🎬 Aplicar no vídeo**.
- **📝 Título, descrição, hashtags e 🏷 tags do YouTube** (em cada corte): copiar e trocar o título; as tags vão no campo "Tags" do YouTube.
- **🗣 Fala do streamer:** o programa ouve o que o streamer fala no corte (reconhecimento de fala grátis, no próprio PC) e usa isso no texto do vídeo e no título. Na 1ª vez ele baixa ~150 MB.
- **Duração do corte** (em Ajustes): 60 segundos por padrão (2/3 antes do momento, 1/3 depois), dá pra mudar de 20 a 90.
- **Os cortes ficam salvos** na pasta `dados\cortes`.
- A janela preta precisa ficar aberta. Pra desligar, é só fechar.

---

## Instalação num servidor (recomendado)

### 1. Contrate um VPS
Qualquer um com **Ubuntu 22 ou 24**. Exemplos: Contabo, Hetzner, Hostinger VPS.

| Lives ao mesmo tempo | Servidor sugerido |
|---|---|
| até 5 | 4 vCPU, 8 GB RAM, 100 GB de disco |
| até 15 | 6 a 8 vCPU, 16 GB RAM, 200 GB de disco |

> O que mais pesa é **renderizar os cortes**, não gravar. O disco usado é cerca de `nº de lives × 20 min de buffer` mais os cortes salvos.

### 2. Envie os arquivos para o servidor
No seu PC, dentro da pasta onde está o `cortes-gta`:
```bash
scp -r cortes-gta root@IP_DO_SERVIDOR:/root/
```

### 3. Instale e ligue (no servidor)
```bash
ssh root@IP_DO_SERVIDOR
```
```bash
curl -fsSL https://get.docker.com | sh
```
```bash
cd /root/cortes-gta && cp .env.example .env && nano .env
```
Troque a `PANEL_PASSWORD`, salve com `Ctrl+O`, `Enter`, `Ctrl+X` e ligue:
```bash
docker compose up -d --build
```

### 4. Use
Abra no navegador do PC ou do celular: **http://IP_DO_SERVIDOR:8000**. Faça login com o usuário e a senha do `.env` e cole os links dos canais.

Ele liga sozinho se o servidor reiniciar. Para ver o que está acontecendo:
```bash
docker compose logs -f
```

Para atualizar (rode de vez em quando, porque as plataformas mudam e o gravador precisa acompanhar):
```bash
docker compose build --pull --no-cache && docker compose up -d
```

---

## Rodar no seu PC com Windows (grátis)
1. Instale o **Python**: https://www.python.org/downloads/. Na primeira tela da instalação, **marque a caixinha "Add python.exe to PATH"**.
2. Extraia o zip numa pasta (ex: `Documentos\cortes-gta`).
3. Dê **dois cliques no `INICIAR.bat`**.
   - Na 1ª vez ele instala o ffmpeg sozinho e pede pra abrir o `INICIAR.bat` de novo.
   - Se o Windows mostrar "O Windows protegeu o computador", clique em **Mais informações → Executar assim mesmo**.
   - Se o Firewall perguntar, clique em **Permitir** (é o que deixa você abrir pelo celular).
4. O navegador abre em **http://localhost:8000**. Cole os links dos canais.

- **Pelo celular** (no mesmo Wi-Fi): abra `http://IP_DO_PC:8000`. Pra descobrir o IP, abra o Prompt de Comando, digite `ipconfig` e veja o "Endereço IPv4" (ex: 192.168.0.15).
- **Os cortes ficam salvos** na pasta `dados\cortes`.
- **Para desligar:** feche a janela preta. Pra gravar, o PC precisa estar ligado com essa janela aberta.
- Desative a suspensão do PC (Configurações → Sistema → Energia → "Nunca") pra ele não dormir no meio da live.

---

## Usar em 2 computadores (ex: casa e casa dos pais)
Instale nos dois PCs do mesmo jeito: Python, extrair o zip e `INICIAR.bat`.

**Jeito simples:** cada PC tem a sua própria lista de canais e os seus cortes. Cole os links nos dois.

**Jeito sincronizado (Google Drive):** os dois PCs veem a mesma lista de canais e os mesmos cortes.
1. Instale o **Google Drive para computador** nos dois PCs, com a mesma conta. Ele cria a unidade `G:\Meu Drive`.
2. Nos dois PCs: copie o `.env.example`, renomeie a cópia para `.env`, abra no Bloco de Notas e coloque no final:
   ```
   DATA_DIR=G:\Meu Drive\cortes-gta
   SEGMENTS_DIR=C:\cortes-gravacoes
   ```
3. **Regra de ouro:** nunca deixe os dois ligados ao mesmo tempo. Feche a janela preta num PC, espere o Google Drive terminar de sincronizar (ícone na barra de tarefas sem setinhas girando) e só então abra no outro.

> O Google Drive grátis tem 15 GB, o que dá uns 200–400 cortes. Apague no painel (🗑) os cortes que já postou ou não quer.

---

## Como os momentos das lives são achados

- **Áudio:** grito, explosão, risada alta (comparado com o normal dos últimos 10 minutos).
- **Chat:** chat acelerando ou cheio de "KKKK", "clipa"... (Twitch e Kick).
- **Fala:** o programa ouve o que o streamer fala o tempo todo. Reação ("meu deus", "que isso"), descoberta
  ("nunca vi isso"), bug ("bugou", "atravessou") e risada viram corte mesmo sem grito. Precisa do reconhecimento
  de fala instalado. Dá pra desligar em Ajustes.
- **⭐ / 👎 Aprende com você:** o programa vê quais coisas do jogo (lugar, veículo, bicho, missão, situação) aparecem
  nos cortes que você aprova e nos que você exclui. Quando qualquer streamer passar por elas, o momento ganha (ou
  perde) nota. Funciona sozinho; o motivo aparece no cartão do corte.
- **Intervalo mínimo entre cortes** (Ajustes, padrão 40s): quanto menor, mais cortes seguidos.
- O cartão da live mostra quantos momentos foram achados, quantos viraram corte e se o chat e a fala estão ativos.

## ⚽ Futebol (streamer reagindo a jogo)

- O programa reconhece pelo título/categoria da live ou do VOD (futebol, Flamengo, Brasileirão, Libertadores...),
  ou você escolhe "⚽ Futebol" no corte, no trecho de VOD ou no corte enviado.
- Cortes mais longos (2 min por padrão, ajustável em Ajustes): a jogada inteira antes do lance e a reação depois.
- Acha os lances pelo grito e pelo que ele fala ("gol", "golaço", "na trave", "pênalti", "juiz ladrão", "que defesa"...).
- Títulos, hashtags e tags de futebol, com o time quando ele falar (ex: "A REAÇÃO DO RENATO A ESSE GOL DO FLAMENGO").
- Trocar um corte pronto pra "⚽ Futebol" deixa ele mais longo sozinho, usando a sobra guardada.

## Recursos dos cortes

- **Sobra antes e depois:** cada corte guarda 30s a mais antes e depois (muda em Ajustes). No ✂ Editar corte, puxe
  "Começa em" pra trás ou "Termina em" pra frente (ou use ⏪ +5s / +5s ⏩) pra pegar mais do momento.
- **Estilo Padrão ou ✨ Dinâmico** (no cartão de cada corte, ou pra todos em Ajustes): o dinâmico tem zoom rápido na
  reação e começo/fim no ponto certo da fala (sem legenda; dá pra ligar a legenda num corte pelo editor).
- **📲 Onde já postou:** marque TikTok, Reels e Shorts em cada corte e anote as visualizações. Quando marca as 3,
  o corte vira "postado". As views ensinam o programa e aparecem em **📈 O que dá mais view**.
- **♻ Corte repetido:** se o mesmo momento for cortado duas vezes (ex: da live e do VOD), o cartão avisa.
- **🎬 Compilado pro YouTube:** junta cortes aprovados num vídeo deitado com o título de cada momento e os capítulos
  prontos pra descrição.
- **VOD ouvido inteiro** (Ajustes, ligado por padrão): além dos picos de som, o programa ouve tudo o que o
  streamer fala no VOD e acha reação sem grito. Mais preciso, demora mais. Se fechar no meio, continua de onde parou.
- **Fila dos VODs:** 2 VODs são feitos ao mesmo tempo (muda em Ajustes: 1 a 3). Nos que estão esperando aparece
  ⏫ Passar na frente. Trecho de VOD por tempo e corte enviado têm fila própria e não esperam os VODs.
- **🎨 Cores e letras:** o título tem 8 estilos de cor (faixa branca, preta, amarela, verde, rosa, vermelha, ou sem
  faixa com contorno) e 6 letras; a marca d'água tem 6 estilos (escura, verde, branca, preta, amarela, contorno).
  Os cortes saem no estilo padrão (faixa branca, marca d'água escura); você muda as cores em cada corte no
  ✂ Editar corte. Em Ajustes dá pra mudar o padrão ou escolher "Variar sozinho".
  Fontes: Anton, Archivo Black, Bangers, Bebas Neue (licença OFL) e Luckiest Guy (licença Apache), em app/static/fonts.
- **📤 Enviar um corte seu:** manda um trecho que você cortou e ele sai no mesmo formato dos automáticos.
- **✂ Cortar um trecho de VOD:** cole o link do vídeo da live e o tempo (ex: de 3:13:00 até 3:15:00). O programa
  baixa só esse pedaço, com a sobra antes e depois, e monta o corte no mesmo estilo. Escolha "1 corte" (o trecho
  todo, até 15 min) ou "Vários cortes": o trecho pode ter 20 min, 1 hora, 3 horas; o programa ouve só esse pedaço
  e faz quantos cortes tiver de bom dentro dele (aparece em VODs, com o andamento). Link com tempo (ex: ...?t=3h13m) colado na caixa de
  cima vai direto pra cá, em vez de processar o VOD inteiro.

## Regras por streamer (campeonatos)
Alguns canais têm regras próprias, aplicadas sozinhas só nos cortes deles (arquivo `app/rules.py`). Os outros canais seguem normais.

| Canal | Hashtag no título | No vídeo | Marcar |
|---|---|---|---|
| Renato Vicente (`orenatovicente`) | #orenatovicente | marca d'água kick.com/orenatovicente | @orenatovicente |
| Allan Stag (`allanstag`) | #allanstag | marca d'água kick.com/allanstag | — |
| Mitsuke (`mitsuke`) | #mitsuke | marca d'água kick.com/mitsuke | — |
| Luanz7 (`luanz7`) | #luanz7 | **Lower** oficial (envie uma vez no painel: link do Drive ou arquivo) | @luanz7 |
| Yayah (`yayahuz`) | #yayah | — | @yayahuz |
| Sofia Espanha (`sofiaespanha`) | #sofiaespanha | marca d'água twitch.tv/sofiaespanha | @sofiaespanha |

Em todos: sem #fyp/#viral (hashtags ligadas ao conteúdo). Na Yayah, só títulos e textos respeitosos, no feminino,
e sem comentário do chat na descrição.
- **Paulinho o Loko** (kick.com/paulinholokobr): `#paulinhooloko` em todos; marca d'água `kick.com/paulinholokobr` no corte, ou o Lower (GIF) dele, se você enviar no cartão do corte.
- **Lower (Paulinho, Luanz7):** envie o arquivo (GIF animado, PNG ou vídeo) no cartão do corte. Ele fica logo acima do título, embaixo da câmera, e dá pra arrastar no ✂ Editar corte. Sem o Lower, sai a marca d'água em texto.

## Ajustes (arquivo `.env`)
| Opção | O que faz |
|---|---|
| `MIN_SCORE` | Nota mínima para cortar. **Muitos cortes ruins: aumente** (7–8). **Poucos cortes: diminua** (5–6) |
| `CLIP_BEFORE` / `CLIP_AFTER` | Segundos antes e depois do pico |
| `COOLDOWN_SECONDS` | Intervalo mínimo entre cortes da mesma live |
| `BUFFER_MINUTES` | Quanto de cada live fica no disco |

No PC: copie o `.env.example`, renomeie a cópia para `.env` e edite no Bloco de Notas. Depois feche e abra o `INICIAR.bat`. No servidor: rode `docker compose up -d` de novo.

## Como a nota é calculada
A cada segundo o sistema compara o momento com os últimos 10 minutos **daquela mesma live**:
- **Chat:** quantas vezes mais rápido que o normal e quantas mensagens são de risada ou hype
- **Áudio:** quantos dB acima do volume normal do streamer

Como cada streamer é comparado com ele mesmo, funciona tanto pra quem grita o tempo todo quanto pra quem é mais calmo.

## ⚠️ Direitos autorais
O conteúdo das lives pertence aos streamers. Para postar os cortes, combine com eles: autorização, crédito e/ou divisão de receita. Isso evita strikes no seu canal.
