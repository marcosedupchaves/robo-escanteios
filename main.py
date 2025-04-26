import os
import logging
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv
from telegram import Update, BotCommand
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

# ─── Funções Auxiliares ──────────────────────────────────────────────

def parse_dt(ts: str) -> datetime:
    """Converte ISO (com 'Z' ou '+00:00') em datetime tz-aware."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
    """Busca fixtures ao vivo (live=True) ou por date='YYYY-MM-DD'."""
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
        out.append(f"🕒 {dt.strftime('%H:%M')} – ⚽ "
                   f"{j['teams']['home']['name']} x {j['teams']['away']['name']}")
    return "\n".join(out) + "\n"

def build_odds_message():
    """Monta texto de odds de gols e escanteios (ao vivo + próximos 3h)."""
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
            lines.append(f"🕒 {dt.strftime('%H:%M')} – ⚽ "
                         f"{j['teams']['home']['name']} x {j['teams']['away']['name']}\n")

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
                    if "goals" in n:    mercados.setdefault("gols", bet["values"])
                    if "corners" in n:  mercados.setdefault("escanteios", bet["values"])

            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    lines.append(f"  ⚽ {v['value']}: {v['odd']}\n")
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    lines.append(f"  🥅 {v['value']}: {v['odd']}\n")
            lines.append("\n")

    return "".join(lines)

# ─── Handlers Telegram ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /start")
    await update.message.reply_text(
        "👋 Olá! Sou seu Robô de Monitoramento de Odds!\n\n"
        "/jogos      – Listar jogos ao vivo\n"
        "/proximos   – Jogos que começam em até 3h\n"
        "/tendencias – Alta tendência de escanteios\n"
        "/odds       – Odds de gols & escanteios\n"
        "/ajuda      – Esta ajuda"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /ajuda")
    # Reaproveita a mesma mensagem do /start
    await start(update, context)

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /jogos")
    text = "📺 *Jogos Ao Vivo:*\n" + format_games(fetch_fixtures(live=True))
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /proximos")
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=3)
    prox   = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]
    text = "⏳ *Próximos (3h):*\n" + format_games(prox)
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def tendencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /tendencias")
    ao_vivo = fetch_fixtures(live=True)
    lista   = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in ao_vivo]
    text = "📊 *Tendências Ao Vivo:*\n" + ("\n".join(lista) or "_Nenhum_\n")
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def odds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /odds")
    try:
        msg = build_odds_message()
    except Exception:
        logger.exception("Error building odds message")
        await update.message.reply_text("❌ Erro ao montar as odds.")
        return
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("Job automático: enviando odds")
        msg = build_odds_message()
        await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        logger.info("Envio automático OK")
    except Exception:
        logger.exception("Falha no envio automático")

# ─── Main ────────────────────────────────────────────────────────────

def main():
    # Inicializa aplicação
    app = ApplicationBuilder().token(TOKEN).build()

    # Registra comandos para o cliente Telegram mostrar sugestões
    app.bot.set_my_commands([
        BotCommand("start", "Inicia o bot"),
        BotCommand("ajuda", "Mostra ajuda"),
        BotCommand("jogos", "Lista jogos ao vivo"),
        BotCommand("proximos", "Jogos que começam em até 3h"),
        BotCommand("tendencias", "Tendências de escanteios"),
        BotCommand("odds", "Odds de gols & escanteios"),
    ])

    # Adiciona handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("jogos", jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias", tendencias))
    app.add_handler(CommandHandler("odds", odds_cmd))

    # Agenda automático: 1ª em 5s, depois a cada 600s
    app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
