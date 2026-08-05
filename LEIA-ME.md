# RADAR DE VOOS NA NUVEM — grátis, 24/7, PC desligado

Corre no GitHub Actions de hora em hora e envia alerta para o teu Telegram
quando o preço bate no alvo ou fica abaixo do mínimo histórico.
O link do alerta já sai com o teu marker de afiliado (558799).

## Instalar (15 minutos, uma vez)

### 1. Criar o bot do Telegram (o teu canal de alertas)
1. No Telegram, fala com **@BotFather** → envia `/newbot` → dá um nome → ele devolve o **token** (guarda).
2. Fala com **@userinfobot** → ele devolve o teu **chat id** (um número — guarda).
3. Abre uma conversa com o teu novo bot e envia-lhe um "olá" (senão ele não te pode escrever).

### 2. Criar o repositório no GitHub
1. Entra em github.com → **New repository** → nome `radar-voos` → **Public**
   (público = minutos ilimitados grátis; as tuas chaves ficam em Secrets, invisíveis).
2. Carrega para lá estes 3 ficheiros com a MESMA estrutura de pastas:
   - `.github/workflows/radar.yml`
   - `radar_nuvem.py`
   - `LEIA-ME.md`
   (podes arrastar no site ou usar o Claude Code: `git init`, `git add .`, `git push`)

### 3. Colar as chaves (Secrets)
No repositório: **Settings → Secrets and variables → Actions → New repository secret**
Cria estes (os 2 primeiros são obrigatórios; os motores, cola os que tiveres):
- `TELEGRAM_TOKEN` — o token do BotFather
- `TELEGRAM_CHAT_ID` — o número do userinfobot
- `AMADEUS_KEY` e `AMADEUS_SECRET` — developers.amadeus.com (opcional)
- `SERPAPI_KEY` — a tua chave de 64 caracteres (opcional)
- `TP_TOKEN` — o teu token Travelpayouts (opcional)

### 4. Ligar e testar
1. Separador **Actions** → ativa os workflows se ele pedir.
2. Abre "Radar de Voos 24/7" → **Run workflow** → em ~1 minuto vês o registo;
   se o preço estiver no alvo, chega o alerta ao Telegram.
3. A partir daí corre sozinho a cada hora, para sempre, grátis.

## Mudar rota, datas, alvo
Edita o ficheiro `.github/workflows/radar.yml` (secção `env:`) diretamente no site
do GitHub: ORIGEM, DESTINO, DATA_IDA, DATA_VOLTA, PAX, ALVO. Guarda e pronto.

## Histórico
Cada verificação fica gravada em `precos.json` no repositório — o teu gráfico
de evolução de preços, de borla.

## Canais extra de envio automático (opcionais)

### Discord (grupo/servidor teu — automação total)
No teu servidor: Definições do canal → Integrações → Webhooks → Novo webhook → copia o URL
e cria o Secret `DISCORD_WEBHOOK` com ele. Pronto — cada promoção cai lá sozinha.

### WhatsApp (para TI — via CallMeBot, grátis)
1. Guarda o número +34 644 71 81 99 nos contactos.
2. Envia-lhe pelo WhatsApp: "I allow callmebot to send me messages"
3. Ele responde com a tua apikey.
4. Cria os Secrets `WHATSAPP_PHONE` (teu número com indicativo, ex. 3519XXXXXXXX)
   e `CALLMEBOT_APIKEY`. Os alertas passam a chegar ao teu WhatsApp.
Para AUDIÊNCIA no WhatsApp: cria um Canal do WhatsApp e encaminha o alerta do
Telegram (10 segundos) — robôs em grupos/canais violam os termos e banem o número.

### LinkedIn, Facebook e X (ponte por RSS — automação total)
O radar publica cada promoção em `feed.xml` no repositório. O endereço público é:
`https://raw.githubusercontent.com/O-TEU-USER/radar-voos/main/feed.xml`
1. Cria conta grátis em **dlvr.it** (ou Zapier/Make).
2. Adiciona esse feed como fonte e liga os destinos: LinkedIn, página do Facebook, X.
3. A partir daí, cada alerta do radar é publicado sozinho nessas redes.
