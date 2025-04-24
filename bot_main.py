import os
import requests
import telegram
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram.ext import Updater, CommandHandler

load_dotenv()

API_KEY = os.getenv('API_FOOTBALL_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

HEADERS = {'x-apisports-key': API_KEY}
BASE_URL = 'https://v3.football.api-sports.io'

def buscar_jogos_ao_vivo():
    try:
        url = f"{BASE_URL}/fixtures?live=all"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        return resp.json().get('response', [])
    except:
        return []

def buscar_media_escanteios(time_id, league_id, season):
    try:
        url = f"{BASE_URL}/teams/statistics?team={time_id}&season={season}&league={league_id}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        dados = resp.json().get('response', {})
        escanteios = dados.get('statistics', {}).get('corners', {}).get('total', {})
        return escanteios.get('total', 0) or 0
    except:
        return 0

def buscar_proximos_jogos():
    try:
        agora = datetime.utcnow()
        daqui_3h = agora + timedelta(hours=3)
        data_formatada = agora.strftime("%Y-%m-%d")
        url = f"{BASE_URL}/fixtures?date={data_formatada}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        jogos = resp.json().get('response', [])
        proximos = []
        for jogo in jogos:
            data_str = jogo['fixture']['date']
            data_jogo = datetime.strptime(data_str, "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
            if agora <= data_jogo <= daqui_3h:
                hora = data_jogo.strftime("%H:%M")
                liga = jogo['league']['name']
                home = jogo['teams']['home']['name']
                away = jogo['teams']['away']['name']
                proximos.append(f"🕒 {hora} | {liga}\n{home} x {away}\n")
        return proximos
    except:
        return []

def start(update, context):
    texto = (
        "👋 Olá! Eu sou o Robô de Monitoramento de Jogos ⚽\n\n"
        "Use os comandos abaixo para interagir comigo:\n"
        "/jogos - Ver jogos ao vivo\n"
        "/tendencias - Jogos com tendência de escanteios\n"
        "/proximos - Jogos que começam nas próximas 3h\n"
        "/ajuda - Ver instruções\n"
        "/config - Status do robô/API"
    )
    context.bot.send_message(chat_id=update.effective_chat.id, text=texto)

def ajuda(update, context):
    texto = (
        "ℹ️ *Comandos disponíveis:*\n\n"
        "/jogos - Jogos ao vivo agora\n"
        "/tendencias - Alta tendência de escanteios\n"
        "/proximos - Jogos que começam nas próximas 3 horas\n"
        "/start - Boas-vindas\n"
        "/ajuda - Ajuda\n"
        "/config - Status da API"
    )
    context.bot.send_message(chat_id=update.effective_chat.id, text=texto, parse_mode=telegram.ParseMode.MARKDOWN)

def jogos(update, context):
    jogos = buscar_jogos_ao_vivo()
    if not jogos:
        mensagem = "❌ Nenhum jogo ao vivo no momento."
    else:
        mensagem = "📺 *Jogos ao Vivo Agora:*\n"
        for jogo in jogos:
            tempo = jogo['fixture']['status']['elapsed']
            liga = jogo['league']['name']
            home = jogo['teams']['home']['name']
            away = jogo['teams']['away']['name']
            gols_home = jogo['goals']['home']
            gols_away = jogo['goals']['away']
            nome_jogo = f"{home} {gols_home} x {gols_away} {away}"
            mensagem += f"⏱️ {tempo}min | {liga}\n{nome_jogo}\n\n"
    context.bot.send_message(chat_id=update.effective_chat.id, text=mensagem, parse_mode=telegram.ParseMode.MARKDOWN)

def config(update, context):
    try:
        url = f"{BASE_URL}/status"
        r = requests.get(url, headers=HEADERS, timeout=10)
        status = r.json().get("response", {})
        texto = (
            f"✅ Robô funcionando!\n"
            f"🟢 API Status: {status.get('account', {}).get('subscription', {}).get('plan', 'Desconhecido')}\n"
            f"👥 Limite diário: {status.get('requests', {}).get('limit_day', '?')}\n"
            f"📊 Utilizado hoje: {status.get('requests', {}).get('current', '?')}"
        )
    except:
        texto = "❌ Não foi possível consultar o status da API."
    context.bot.send_message(chat_id=update.effective_chat.id, text=texto)

def tendencias(update, context):
    jogos = buscar_jogos_ao_vivo()
    destaque = []
    for jogo in jogos:
        tempo = jogo['fixture']['status']['elapsed']
        if tempo is None or tempo < 30:
            continue
        league_id = jogo['league']['id']
        season = jogo['league']['season']
        home = jogo['teams']['home']
        away = jogo['teams']['away']
        media_home = buscar_media_escanteios(home['id'], league_id, season)
        media_away = buscar_media_escanteios(away['id'], league_id, season)
        media_total = media_home + media_away
        if media_total >= 10:
            nome_jogo = f"{home['name']} x {away['name']}"
            destaque.append(f"🔥 {nome_jogo} - Média: {media_total} escanteios")

    if destaque:
        mensagem = "📊 *Jogos com alta tendência de escanteios:*\n" + "\n".join(destaque)
    else:
        mensagem = "❌ Nenhum jogo com alta tendência encontrado no momento."
    context.bot.send_message(chat_id=update.effective_chat.id, text=mensagem, parse_mode=telegram.ParseMode.MARKDOWN)

def proximos(update, context):
    lista = buscar_proximos_jogos()
    if lista:
        mensagem = "📅 *Jogos nas próximas 3 horas:*\n\n" + "\n".join(lista)
    else:
        mensagem = "❌ Nenhum jogo encontrado para as próximas 3 horas."
    context.bot.send_message(chat_id=update.effective_chat.id, text=mensagem, parse_mode=telegram.ParseMode.MARKDOWN)

# Início do bot
updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
dispatcher = updater.dispatcher
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("ajuda", ajuda))
dispatcher.add_handler(CommandHandler("jogos", jogos))
dispatcher.add_handler(CommandHandler("config", config))
dispatcher.add_handler(CommandHandler("tendencias", tendencias))
dispatcher.add_handler(CommandHandler("proximos", proximos))

updater.start_polling()
print("🤖 Bot ouvindo todos os comandos...")
updater.idle()
