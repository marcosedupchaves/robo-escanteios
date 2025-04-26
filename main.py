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

# ─── Configuração ────────────────────────────────────────────────────

load_dotenv()
API_KEY = os.getenv("API_FOOTBALL_KEY")
TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

logging.basicConfig(
    format="%(asctime)s %(levelname)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Helpers ─────────────────────────────────────────────────────────

def parse_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
    url = "https://v3.football.api-sports.io/fixtures"
    params = {}
    if live is not None:
        params["live"] = "all"
    if date:
        params["date"] = date
    headers = {"x-apisports-key": API_KEY}
    return requests.get(url, headers=headers, params=params).json().get("response", [])

def format_games(jogos):
    if not jogos:
        return "_Nenhum jogo encontrado._\n"
    out = []
    for j in jogos:
        dt = parse_dt(j["fixture"]["date"])
        hora = dt.strftime("%H:%M")
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        out.append(f"🕒 {hora} – ⚽ {home} x {away}")
    return "\n".join(out) + "\n"

def build_odds_message():
    agora   = datetime.now(timezone.utc)
    limite  = agora + timedelta(hours=3)
    ao_vivo = fetch_fixtures(live=True)
    proximos = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]

    lines = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [("📺 Jogos Ao Vivo", ao_vivo), ("⏳ Próximos (3h)", proximos)]:
        lines.append(f"{title}:\n")
        if not jogos:
            lines.append("_Nenhum jogo encontrado._\n\n")
            continue
        for j in jogos:
            fid = j["fixture"]["id"]
            dt  = parse_dt(j["fixture"]["date"])
            hora = dt.strftime("%H:%M")
            home = j["teams"]["home"]["name"]
            away = j["teams"]["away"]["name"]
            lines.append(f"🕒 {hora} – ⚽ {home} x {away}\n")

            odds = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={fid}",
                headers={"x-apisports-key": API_KEY}
            ).json().get("response", [])
            if not odds:
                lines.append("  Sem odds disponíveis.\n\n")
                continue

            mercados = {}
            for book in odds[0].get("bookmakers", []):
                for bet in book.get("bets", []):
                    n = bet["name"].lower()
                    if "goals" in n:
                        mercados.setdefault("gols", bet["values"])
                    if "corners" in n:
                        mercados.setdefault("escanteios", bet["values"])
            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    lines.append(f"  ⚽ {v['value']}: {v['odd']}\n")
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    lines.append(f"  🥅 {v['value']}: {v['odd']}\n")
            lines.append("\n")

    return "".join(lines)

# ─── Handlers ────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Recebido /start")
    await update.message.reply_text(
        "👋 Olá! Sou seu Robô de Odds!\n\n"
        "Comandos:\n"
        "/jogos      – Listar ao vivo\n"
        "/proximos   – Próximos (3h)\n"
        "/tendencias – Tendências escanteios\n"
        "/odds       – Odds de gols & escanteios\n"
        "/ajuda      – Esta ajuda\n"
        "/start      – Boas-vindas"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Recebido /ajuda")
    # Reusa a mensagem de start
    await start(update, context)

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Recebido /jogos")
    text = "📺 *Jogos Ao Vivo:*\n" + format_games(fetch_fixtures(live=True))
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Recebido /proximos")
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=3)
    prox   = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]
    text = "⏳ *Próximos (3h):*\n" + format_games(prox)
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def tendencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Recebido /tendencias")
    ao_vivo = fetch_fixtures(live=True)
    lista   = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in ao_vivo]
    text = "📊 *Tendências Ao Vivo:*\n" + ("\n".join(lista) or "_Nenhum_\n")
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def odds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Recebido /odds")
    msg = build_odds_message()
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("Job automático: enviando odds")
        msg = build_odds_message()
        await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        logger.info("Envio automático OK")
    except Exception:
        logger.exception("Falha no envio automático")

# ─── Setup & Run ─────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # registra comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("jogos", jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias", tendencias))
    app.add_handler(CommandHandler("odds", odds_cmd))

    # agendamento automático: 1ª exec em 5s, depois a cada 600s
    app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
