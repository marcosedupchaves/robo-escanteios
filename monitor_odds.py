import os
import requests
from dotenv import load_dotenv
from telegram import ParseMode

load_dotenv()

API_KEY = os.getenv('API_FOOTBALL_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = int(os.getenv('CHAT_ID'))

def get_odds():
    from datetime import datetime, timedelta
    agora = datetime.utcnow()
    daqui_3h = agora + timedelta(hours=3)

    url = "https://v3.football.api-sports.io/odds/live"
    headers = {
        'x-apisports-key': API_KEY
    }
    response = requests.get(url, headers=headers)
    jogos = response.json().get('response', [])

    odds_msg = "📊 *Odds de Gols e Escanteios:*\n"

    if jogos:
        odds_msg += "📺 *Jogos Ao Vivo:*\n"
        for j in jogos:
            times = f"{j['teams']['home']['name']} x {j['teams']['away']['name']}"
            horario = datetime.fromisoformat(j['fixture']['date'][:-1]).strftime('%H:%M')
            odds_msg += f"🕒 {horario} - ⚽ {times}\n"
            mercados = j.get('bookmakers', [])
            for mercado in mercados:
                if mercado['betting_type'] == "Goals Over/Under":
                    for aposta in mercado['bets']:
                        odds_msg += f"  ⚽ {aposta['name']}: {aposta['odd']}\n"
                if mercado['betting_type'] == "Corners Over/Under":
                    for aposta in mercado['bets']:
                        odds_msg += f"  🥅 {aposta['name']}: {aposta['odd']}\n"
            odds_msg += "\n"
    else:
        odds_msg += "❌ Nenhum jogo ao vivo encontrado.\n"

    return odds_msg

def odds_command(update, context):
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    mensagem = get_odds()
    bot.send_message(chat_id=CHAT_ID, text=mensagem, parse_mode=ParseMode.MARKDOWN)
