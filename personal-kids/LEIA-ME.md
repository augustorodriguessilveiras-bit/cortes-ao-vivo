# JP Personal Kids — gerador de posts para o Instagram

Gera todo dia um post pronto com a **logo original** (recortada da imagem enviada, sem redesenho),
nas cores da marca, mais a legenda, hashtags e o **horário sugerido para postar**.

## Como usar
```
pip install pillow
python gerar_post.py              # post de hoje
python gerar_post.py 2026-12-24   # post de uma data
python gerar_post.py --semana     # 7 posts a partir de hoje
python gerar_post.py --divulgacao # post de divulgação das aulas (saida/divulgacao/)
```
Os arquivos saem em `saida/AAAA-MM-DD/`: `post.png` (feed 4:5), `story.png` (stories) e `legenda.txt`.

## Temas da semana e horários (Brasília)
| Dia | Tema | Postar às |
|---|---|---|
| Segunda | Dica de exercício | 19:30 |
| Terça | Benefícios | 12:00 |
| Quarta | Brincadeira ativa | 19:30 |
| Quinta | Mito ou verdade? | 12:00 |
| Sexta | Desafio da semana | 18:30 |
| Sábado | Dica para os pais | 10:00 |
| Domingo | Frase da semana | 18:00 |

## Personalizar
- `conteudo.py`: textos, legendas, hashtags e horários — é só copiar um bloco e trocar o texto.
- `gerar_post.py`: variável `INSTAGRAM = "@seuperfil"` coloca seu @ no rodapé.
- `assets/logo.png`: sua logo (troque o arquivo se tiver uma versão em alta resolução).
