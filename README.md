# pg_avisaIncentivo

Monitor automático para o aviso de incentivo à compra de carro elétrico em Portugal (Fundo Ambiental — Mobilidade Verde 2026). Verifica fontes oficiais e noticiosas a cada 5 minutos via GitHub Actions e dispara notificações instantâneas em vários canais quando detecta sinais de abertura.

## Como funciona

1. `monitor/sources.py` define a lista de fontes (HTML do Fundo Ambiental, portal do Governo, RSS de Google News).
2. A cada 5 min, o GitHub Actions corre `python -m monitor.main`:
   - Faz fetch de cada fonte.
   - Normaliza o conteúdo e calcula um hash.
   - Compara com o estado anterior em `state.json`.
   - Se mudou: classifica como `ALERT` (apareceram keywords críticas como "candidaturas", "Mobilidade Verde", "2026", "aviso") ou `INFO` (mudança cosmética).
   - Dispara para todos os canais configurados.
   - Faz commit do `state.json` atualizado.

## Canais suportados

| Canal | Quando | Setup |
|---|---|---|
| **ntfy.sh** | sempre (recomendado) | instala app, segue tópico secreto |
| **Email** | sempre | SMTP (Gmail App Password) |
| **Telegram** | opcional | criar bot via @BotFather |
| **Discord** | opcional | webhook num canal |

## Setup

### 1. ntfy.sh (push para o telemóvel)

1. Instala a app **ntfy** (Android/iOS).
2. Escolhe um nome de tópico **único e secreto** (qualquer pessoa que adivinhe consegue ouvir). Exemplo: `pg-incentivo-ev-7f3a9b`.
3. Na app, "Subscribe to topic" → cola o nome.
4. Adiciona o tópico ao secret `NTFY_TOPIC` no GitHub.

### 2. Email (Gmail)

1. Vai a https://myaccount.google.com/apppasswords (precisa de 2FA ativo).
2. Cria uma App Password chamada `pg_avisaIncentivo`. Copia a password de 16 caracteres.
3. Adiciona aos GitHub secrets:
   - `EMAIL_USER` = teu email Gmail
   - `EMAIL_PASSWORD` = a app password
   - `EMAIL_TO` = email destino (pode ser o mesmo)

### 3. Telegram (opcional)

1. Fala com [@BotFather](https://t.me/BotFather) → `/newbot` → escolhe nome → copia o token.
2. Manda uma mensagem ao teu novo bot.
3. Vai a `https://api.telegram.org/bot<TOKEN>/getUpdates` e copia o `chat.id`.
4. Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

### 4. Discord (opcional)

Server settings → Integrations → Webhooks → New → copia URL → secret `DISCORD_WEBHOOK_URL`.

### 5. Configurar GitHub Secrets

No repo: **Settings → Secrets and variables → Actions → New repository secret**. Adiciona os secrets que quiseres usar. Os outros podem ficar vazios.

## Correr localmente (teste)

```bash
python -m venv .venv
. .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # preencher secrets
# Carregar .env (PowerShell): Get-Content .env | ForEach-Object { if ($_ -match '^(\w+)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] } }
python -m monitor.main
```

A primeira execução vai disparar `INFO` para todas as fontes (estado inicial). Depois disso só notifica em mudanças reais.

## Frequência

`*/5 * * * *` por defeito. Para apertar a janela em maio/junho 2026, mudar para `*/2 * * * *` em `.github/workflows/monitor.yml`.

> Nota: o GitHub pode atrasar crons em períodos de carga. Os 5 min são best-effort — na prática a latência típica fica entre 5–10 min.
