# CS2 Coach

Analisa suas partidas de CS2 (Premier, Competitivo e FACEIT) **depois** que elas terminam, a partir das demos:
nota, ADR, KAST, duelos, mortes no radar, utilitária, economia, mira e counter-strafe. Tudo calculado das demos, sem IA.

## Segurança (VAC / FACEIT AC)

O programa só usa caminhos oficiais e passivos:

| O que faz | Por que é seguro |
|---|---|
| Sabe se você está jogando pela janela ativa do Windows | Só pergunta ao Windows qual programa está em primeiro plano. Nada é lido do jogo. |
| Game State Integration (**desligado por padrão**) | Recurso oficial da Valve, mas neste PC deixou as animações do CS lentas. Para religar: `GSI_ENABLED=1` no `.env`. |
| Lê arquivos `.dem` | Arquivo em disco, lido depois da partida. Os originais nunca são alterados. |
| Steam Web API / FACEIT Data API | APIs públicas oficiais, com as suas chaves (opcionais). |
| Janela da FACEIT dentro do app | Você faz login nela; o app abre o histórico e clica em "Assistir demo", uma partida por vez, como você faria. A senha nunca passa pelo app. |

O que ele **não** faz: não lê nem escreve memória do jogo, não injeta nada, não desenha overlay,
não envia teclas/mouse, não faz login na sua conta Steam, não fala com o Game Coordinator.
Enquanto há partida em andamento, ele não importa demos nem chama APIs.

## Instalação

1. Instale o [Python 3.12+](https://www.python.org/downloads/) (marque "Add python.exe to PATH") e o
   [Node.js LTS](https://nodejs.org/).
2. Baixe este projeto e dê dois cliques em **`instalar.bat`**. Ele prepara tudo, cria os atalhos e abre o app.
3. No app, siga o **Comece por aqui** da tela inicial.

As configurações são feitas **pela tela Configurações do app** (ícone de engrenagem), com passo a passo.
Chaves ficam no Gerenciador de Credenciais do Windows; o `.env` (copie de `.env.example`) é só uma reserva opcional.

Abra pelo atalho **CS2 Coach** (Área de Trabalho ou Menu Iniciar) quando quiser ver suas partidas.
Ao abrir, ele importa as demos novas (pasta do CS2, Downloads e FACEIT). Fechar a janela encerra o app.

Na primeira execução ele cria `gamestate_integration_coach.cfg` na pasta `cfg` do CS2.
**Reinicie o CS2** depois disso. Sem janela (só serviço): `python -m coach.main`.

## Chaves

1. **FACEIT**: só o seu nick (Configurações). Sem chave e sem aprovação. Depois da partida, clique em
   **Partidas na FACEIT** → partida → **Assistir demo**; o app pega o arquivo da pasta Downloads.
   - Opcional: com uma chave Server side do developers.faceit.com, a partida aparece na lista assim que termina.
   - Sem ele: na sala da partida, clique em "Assistir demo"/baixar. A pasta Downloads é monitorada.
2. **Steam** (Premier/Competitivo):
   - `STEAM_WEB_API_KEY`: steamcommunity.com/dev/apikey (domínio pode ser `localhost`).
   - `STEAM_AUTH_CODE` e `STEAM_LAST_SHARECODE`: help.steampowered.com → CS2 → "Acesso ao histórico
     de partidas" → crie o código de autenticação; o share code mais recente aparece na mesma página.
   - `STEAM_ID64`: opcional, é aprendido pelo GSI.
   - A Valve não fornece a URL da demo por API pública. Depois da partida, no CS2:
     **Assistir → Suas partidas → baixar**. O programa importa a demo e liga pelo share code.

## Testes

```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m tools.simulate_gsi
```

O segundo envia uma partida falsa para o programa em execução (use um banco de teste ou apague
`data\coach.db` depois).

## Dados

Tudo fica em `data/` (fora do git): `coach.db` (SQLite), `demos/` (cópias das demos), `logs/coach.log`.
API local: `http://127.0.0.1:31982/api/status`, `/api/matches`, `/api/matches/{id}/rounds`, `/api/demos`.
