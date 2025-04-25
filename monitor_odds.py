import os
import requests
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import CallbackContext

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")

def get_odds():
    agora = datetime.now(timezone.utc)
    daqui_3h = agora + timedelta(hours=3)
    headers = {"x-apisports-key": API_FOOTBALL_KEY}

    # Buscar jogos ao vivo
    resp_live = requests.get("https://v3.football.api-sports.io/fixtures?live=all", headers=headers)
    jogos_ao_vivo = resp_live.json().get("response", [])

    # Buscar próximos jogos (até 3h)
    resp_prox = requests.get(f"https://v3.football.api-sports.io/fixtures?date={agora.date()}", headers=headers)
    jogos_proximos = []
    for j in resp_prox.json().get("response", []):
        jogo_data = datetime.strptime(j['fixture']['date'][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        if agora <= jogo_data <= daqui_3h:
            jogos_proximos.append(j)

    todos_jogos = {
        "ao_vivo": jogos_ao_vivo,
        "proximos": jogos_proximos
    }

    odds_msg = "📊 *Odds de Gols e Escanteios:*

"

    for categoria, jogos in todos_jogos.items():
        if categoria == "ao_vivo":
            odds_msg += "📺 *Jogos Ao Vivo:*
"
        else:
            odds_msg += "⏳ *Jogos Próximos (até 3h):*
"

        if not jogos:
            odds_msg += "_Nenhum jogo encontrado._

"
            continue

        for jogo in jogos:
            fixture_id = jogo["fixture"]["id"]
            times = f"{jogo['teams']['home']['name']} x {jogo['teams']['away']['name']}"
            horario = datetime.strptime(jogo['fixture']['date'][:19], "%Y-%m-%dT%H:%M:%S").strftime("%H:%M")

            odds_resp = requests.get(f"https://v3.football.api-sports.io/odds?fixture={fixture_id}", headers=headers)
            odds_data = odds_resp.json().get("response", [])

            if not odds_data:
                continue

            mercados = {}
            for bookmaker in odds_data[0]["bookmakers"]:
                for mercado in bookmaker["bets"]:
                    nome = mercado["name"].lower()
                    if "total goals" in nome or "goals" in nome:
                        if "gols" not in mercados:
                            mercados["gols"] = mercado["values"]
                    elif "corners" in nome:
                        if "escanteios" not in mercados:
                            mercados["escanteios"] = mercado["values"]

            if not mercados:
                continue

            odds_msg += f"🕒 {horario} - ⚽ *{times}*
"
            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    odds_msg += f"  ⚽ Gols {v['value']}: {v['odd']}
"
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    odds_msg += f"  🥅 Escanteios {v['value']}: {v['odd']}
"
            odds_msg += "\n"

    if odds_msg.strip() == "📊 *Odds de Gols e Escanteios:*

":
        odds_msg += "Sem odds disponíveis no momento."

    return odds_msg

def odds_command(update: Update, context: CallbackContext):
    msg = get_odds()
    update.message.reply_text(msg, parse_mode="Markdown")

