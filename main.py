import os
import time
import requests
import telegram
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('API_FOOTBALL_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('CHAT_ID')

HEADERS = {'x-apisports-key': API_KEY}
BASE_URL = 'https://v3.football.api-sports.io'

bot = telegram.Bot(token=TELEGRAM_TOKEN)

def enviar_alerta(mensagem):
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensagem)

def buscar_jogos_ao_vivo():
    url = f"{BASE_URL}/fixtures?live=all"
    resp = requests.get(url, headers=HEADERS)
    return resp.json().get('response', [])

def buscar_media_escanteios(time_id, league_id=71, season=2023):
    url = f"{BASE_URL}/teams/statistics?team={time_id}&season={season}&league={league_id}"
    resp = requests.get(url, headers=HEADERS)
    dados = resp.json().get('response', {})
    escanteios = dados.get('statistics', {}).get('corners', {}).get('total', {})
    media_total = escanteios.get('total', 0) or 0
    media_1t = escanteios.get('first', 0) or 0
    return media_total, media_1t

def analisar_partidas():
    jogos = buscar_jogos_ao_vivo()
    for jogo in jogos:
        tempo = int(jogo['fixture']['status']['elapsed'] or 0)
        if tempo != 36 and tempo != 85:
            continue

        home = jogo['teams']['home']
        away = jogo['teams']['away']
        home_id = home['id']
        away_id = away['id']
        league_id = jogo['league']['id']
        season = jogo['league']['season']

        try:
            media_home_total, media_home_1t = buscar_media_escanteios(home_id, league_id, season)
            media_away_total, media_away_1t = buscar_media_escanteios(away_id, league_id, season)
        except:
            continue

        media_total_jogo = media_home_total + media_away_total
        media_1t_jogo = media_home_1t + media_away_1t

        if media_total_jogo >= 10 and media_1t_jogo >= 4:
            msg = (
                f"🔔 Alerta de Escanteios - {tempo}min\n"
                f"Jogo: {home['name']} x {away['name']}\n"
                f"Média total: {media_total_jogo:.1f} | 1ºT: {media_1t_jogo:.1f}"
            )
            enviar_alerta(msg)

while True:
    try:
        analisar_partidas()
    except Exception as e:
        print(f"Erro: {e}")
    time.sleep(60)
