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
API_KEY        = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = int(os.getenv("CHAT_ID"))

# Configura logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Helpers de API ─────────────────────────────────────────────────

def parse_datetime(ts: str) -> datetime:
    """
    Converte string ISO (com Z ou offset) em datetime timezone-aware.
    """
    if ts.endswith("Z"):
        ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
    """
    Busca fixtures da API-Football. 
    - live=True para ao vivo, 
    - date="YYYY-MM-DD" para data fixa.
    """
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
    """
    Formata lista de jogos (horário e times).
    """
    if not jogos:
        return "_Nenhum jogo encontrado._\n"
    lines = []
    for j in jogos:
        ts = j["fixture"]["date"]
        dt = parse_datetime(ts)
        hora = dt.strftime("%H:%M")
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        lines.append(f"🕒 {hora} – ⚽ {home} x {away}")
    return "\n".join(lines) + "\n"

def get_odds_message():
    """
    Monta mensagem de odds de gols e escanteios para ao vivo e próximos 3h.
    """
    agora   = datetime.now(timezone.utc)
    daqui3h = agora + timedelta(hours=3)

    # Busca ao vivo e próximos
    live = fetch_fixtures(live=True)
    prox = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_datetime(j["fixture"]["date"]) <= daqui3h
    ]

    msg = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [("📺 Jogos Ao Vivo", live), ("⏳ Jogos Próximos (até 3h)", prox)]:
        msg.append(f"{title}:\n")
        if not jogos:
            msg.append("_Nenhum jogo encontrado._\n\n")
            continue

        for j in jogos:
            fid = j["fixture"]["id"]
            ts  = j["fixture"]["date"]
            dt  = parse_datetime(ts)
            hora= dt.strftime("%H:%M")
            home = j["teams"]["home"]["name"]
            away = j["teams"]["away"]["name"]
            msg.append(f"🕒 {hora} – ⚽ {home} x {away}\n")

            # Busca odds
            odds_resp = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={fid}",
                headers={"x-apisports-key": API_KEY}
            )
            odds_data = odds_resp.json().get("response", [])
            if not odds_data:
                msg.append("  Sem odds disponíveis.\n\n")
                continue

            mercados = {}
            for b in odds_data[0].get("bookmakers", []):
                for bet in b.get("bets", []):
                    nome = bet["name"].lower()
                    if "goals" in nome:
                        mercados.setdefault("gols", bet["values"])
                    elif "corners" in nome:
                        mercados.setdefault("escanteios", bet["values"])

            # Adiciona valores
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
        "/proximos   – Jogos que começam em até 3h\n"
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
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown"
    )

async def proximos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agora   = datetime.now(timezone.utc)
    daqui3h = agora + timedelta(hours=3)
    prox = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_datetime(j["fixture"]["date"]) <= daqui3h
    ]
    text = "⏳ *Jogos Próximos (até 3h):*\n" + format_games(prox)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown"
    )

async def tendencias_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    live = fetch_fixtures(live=True)
    destaque = []
    for j in live:
        # Exemplo: inclui todos! Ajuste seu critério
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        destaque.append(f"{home} x {away}")
    text = "📊 *Tendências de Escanteios (Ao Vivo):*\n" + "\n".join(destaque)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown"
    )

async def odds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_odds_message()
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=msg, parse_mode="Markdown"
    )

async def automatic_odds(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("🚀 Executando envio automático de odds...")
        msg = get_odds_message()
        await context.bot.send_message(
            chat_id=CHAT_ID, text=msg, parse_mode="Markdown"
        )
        logger.info("✅ Envio automático feito com sucesso")
    except Exception:
        logger.exception("❌ Falha no envio automático")

# ─── Início do Bot ─────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Registra comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("jogos", jogos_command))
    app.add_handler(CommandHandler("proximos", proximos_command))
    app.add_handler(CommandHandler("tendencias", tendencias_command))
    app.add_handler(CommandHandler("odds", odds_command))

    # Agenda envio automático a cada 600s, 1ª execução em 5s
    app.job_queue.run_repeating(automatic_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e ouvindo comandos…")
    app.run_polling()

if __name__ == "__main__":
    main()
