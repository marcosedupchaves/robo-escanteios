import os
import requests
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import CallbackContext

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")

def get_odds():
    agora = datetime.utcnow()
    daqui_3h = agora + timedelta(hours=3)
    headers = {"x-apisports-key": API_FOOTBALL_KEY}

    # Buscar jogos ao vivo
    resp_live = requests.get("https://v3.football.api-sports.io/fixtures?live=all", headers=headers)
    jogos_ao_vivo = resp_live.json().get("response", [])

    # Buscar próximos jogos (dentro de 3h)
    resp_prox = requests.get(
        f"https://v3.football.api-sports.io/fixtures?date={agora.date()}",
        headers=headers
    )
    jogos_proximos = [
        j for j in resp_prox.json().get("response", [])
        if agora <= datetime.fromisoformat(j['fixture']['date'][:-1]) <= daqui_3h
    ]

    todos_jogos = jogos_ao_vivo + jogos_proximos
    odds_msg = "📊 *Odds de Gols e Escanteios:*\n\n"


    for jogo in todos_jogos:
        fixture_id = jogo["fixture"]["id"]
        times = f"{jogo['teams']['home']['name']} x {jogo['teams']['away']['name']}"

        # Buscar odds do jogo
        odds_resp = requests.get(f"https://v3.football.api-sports.io/odds?fixture={fixture_id}", headers=headers)
        odds_data = odds_resp.json().get("response", [])

        if not odds_data:
            continue

        mercados = {}
        for mercado in odds_data[0]["bookmakers"][0]["bets"]:
            nome = mercado["name"].lower()
            if "total goals" in nome or "goals" in nome:
                mercados["gols"] = mercado["values"]
            elif "corners" in nome:
                mercados["escanteios"] = mercado["values"]

        if not mercados:
            continue

        odds_msg += f"⚽ *{times}*\n"
"
        if "gols" in mercados:
            for v in mercados["gols"][:2]:
                odds_msg += f"  • Gols {v['value']}: {v['odd']}
"
        if "escanteios" in mercados:
            for v in mercados["escanteios"][:2]:
                odds_msg += f"  • Escanteios {v['value']}: {v['odd']}
"
        odds_msg += "
"

    if odds_msg.strip() == "📊 *Odds de Gols e Escanteios:*":
        odds_msg += "Sem odds disponíveis no momento."

    return odds_msg

def odds_command(update: Update, context: CallbackContext):
    msg = get_odds()
    update.message.reply_text(msg, parse_mode="Markdown")
