"""Banco de conteúdo do JP Personal Kids.

Cada dia da semana tem um tema fixo. Dentro de cada tema há vários posts;
o gerador escolhe um diferente a cada semana, então o conteúdo só se repete
depois de várias semanas.

Para adicionar posts novos, basta copiar um bloco { ... } e mudar o texto.
"""

# Melhores horários para postar (público: pais e mães), por dia da semana.
# 0 = segunda ... 6 = domingo
HORARIOS = {
    0: "19:30",
    1: "12:00",
    2: "19:30",
    3: "12:00",
    4: "18:30",
    5: "10:00",
    6: "18:00",
}

TEMAS = {
    0: {"nome": "DICA DE EXERCÍCIO", "cor": "verde"},
    1: {"nome": "BENEFÍCIOS", "cor": "azul"},
    2: {"nome": "BRINCADEIRA ATIVA", "cor": "vermelho"},
    3: {"nome": "MITO OU VERDADE?", "cor": "roxo"},
    4: {"nome": "DESAFIO DA SEMANA", "cor": "amarelo"},
    5: {"nome": "DICA PARA OS PAIS", "cor": "azul"},
    6: {"nome": "FRASE DA SEMANA", "cor": "vermelho"},
}

POSTS = {
    # SEGUNDA — dica de exercício
    0: [
        {"titulo": "Pular corda turbina o coração!",
         "itens": ["Comece com 3 séries de 30 segundos", "Descanse 30 segundos entre elas", "Pule com os pés juntinhos e joelhos soltos"],
         "legenda": "Pular corda é diversão garantida e ainda fortalece o coração, as pernas e a coordenação! 🪢💪 Quem aí já pula corda em casa?"},
        {"titulo": "Caminhada do urso 🐻",
         "itens": ["Mãos e pés no chão, bumbum para cima", "Ande 5 metros para frente e volte", "Repita 3 vezes"],
         "legenda": "A caminhada do urso fortalece braços, ombros e barriga — e as crianças AMAM! Grava seu pequeno fazendo e marca a gente! 🐻"},
        {"titulo": "Polichinelo divertido",
         "itens": ["Faça 10 polichinelos contando em voz alta", "Descanse e repita 3 vezes", "Dica: conte em inglês para aprender junto!"],
         "legenda": "Polichinelo é clássico porque funciona: aquece o corpo todo e melhora a coordenação. Bora contar juntos? 1, 2, 3... 🙌"},
        {"titulo": "Equilíbrio do flamingo 🦩",
         "itens": ["Fique em um pé só por 15 segundos", "Troque de perna", "Desafio: tente de olhos fechados!"],
         "legenda": "Equilíbrio é base para correr, pular e praticar qualquer esporte. Quanto tempo seu flamingo aguenta? 🦩"},
        {"titulo": "Agachamento do sapo 🐸",
         "itens": ["Agache com as mãos no chão", "Salte para cima esticando os braços", "Faça 8 saltos, descanse, repita 3x"],
         "legenda": "Pula, sapinho! O salto do sapo fortalece as pernas e gasta aquela energia extra. 🐸💚"},
        {"titulo": "Prancha do super-herói",
         "itens": ["Apoie antebraços e pontas dos pés", "Corpo retinho como uma tábua", "Segure 15 a 20 segundos, 3 vezes"],
         "legenda": "Todo super-herói precisa de uma barriga forte! A prancha ajuda na postura e na força do tronco. 🦸‍♂️🦸‍♀️"},
        {"titulo": "Corrida do caranguejo 🦀",
         "itens": ["Sente, apoie mãos e pés e levante o bumbum", "Ande de lado para a direita e para a esquerda", "3 idas e voltas"],
         "legenda": "Andar de caranguejo trabalha braços, pernas e coordenação, tudo com muita risada! 🦀"},
        {"titulo": "Skipping no lugar",
         "itens": ["Corra no lugar subindo bem os joelhos", "20 segundos rápido, 20 segundos descanso", "Repita 4 vezes"],
         "legenda": "Skipping é um ótimo aquecimento e deixa o coração forte. Coloca uma música e bora! 🎶🏃"},
        {"titulo": "Arremesso ao alvo 🎯",
         "itens": ["Use bolinhas de meia e um balde", "Arremesse de 2, 3 e 4 passos de distância", "Conte quantas acertou!"],
         "legenda": "Arremessar melhora a coordenação olho-mão e a concentração. Material? Só meias e um balde! 🎯"},
        {"titulo": "Rolamento seguro",
         "itens": ["Use um colchonete ou tapete macio", "Queixo no peito e corpo em bolinha", "Sempre com um adulto por perto"],
         "legenda": "Rolar ajuda na consciência corporal e no equilíbrio. Segurança em primeiro lugar: colchonete e adulto junto! 🤸"},
    ],
    # TERÇA — benefícios
    1: [
        {"titulo": "Criança ativa dorme melhor 😴",
         "itens": ["Gasta a energia do dia", "Adormece mais rápido", "Acorda mais disposta"],
         "legenda": "Quer uma noite tranquila? Movimento durante o dia ajuda (e muito!) no sono das crianças. 🌙"},
        {"titulo": "Exercício ajuda na escola 📚",
         "itens": ["Mais atenção e concentração", "Melhor memória", "Mais disposição para aprender"],
         "legenda": "Movimento também é aprendizado! Crianças ativas tendem a ter mais foco na sala de aula. 📚✨"},
        {"titulo": "Ossos e músculos fortes 💪",
         "itens": ["Pular e correr fortalecem os ossos", "Músculos ficam mais resistentes", "Menos risco de lesões"],
         "legenda": "A infância é a melhor fase para construir ossos e músculos fortes para a vida toda! 💪"},
        {"titulo": "Mais confiança e autoestima",
         "itens": ["Cada conquista vira motivo de orgulho", "Aprende a superar desafios", "Se sente capaz"],
         "legenda": "Quando a criança consegue fazer algo novo, a confiança dela vai lá em cima! 🚀"},
        {"titulo": "Amizades e trabalho em equipe",
         "itens": ["Aprende a dividir e esperar a vez", "Faz novos amigos", "Respeita regras e colegas"],
         "legenda": "Brincar e se exercitar em grupo ensina valores que vão muito além do esporte. 🤝"},
        {"titulo": "Menos telas, mais movimento 📵",
         "itens": ["Recomendado: 60 minutos de atividade por dia", "Pode ser dividido ao longo do dia", "Brincadeira também conta!"],
         "legenda": "A recomendação para crianças e adolescentes é de pelo menos 60 minutos de atividade física por dia. Como está aí na sua casa? ⏱️"},
        {"titulo": "Coordenação motora em dia",
         "itens": ["Correr, pular e arremessar", "Equilibrar e girar", "Base para qualquer esporte"],
         "legenda": "Coordenação motora bem trabalhada na infância facilita aprender qualquer esporte depois. ⚽🏀🤸"},
        {"titulo": "Mais alegria e menos estresse 😄",
         "itens": ["Movimento libera substâncias do bem-estar", "Ajuda a lidar com a ansiedade", "Deixa o humor lá em cima"],
         "legenda": "Criança que se mexe é criança mais feliz! Exercício também cuida das emoções. 💛"},
    ],
    # QUARTA — brincadeira ativa
    2: [
        {"titulo": "Estátua! 🗿",
         "itens": ["Coloque uma música animada", "Quando parar, todo mundo congela", "Quem mexer faz 5 polichinelos"],
         "legenda": "Brincadeira clássica que trabalha atenção, equilíbrio e controle do corpo. Pais, entrem na dança também! 🎶"},
        {"titulo": "Circuito no sofá da sala",
         "itens": ["Passar por baixo da mesa", "Pular almofadas no chão", "Andar na linha de fita crepe"],
         "legenda": "Com o que tem em casa dá para montar um circuito incrível! Mostra pra gente o circuito de vocês! 🛋️"},
        {"titulo": "Morto-vivo 💀",
         "itens": ["\"Morto\": agacha", "\"Vivo\": fica em pé", "Fale rápido para confundir!"],
         "legenda": "Morto-vivo é treino de pernas disfarçado de brincadeira. E dá muita risada! 😂"},
        {"titulo": "Caça ao tesouro ativa 🗺️",
         "itens": ["Esconda pistas pela casa ou quintal", "Cada pista tem um exercício", "O tesouro pode ser uma fruta!"],
         "legenda": "Movimento + raciocínio + diversão. Caça ao tesouro é sucesso em qualquer idade! 🏴‍☠️"},
        {"titulo": "Batata quente com exercício 🥔",
         "itens": ["Passe a bola ao som da música", "Quando parar, quem está com ela...", "...faz um exercício sorteado!"],
         "legenda": "Uma versão ativa da batata quente para fazer em família ou com os amiguinhos. 🔥"},
        {"titulo": "Amarelinha",
         "itens": ["Desenhe com giz ou fita no chão", "Pule em um pé e em dois pés", "Trabalha equilíbrio e força"],
         "legenda": "A amarelinha nunca sai de moda! Equilíbrio, força e coordenação numa brincadeira só. 🟨"},
        {"titulo": "Siga o mestre 👑",
         "itens": ["Um é o mestre e faz movimentos", "Todos copiam", "Troque o mestre a cada rodada"],
         "legenda": "Siga o mestre estimula a criatividade e a imitação de movimentos. Quem é o mestre aí? 👑"},
        {"titulo": "Pega-pega da sombra",
         "itens": ["Em dia de sol, ao ar livre", "Tem que pisar na sombra do amigo", "Muita corrida e risada"],
         "legenda": "Pega-pega da sombra é uma variação divertida para gastar energia ao ar livre. ☀️ Não esqueçam do protetor solar e da água!"},
    ],
    # QUINTA — mito ou verdade
    3: [
        {"titulo": "Musculação faz a criança parar de crescer?",
         "itens": ["MITO! ❌", "Com orientação profissional e cargas adequadas, o treino de força é seguro", "E ainda fortalece os ossos"],
         "legenda": "Esse é um dos mitos mais comuns! Treino de força orientado e adaptado à idade é seguro e traz muitos benefícios. 💪"},
        {"titulo": "Criança precisa se alongar antes de brincar?",
         "itens": ["Melhor ainda: aquecer! ✅", "Correr leve e pular são um ótimo aquecimento", "Alongamento fica para o final"],
         "legenda": "Antes da atividade, o ideal é aquecer o corpo com movimentos leves. Alongar com calma fica para o final! 🧘"},
        {"titulo": "Brincar conta como atividade física?",
         "itens": ["VERDADE! ✅", "Correr, pular e escalar contam muito", "Toda movimentação ativa soma no dia"],
         "legenda": "Brincar é a forma mais natural de a criança se exercitar. Toda brincadeira ativa conta! 🎉"},
        {"titulo": "Suar muito significa que treinou bem?",
         "itens": ["MITO! ❌", "Suor depende do clima e do corpo de cada um", "O importante é a qualidade do movimento"],
         "legenda": "Suor não mede a qualidade do treino! Mas atenção: sempre ofereça água antes, durante e depois. 💧"},
        {"titulo": "Criança gordinha é criança saudável?",
         "itens": ["MITO! ❌", "Saúde vem de alimentação equilibrada", "E de movimento todos os dias"],
         "legenda": "Saúde vai muito além da balança: alimentação equilibrada, sono e movimento são o trio de ouro. Na dúvida, converse com o pediatra! 🍎"},
        {"titulo": "Exercício deixa a criança mais calma?",
         "itens": ["VERDADE! ✅", "Ajuda a gastar energia", "E a regular as emoções"],
         "legenda": "Sim! Atividade física ajuda a criança a ficar mais tranquila e focada. 🧠💛"},
        {"titulo": "Só criança 'atlética' pode fazer exercício?",
         "itens": ["MITO! ❌", "Todo corpo pode e deve se movimentar", "Cada um no seu ritmo"],
         "legenda": "Exercício é para TODAS as crianças! O segredo é respeitar o ritmo de cada uma e tornar tudo divertido. 🌈"},
        {"titulo": "Pode treinar depois de comer?",
         "itens": ["Com moderação ✅", "Após refeição grande, espere um pouco", "Lanche leve não costuma atrapalhar"],
         "legenda": "Depois de um almoção, vale esperar um tempinho antes de atividades intensas. Um lanche leve já dá energia para brincar! 🍌"},
    ],
    # SEXTA — desafio da semana
    4: [
        {"titulo": "Desafio: 20 polichinelos!",
         "itens": ["Faça 20 polichinelos sem parar", "Grave e poste nos stories", "Marque a gente! 📲"],
         "legenda": "DESAFIO DA SEMANA 🏆 20 polichinelos sem parar! Grava, posta e marca a gente que a gente reposta! 🙌"},
        {"titulo": "Desafio do equilíbrio 🦩",
         "itens": ["30 segundos num pé só", "Sem apoiar a mão em nada", "Vale tentar dos dois lados!"],
         "legenda": "DESAFIO DA SEMANA 🏆 Quem consegue ficar 30 segundos num pé só? Pais também podem participar! 😄"},
        {"titulo": "Desafio pais x filhos 👨‍👧",
         "itens": ["Quem faz mais agachamentos em 30s?", "Pais contra filhos!", "Mostra o resultado pra gente"],
         "legenda": "DESAFIO DA SEMANA 🏆 Pais x filhos! Quem ganha? Comenta aqui embaixo o placar! 👇"},
        {"titulo": "Desafio da prancha",
         "itens": ["Segure a prancha por 20 segundos", "Conseguiu? Tente 30!", "Corpo retinho, hein!"],
         "legenda": "DESAFIO DA SEMANA 🏆 Prancha do super-herói! Até onde seu pequeno chega? ⏱️"},
        {"titulo": "Desafio da corda 🪢",
         "itens": ["Quantos pulos sem errar?", "Anote o recorde", "Tente bater na semana que vem!"],
         "legenda": "DESAFIO DA SEMANA 🏆 Recorde de pulos na corda! Conta nos comentários quantos pulos foram! 👇"},
        {"titulo": "Desafio 7 dias ativos ✅",
         "itens": ["60 minutos de movimento por dia", "Marque um ✅ no calendário", "Complete a semana inteira!"],
         "legenda": "DESAFIO DA SEMANA 🏆 7 dias ativos! Imprime um calendário, cola na geladeira e vai marcando. Bora?"},
        {"titulo": "Desafio da bolinha 🎯",
         "itens": ["10 arremessos no balde", "De 3 passos de distância", "Quantos acertos?"],
         "legenda": "DESAFIO DA SEMANA 🏆 Mira certeira! Comenta quantos acertos seu pequeno fez! 🎯"},
        {"titulo": "Desafio do sapo 🐸",
         "itens": ["Salto do sapo pela sala", "Quantos saltos até a parede?", "Menos saltos = saltos maiores!"],
         "legenda": "DESAFIO DA SEMANA 🏆 Salto do sapo! Quanto menos saltos até a parede, mais forte é o sapinho! 🐸"},
    ],
    # SÁBADO — dica para os pais
    5: [
        {"titulo": "Seja o exemplo 👨‍👩‍👧",
         "itens": ["Criança imita o que vê", "Pais ativos, filhos ativos", "Façam exercícios juntos!"],
         "legenda": "O melhor incentivo é o exemplo! Que tal um passeio de bicicleta em família neste fim de semana? 🚲"},
        {"titulo": "Água é essencial 💧",
         "itens": ["Leve garrafinha para todas as atividades", "Ofereça antes, durante e depois", "Em dias quentes, ainda mais!"],
         "legenda": "Hidratação é fundamental, principalmente nos dias quentes. Garrafinha sempre na mochila! 💧"},
        {"titulo": "Lanche antes do treino 🍌",
         "itens": ["Frutas como banana ou maçã", "Iogurte natural", "Sanduíche leve"],
         "legenda": "Um lanche leve antes de se exercitar dá energia sem pesar. Na dúvida, converse com o pediatra ou nutricionista! 🍎"},
        {"titulo": "Elogie o esforço, não só o resultado",
         "itens": ["\"Você se esforçou muito!\"", "\"Vi que você não desistiu!\"", "Isso cria amor pelo movimento"],
         "legenda": "Elogiar o esforço ensina a criança a persistir e a gostar de se exercitar, independentemente de ganhar ou perder. 💛"},
        {"titulo": "Crie uma rotina de movimento",
         "itens": ["Escolha um horário fixo", "Transforme em momento da família", "Constância vale mais que intensidade"],
         "legenda": "Rotina é tudo! Pequenos momentos de movimento todos os dias fazem uma diferença enorme. 📅"},
        {"titulo": "Roupa e tênis adequados 👟",
         "itens": ["Roupas leves e confortáveis", "Tênis do tamanho certo", "Protetor solar ao ar livre"],
         "legenda": "Conforto e segurança deixam a atividade muito mais gostosa. Confere o tênis do seu pequeno! 👟"},
        {"titulo": "Respeite o ritmo da criança",
         "itens": ["Cada criança tem seu tempo", "Não compare com outras", "Diversão em primeiro lugar"],
         "legenda": "Cada criança é única! Respeitar o ritmo dela é o caminho para ela amar se movimentar. 🌈"},
        {"titulo": "Fim de semana ativo ☀️",
         "itens": ["Parque, praça ou praia", "Bicicleta, patinete, bola", "Deixe as telas de lado por algumas horas"],
         "legenda": "Fim de semana é perfeito para se movimentar em família! Qual é o programa de vocês hoje? ☀️"},
    ],
    # DOMINGO — frase motivacional
    6: [
        {"titulo": "Criança que brinca é criança que cresce feliz!", "itens": [],
         "legenda": "Domingo é dia de brincar, se movimentar e ser feliz! 💛 Bom domingo, família!"},
        {"titulo": "Movimento é a linguagem da infância.", "itens": [],
         "legenda": "Correr, pular, rolar, dançar... é assim que as crianças descobrem o mundo. 🌍"},
        {"titulo": "Pequenos passos todos os dias fazem grandes campeões.", "itens": [],
         "legenda": "Não precisa ser perfeito, precisa ser constante! Uma ótima semana para todos! 🏆"},
        {"titulo": "O melhor treino é aquele que parece brincadeira!", "itens": [],
         "legenda": "Esse é o nosso lema aqui no JP Personal Kids! 🎉"},
        {"titulo": "Cuidar do corpo desde cedo é um presente para a vida toda.", "itens": [],
         "legenda": "Hábitos saudáveis construídos na infância acompanham a gente para sempre. 🎁"},
        {"titulo": "Toda criança é capaz. Basta acreditar e se divertir!", "itens": [],
         "legenda": "Acredite no seu pequeno e celebre cada conquista! 🌟"},
        {"titulo": "Desliga a tela, liga a diversão!", "itens": [],
         "legenda": "Que tal um domingo com mais brincadeira e menos tela? 📵➡️⚽"},
        {"titulo": "Família que se movimenta junta, fica junta!", "itens": [],
         "legenda": "Movimento também é conexão. Aproveitem o domingo juntos! 👨‍👩‍👧‍👦"},
    ],
}

