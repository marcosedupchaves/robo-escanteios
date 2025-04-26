import os
import telegram
from telegram.ext import Updater, CommandHandler
from monitor_odds import odds_command
from dotenv import load_dotenv
import threading
import time

# Carrega as variáveis de ambiente
load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = int(os.getenv('CHAT_ID'))

bot = telegram.Bot(token=TELEGRAM_TOKEN)

# Envio automático de odds
def enviar_odds_automaticamente():
    while True:
        try:
            odds_command(None, None)
            print("✅ Mensagem automática enviada com sucesso!")
        except Exception as e:
            print(f"❌ Erro ao enviar mensagem automática: {e}")
        time.sleep(600)  # 10 minutos

# Comandos
def start(update, context):
    update.message.reply_text(
        "👋 Olá! Eu sou seu Robô de Monitoramento de Odds!\n\n"
        "Use os comandos:\n"
        "/odds - Ver odds de gols e escanteios\n"
        "/start - Mensagem de boas-vindas\n"
        "/ajuda - Mostrar comandos"
    )

def ajuda(update, context):
    update.message.reply_text(
        "📋 Comandos disponíveis:\n"
        "/odds - Ver odds\n"
        "/start - Boas-vindas\n"
        "/ajuda - Esta ajuda"
    )

updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
dispatcher = updater.dispatcher

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("ajuda", ajuda))
dispatcher.add_handler(CommandHandler("odds", odds_command))

print("🤖 Bot ouvindo todos os comandos...")
updater.start_polling()

# Rodar o envio automático paralelo
threading.Thread(target=enviar_odds_automaticamente, daemon=True).start()

updater.idle()
