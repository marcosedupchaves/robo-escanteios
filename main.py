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
    CallbackContext,
)

# Carrega variáveis de ambiente
load_dotenv()
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID          = int(os.getenv("CHAT_ID"))

# Configura logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Função que consulta odds
def get_odds():
    agora    = datetime.now(timezone.utc)
    daqui3h  = agora + timedelta(hours=3)
    headers  = {"x-apisports-key": API_FOOTBALL_KEY}

    # APENAS para demo, import local:
    from monitor_odds import _build_message
    return _build_message(agora, daqui3h, headers)

# Handler /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Sou seu Robô de Monitoramento de Odds!\n\n"
        "Use:\n"
        "/odds   – Odds agora\n"
        "/start  – Boas-vindas\n"
        "/ajuda  – Comandos"
    )

# Handler /ajuda
async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 Comandos:\n"
        "/odds   – Ver odds de gols e escanteios\n"
        "/start  – Inicia o bot\n"
        "/ajuda  – Esta ajuda"
    )

# Handler /odds manual
async def odds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_odds()
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=msg,
        parse_mode="Markdown"
    )

# Tarefa automática
async def automatic_odds(context: CallbackContext):
    msg = get_odds()
    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=msg,
        parse_mode="Markdown"
    )

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # registra comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("odds", odds_command))

    # agenda envio automático a cada 600s (10 min), primeiro disparo imediato
    jq = app.job_queue
    jq.run_repeating(automatic_odds, interval=600, first=0)

    logger.info("🤖 Bot iniciado e ouvindo comandos...")
    app.run_polling()

if __name__ == "__main__":
    main()
