import os
import logging
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# Carrega variáveis de ambiente
load_dotenv()
API_KEY       = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN= os.getenv("TELEGRAM_TOKEN")
CHAT_ID       = int(os.getenv("CHAT_ID"))

# Configura logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Funções de consulta ─────────────────────────────────────────────

def fetch_fixtures(live=None, date=None):
    """Helper: busca fixtures da API-Football."""
    url = "https://v3.football.api-sports.io/fixtures"
    params = {}
    if live is not None:   params["live"] = "all"
    if date is not None:   params["date"] = date
    headers = {"x-apisports-key": API_KEY}
    r = requests.get(url, headers=headers, params=params)
    return r.json().get("response", [])

def format_games(jogos):
    """Retorna texto com lista de jogos (horário e times)."""
    if not jogos:
        return "_Nenhum jogo encontrado._\n"
    lines = []
    for j in jogos:
        dt = datetime.fromisoformat(j["fixture"]["date"][:-1]).replace(tzinfo=timezone.utc)
        hora = dt.strftime("%H:%M")
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        lines.append(f"🕒 {hora} – ⚽ {home} x {away}")
    return "\n".join(lines) + "\n"

def get_odds_message():
    """Cria mensagem com odds de gols e escanteios."""
    agora   = datetime.now(timezone.utc)
    daqui3h = agora + timedelta(hours=3)
    # busca ao vivo e próximos
    live = fetch_fixtures(live=True)
    prox = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= datetime.fromisoformat(j["fixture"]["date"][:-1]).replace(tzinfo=timezone.utc) <= daqui3h
    ]

    msg = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [("📺 Jogos Ao Vivo", live), ("⏳ Jogos Próximos (até 3 h)", prox)]:
        msg.append(f"{title}:\n")
        if not jogos:
            msg.append("_Nenhum jogo encontrado._\n\n")
            continue

        for j in jogos:
            fid = j["fixture"]["id"]
            dt = datetime.fromisoformat(j["fixture"]["date"][:-1]).replace(tzinfo=timezone.utc)
            hora = dt.strftime("%H:%M")
            home = j["teams"]["home"]["name"]
            away = j["teams"]["away"]["name"]
            msg.append(f"🕒 {hora} – ⚽ {home} x {away}\n")

            # busca odds do fixture
            odds = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={fid}",
                headers={"x-apisports-key": API_KEY}
            ).json().get("response", [])
            if not odds:
                msg.append("  Sem odds disponíveis.\n\n")
                continue

            mercados = {}
            for b in odds[0].get("bookmakers", []):
                for bet in b.get("bets", []):
                    n = bet["name"].lower()
                    if "goals" in n:
                        mercados.setdefault("gols", bet["values"])
                    elif "corners" in n:
                        mercados.setdefault("escanteios", bet["values"])

            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    msg.append(f"  ⚽ Gols {v['value']}: {v['odd']}\n")
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    msg.append(f"  🥅 Escanteios {v['value']}: {v['odd']}\n")
            msg.append("\n")

    return "".join(msg)

# ─── Handlers Telegram ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Sou seu Robô de Monitoramento de Odds!\n\n"
        "Comandos:\n"
        "/jogos      – Listar jogos ao vivo\n"
        "/proximos   – Listar jogos próximos (até 3 h)\n"
        "/tendencias – Jogos com alta tendência de escanteios\n"
        "/odds       – Odds de gols & escanteios\n"
        "/start      – Boas-vindas\n"
        "/ajuda      – Esta ajuda"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def jogos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    live = fetch_fixtures(live=True)
    text = "📺 *Jogos Ao Vivo:*\n" + format_games(live)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

async def proximos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agora   = datetime.now(timezone.utc)
    daqui3h = agora + timedelta(hours=3)
    prox = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= datetime.fromisoformat(j["fixture"]["date"][:-1]).replace(tzinfo=timezone.utc) <= daqui3h
    ]
    text = "⏳ *Jogos Próximos (até 3 h):*\n" + format_games(prox)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

async def tendencias_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Exemplo simples: quem tem média de >4 corners/jogo (você pode aprimorar)
    # Aqui fazemos uma busca genérica nos jogos ao vivo:
    live = fetch_fixtures(live=True)
    destaque = []
    for j in live:
        vals = requests.get(
            f"https://v3.football.api-sports.io/statistics?fixture={j['fixture']['id']}",
            headers={"x-apisports-key": API_KEY}
        ).json().get("response", [])
        # supondo que response tenha dados de corners
        corners = next((s["statistics"] for s in vals if s["team"]["id"]==j["teams"]["home"]["id"]), [])
        # ... implementar seu critério real aqui ...
        # Para fins de exemplo vamos incluir todos
        destaque.append(f"{j['teams']['home']['name']} x {j['teams']['away']['name']}")
    text = "📊 *Tendências de Escanteios (Ao Vivo):*\n" + "\n".join(destaque) + "\n"
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")

async def odds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_odds_message()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown")

async def automatic_odds(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("🚀 Executando envio automático de odds...")
        msg = get_odds_message()
        await context.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
        logger.info("✅ Envio automático feito com sucesso")
    except Exception:
        logger.exception("❌ Falha no envio automático")

# ─── Início do bot ──────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # registra handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("jogos", jogos_command))
    app.add_handler(CommandHandler("proximos", proximos_command))
    app.add_handler(CommandHandler("tendencias", tendencias_command))
    app.add_handler(CommandHandler("odds", odds_command))

    # agenda envio automático
    app.job_queue.run_repeating(automatic_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e ouvindo comandos…")
    app.run_polling()

if __name__ == "__main__":
    main()
