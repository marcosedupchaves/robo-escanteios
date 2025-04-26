import os
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv
from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ─── Configuração ────────────────────────────────────────────────────
load_dotenv()
API_KEY = os.getenv("API_FOOTBALL_KEY")
TOKEN   = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Estado Dinâmico ─────────────────────────────────────────────────
config = {
    "window_hours": 3,
    "auto_enabled": True,
    "leagues": []
}
all_leagues = []
PAGE_SIZE = 8
auto_job = None

# ─── Helpers ─────────────────────────────────────────────────────────
def parse_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
    url = "https://v3.football.api-sports.io/fixtures"
    params = {}
    if live is not None:    params["live"]   = "all"
    if date:                params["date"]   = date
    if config["leagues"]:
        params["league"] = ",".join(map(str, config["leagues"]))
    r = requests.get(url, headers={"x-apisports-key": API_KEY}, params=params)
    return r.json().get("response", [])

def parse_stat(stats, name):
    """Retorna (home, away) para estatística 'name'."""
    for item in stats:
        if item["type"].lower() == name.lower():
            home = item["statistics"][0].get("value") or 0
            away = item["statistics"][1].get("value") or 0
            # valor "%" vira string, mantemos assim
            return home, away
    return 0, 0

def load_leagues():
    global all_leagues
    now_year = datetime.now().year
    resp = requests.get(
        "https://v3.football.api-sports.io/leagues",
        headers={"x-apisports-key": API_KEY},
        params={"season": now_year}
    )
    arr = resp.json().get("response", [])
    all_leagues = [(e["league"]["id"], e["league"]["name"]) for e in arr]

# ─── Construtor de /jogos detalhado ──────────────────────────────────
def build_jogos_detailed_message():
    vivo = fetch_fixtures(live=True)
    if not vivo:
        return "_Nenhum jogo ao vivo no momento._"
    lines = []
    for j in vivo:
        fid = j["fixture"]["id"]
        # informações básicas
        league = j["league"]["name"]
        stadium = j["fixture"]["venue"]["name"] or "Desconhecido"
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        score_home = j["goals"]["home"] or 0
        score_away = j["goals"]["away"] or 0
        status = j["fixture"]["status"]["long"]
        elapsed = j["fixture"]["status"].get("elapsed") or 0
        time_str = f"{status} {elapsed}′"
        # estatísticas
        stats_resp = requests.get(
            f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fid}",
            headers={"x-apisports-key": API_KEY}
        ).json().get("response", [])
        stats = stats_resp[0]["statistics"] if stats_resp else []
        yellow_h, yellow_a = parse_stat(stats, "Yellow Cards")
        red_h, red_a = parse_stat(stats, "Red Cards")
        cards = yellow_h + yellow_a + red_h + red_a
        corners_h, corners_a = parse_stat(stats, "Corner Kicks")
        shots_on_h, shots_on_a = parse_stat(stats, "Shots on Goal")
        shots_off_h, shots_off_a = parse_stat(stats, "Shots off Goal")
        total_shots = shots_on_h + shots_on_a + shots_off_h + shots_off_a
        poss_h, poss_a = parse_stat(stats, "Ball Possession")
        # ataques
        att_h, att_a = parse_stat(stats, "Attacks")
        dang_h, dang_a = parse_stat(stats, "Dangerous Attacks")
        # odds 3-way
        odds_resp = requests.get(
            f"https://v3.football.api-sports.io/odds?fixture={fid}",
            headers={"x-apisports-key": API_KEY}
        ).json().get("response", [])
        odd_home = odd_draw = odd_away = None
        if odds_resp:
            for b in odds_resp[0].get("bookmakers", []):
                for bet in b.get("bets", []):
                    if "match winner" in bet["name"].lower():
                        for v in bet["values"]:
                            val = v["value"].lower()
                            if "home" in val:   odd_home = v["odd"]
                            if "draw" in val:   odd_draw = v["odd"]
                            if "away" in val:   odd_away = v["odd"]
                        break
                if odd_home is not None:
                    break
        # dica de aposta: menor odd
        tip = "—"
        ods = [(odd_home, home), (odd_draw, "Empate"), (odd_away, away)]
        ods = [(o,t) for o,t in ods if o]
        if ods:
            best = min(ods, key=lambda x: float(x[0]))
            tip = f"{best[1]} ({best[0]})"
        # monta bloco
        dt_local = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        block = (
            f"*{league}*\n"
            f"Estádio: {stadium}\n"
            f"Confronto: {home} x {away}\n"
            f"Placar: {score_home}–{score_away}\n"
            f"Cartões: {cards}  Escanteios: {corners_h+corners_a}\n"
            f"Finalizações: {total_shots}  Chutes ao Gol: {shots_on_h+shots_on_a}\n"
            f"Posse de Bola: {poss_h}%–{poss_a}%\n"
            f"Ataques: {att_h+att_a}  Perigosos: {dang_h+dang_a}\n"
            f"Hora (SP): {dt_local.strftime('%H:%M')}  Tempo: {time_str}\n"
            f"Odds: Casa {odd_home or '-'} | Empate {odd_draw or '-'} | Fora {odd_away or '-'}\n"
            f"Dica de aposta: {tip}\n"
            "—" * 20 + "\n"
        )
        lines.append(block)
    return "".join(lines)

# ─── Handlers Telegram ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bot de Odds ativo!\n\n"
        "⚽ /liga list   – Abrir menu de ligas\n"
        "📺 /jogos       – Detalhes dos jogos ao vivo\n"
        "⏳ /proximos    – Próximos (janela config)\n"
        "📊 /tendencias  – Tendências de escanteios\n"
        "🎲 /odds        – Odds de gols e escanteios\n"
        "⚙️ /config      – Ver/ajustar configurações\n"
        "❓ /ajuda       – Este menu de ajuda",
        parse_mode="Markdown"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /jogos")
    msg = build_jogos_detailed_message()
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

# ─── (mantém aqui os outros handlers: /liga, /proximos, /tendencias, /odds, /config ...) ───

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    if not config["auto_enabled"]:
        return
    msg = build_jogos_detailed_message()  # ou build_odds_message, conforme preferir
    await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

def main():
    load_leagues()
    app = ApplicationBuilder().token(TOKEN).build()

    app.bot.set_my_commands([
        BotCommand("start","Boas-vindas"),
        BotCommand("liga","Gerenciar ligas"),
        BotCommand("jogos","Detalhes ao vivo"),
        BotCommand("proximos","Próximos"),
        BotCommand("tendencias","Tendências"),
        BotCommand("odds","Odds"),
        BotCommand("config","Config geral"),
        BotCommand("ajuda","Ajuda"),
    ])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("jogos", jogos))
    # ... registre também os handlers de /liga, callbacks, /proximos, /tendencias, /odds, /config

    global auto_job
    auto_job = app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