HASHTAGS_FIXAS = [
    "#personalkids", "#jppersonalkids", "#educacaofisica", "#criancaativa",
    "#atividadefisicainfantil", "#brincadeiras", "#infanciasaudavel",
]

HASHTAGS_TEMA = {
    0: ["#exerciciosparacriancas", "#treinoinfantil", "#dicadodia"],
    1: ["#saudeinfantil", "#beneficiosdoexercicio", "#desenvolvimentoinfantil"],
    2: ["#brincadeirasinfantis", "#brincarecoisaseria", "#brincadeirasemcasa"],
    3: ["#mitoouverdade", "#saudeinfantil", "#informacao"],
    4: ["#desafio", "#desafiodasemana", "#paisefilhos"],
    5: ["#dicaparapais", "#maternidade", "#paternidade"],
    6: ["#motivacao", "#bomdomingo", "#familia"],
}

# Post de divulgação das aulas (python gerar_post.py --divulgacao)
HORARIO_DIVULGACAO = "Terça, quarta ou quinta às 19:30"
DIVULGACAO = {
    "titulo": "Seu filho mais ativo, forte e feliz!",
    "marcador": "check",
    "itens": [
        "Aulas personalizadas para cada idade",
        "Treino em forma de brincadeira",
        "Coordenação, força e equilíbrio",
        "Mais confiança e autoestima",
        "Acompanhamento de perto",
    ],
    "cta": "AGENDE UMA AULA EXPERIMENTAL",
    "legenda": (
        "🎉 Chegou a hora do seu filho trocar a tela pelo movimento!\n\n"
        "No JP Personal Kids, cada aula é pensada para a idade e o ritmo da criança, "
        "com exercícios em forma de brincadeira que desenvolvem:\n\n"
        "✅ Coordenação motora\n"
        "✅ Força e equilíbrio\n"
        "✅ Confiança e autoestima\n"
        "✅ Hábitos saudáveis para a vida toda\n\n"
        "Aqui, o melhor treino é aquele que parece brincadeira! 💛\n\n"
        "📲 Agende uma AULA EXPERIMENTAL: é só chamar no direct ou comentar \"EU QUERO\" que a gente te responde!\n\n"
        "👉 Marque aqui um pai ou mãe que precisa conhecer o Personal Kids!"
    ),
}
