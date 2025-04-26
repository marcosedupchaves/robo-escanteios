import os
import requests
from datetime import datetime, timedelta, timezone

API_KEY = os.getenv("API_FOOTBALL_KEY")

def _build_message(agora, daqui3h, headers):
    # Busca torneios ao vivo e futuros
    resp_live = requests.get(
        "https://v3.football.api-sports.io/fixtures?live=all",
        headers=headers
    )
    live = resp_live.json().get("response", [])

    resp_prox = requests.get(
        f"https://v3.football.api-sports.io/fixtures?date={agora.date()}",
        headers=headers
    )
    prox = [
        j for j in resp_prox.json().get("response", [])
        if agora <= datetime.fromisoformat(j["fixture"]["date"][:-1]).replace(tzinfo=timezone.utc) <= daqui3h
    ]

    categorias = {
        "📺 Jogos Ao Vivo": live,
        "⏳ Jogos Próximos (até 3h)": prox
    }

    msg_lines = ["📊 *Odds de Gols e Escanteios:*\n"]
    for titulo, jogos in categorias.items():
        msg_lines.append(f"{titulo}:\n")
        if not jogos:
            msg_lines.append("_Nenhum jogo encontrado._\n\n")
            continue

        for j in jogos:
            fid   = j["fixture"]["id"]
            home  = j["teams"]["home"]["name"]
            away  = j["teams"]["away"]["name"]
            hora  = datetime.fromisoformat(j["fixture"]["date"][:-1])\
                       .strftime("%H:%M")
            msg_lines.append(f"🕒 {hora} - ⚽ {home} x {away}\n")

            odds_resp = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={fid}",
                headers=headers
            )
            odds_data = odds_resp.json().get("response", [])
            if not odds_data:
                msg_lines.append("  Sem odds disponíveis.\n\n")
                continue

            mercados = {}
            for b in odds_data[0].get("bookmakers", []):
                for bet in b.get("bets", []):
                    nome = bet["name"].lower()
                    if "goals" in nome:
                        mercados.setdefault("gols", bet["values"])
                    elif "corners" in nome:
                        mercados.setdefault("escanteios", bet["values"])

            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    msg_lines.append(f"  ⚽ Gols {v['value']}: {v['odd']}\n")
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    msg_lines.append(f"  🥅 Escanteios {v['value']}: {v['odd']}\n")
            msg_lines.append("\n")

    return "".join(msg_lines)

def get_odds():
    agora   = datetime.now(timezone.utc)
    daqui3h = agora + timedelta(hours=3)
    headers = {"x-apisports-key": API_KEY}
    return _build_message(agora, daqui3h, headers)
