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

# Carrega variáveis de ambiente de um arquivo .env
load_dotenv()
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID          = int(os.getenv("CHAT_ID"))

# Configura o logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def get_odds():
    """Consulta a API-Football e retorna a mensagem formatada."""
    agora   = datetime.now(timezone.utc)
    daqui3h = agora + timedelta(hours=3)
    headers = {"x-apisports-key": API_FOOTBALL_KEY}

    # Jogos ao vivo
    resp_live = requests.get(
        "https://v3.football.api-sports.io/fixtures?live=all",
        headers=headers
    )
    live = resp_live.json().get("response", [])

    # Próximos jogos em até 3h
    resp_prox = requests.get(
        f"https://v3.football.api-sports.io/fixtures?date={agora.date()}",
        headers=headers
    )
    prox = []
    for j in resp_prox.json().get("response", []):
        # parse da data
        data = datetime.strptime(j["fixture"]["date"][:19], "%Y-%m-%dT%H:%M:%S")\
                    .replace(tzinfo=timezone.utc)
        if agora <= data <= daqui3h:
            prox.append(j)

    categorias = {
        "📺 Jogos Ao Vivo": live,
        "⏳ Jogos Próximos (até 3h)": prox
    }

    linhas = ["📊 *Odds de Gols e Escanteios:*\n"]
    for titulo, jogos in categorias.items():
        linhas.append(f"{titulo}:\n")
        if not jogos:
            linhas.append("_Nenhum jogo encontrado._\n\n")
            continue

        for j in jogos:
            fid   = j["fixture"]["id"]
            home  = j["teams"]["home"]["name"]
            away  = j["teams"]["away"]["name"]
            hora  = datetime.strptime(j["fixture"]["date"][:19], "%Y-%m-%dT%H:%M:%S")\
                         .strftime("%H:%M")
            linhas.append(f"🕒 {hora} - ⚽ {home} x {away}\n")

            odds_resp = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={fid}",
                headers=headers
            )
            odds_data = odds_resp.json().get("response", [])
            if not odds_data:
                linhas.append("  Sem odds disponíveis.\n\n")
                continue

            # Pega mercados de gols e escanteios em qualquer casa
            mercados = {}
            for book in odds_data[0].get("bookmakers", []):
                for bet in book.get("bets", []):
                    nome = bet["name"].lower()
                    if "goals" in nome:
                        mercados.setdefault("gols", bet["values"])
                    elif "corners" in nome:
                        mercados.setdefault("escanteios", bet["values"])

            # Adiciona linhas de odds
            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    linhas.append(f"  ⚽ Gols {v['value']}: {v['odd']}\n")
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    linhas.append(f"  🥅 Escanteios {v['value']}: {v['odd']}\n")
            linhas.append("\n")

    return "".join(linhas)

# ------- Handlers --------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Sou seu Robô de Monitoramento de Odds!\n\n"
        "Use:\n"
        "/odds  – Ver odds agora\n"
        "/start – Boas-vindas\n"
        "/ajuda – Comandos disponíveis"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Comandos:\n"
        "/odds  – Mostrar odds de gols e escanteios\n"
        "/start – Inicia o bot\n"
        "/ajuda – Esta ajuda"
    )

async def odds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_odds()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=msg,
        parse_mode="Markdown"
    )

async def automatic_odds(context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("🚀 Executando envio automático de odds...")
        msg = get_odds()
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="Markdown"
        )
        logger.info("✅ Envio automático feito com sucesso")
    except Exception:
        logger.exception("❌ Falha no envio automático")

# ------- Função principal --------
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Registra comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("odds", odds_command))

    # Agenda envio automático: 1ª execução em 5s, depois a cada 600s (10 min)
    app.job_queue.run_repeating(automatic_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e ouvindo comandos e agendamentos...")
    app.run_polling()

if __name__ == "__main__":
    main()
