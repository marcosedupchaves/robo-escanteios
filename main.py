import os
import logging
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# ─── Configuração ────────────────────────────────────────────────────

load_dotenv()
API_KEY = os.getenv("API_FOOTBALL_KEY")
TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))

logging.basicConfig(
    format="%(asctime)s • %(levelname)s • %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Funções auxiliares ──────────────────────────────────────────────

def parse_datetime(ts: str) -> datetime:
    # Converte ISO com 'Z' ou '+00:00'
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool = None, date: str = None):
    url = "https://v3.football.api-sports.io/fixtures"
    params = {}
    if live is not None:
        params["live"] = "all"
    if date is not None:
        params["date"] = date
    headers = {"x-apisports-key": API_KEY}
    resp = requests.get(url, headers=headers, params=params)
    return resp.json().get("response", [])

def format_games(jogos):
    if not jogos:
        return "_Nenhum jogo encontrado._\n"
    out = []
    for j in jogos:
        dt = parse_datetime(j["fixture"]["date"])
        hora = dt.strftime("%H:%M")
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        out.append(f"🕒 {hora} – ⚽ {home} x {away}")
    return "\n".join(out) + "\n"

def build_odds_message():
    agora   = datetime.now(timezone.utc)
    limite  = agora + timedelta(hours=3)
    live    = fetch_fixtures(live=True)
    prox    = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_datetime(j["fixture"]["date"]) <= limite
    ]

    msg = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [("📺 Ao Vivo", live), ("⏳ Próximos (3h)", prox)]:
        msg.append(f"{title}:\n")
        if not jogos:
            msg.append("_Nenhum jogo_\n\n")
            continue
        for j in jogos:
            fid = j["fixture"]["id"]
            dt  = parse_datetime(j["fixture"]["date"])
            hora= dt.strftime("%H:%M")
            home= j["teams"]["home"]["name"]
            away= j["teams"]["away"]["name"]
            msg.append(f"🕒 {hora} – ⚽ {home} x {away}\n")

            odds = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={fid}",
                headers={"x-apisports-key": API_KEY}
            ).json().get("response", [])
            if not odds:
                msg.append("  Sem odds.\n\n")
                continue

            mercados = {}
            for b in odds[0].get("bookmakers", []):
                for bet in b.get("bets", []):
                    n = bet["name"].lower()
                    if "goals" in n:
                        mercados.setdefault("gols", bet["values"])
                    if "corners" in n:
                        mercados.setdefault("escanteios", bet["values"])

            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    msg.append(f"  ⚽ {v['value']}: {v['odd']}\n")
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    msg.append(f"  🥅 {v['value']}: {v['odd']}\n")
            msg.append("\n")

    return "".join(msg)

# ─── Handlers ─────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Cmd /start recebido")
    await update.message.reply_text(
        "👋 Bem-vindo!\n"
        "/jogos      – Jogos ao vivo\n"
        "/proximos   – Jogos próximos (3h)\n"
        "/tendencias – Alta tendência escanteios\n"
        "/odds       – Odds gols e escanteios"
    )

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Cmd /jogos recebido")
    text = "📺 *Jogos Ao Vivo:*\n" + format_games(fetch_fixtures(live=True))
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Cmd /proximos recebido")
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=3)
    prox   = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_datetime(j["fixture"]["date"]) <= limite
    ]
    text = "⏳ *Próximos (3h):*\n" + format_games(prox)
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def tendencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Cmd /tendencias recebido")
    live = fetch_fixtures(live=True)
    desta = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in live]
    text = "📊 *Tendências Ao Vivo:*\n" + ("\n".join(desta) or "_Nenhum_\n")
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def odds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Cmd /odds recebido")
    msg = build_odds_message()
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("Job automático disparado")
        msg = build_odds_message()
        await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        logger.info("Envio automático OK")
    except Exception:
        logger.exception("Falha no envio automático")

# ─── Inicialização ───────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    # registra handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("jogos", jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias", tendencias))
    app.add_handler(CommandHandler("odds", odds_cmd))

    # agendamento a cada 10m, primeiro em 5s
    app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
