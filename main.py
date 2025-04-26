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
    "leagues": []    # IDs de ligas selecionadas; vazio = todas
}
all_leagues = []    # preenchido no startup
PAGE_SIZE  = 8      # ligas por página
auto_job   = None

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
    """Retorna tupla (home, away) para estatística específica."""
    for item in stats:
        if item["type"].lower() == name.lower():
            vals = item["statistics"]
            home = vals[0].get("value") or 0
            away = vals[1].get("value") or 0
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

# ─── Construtores de mensagem ────────────────────────────────────────
def build_jogos_detailed_message():
    vivo = fetch_fixtures(live=True)
    if not vivo:
        return "_Nenhum jogo ao vivo no momento._"
    lines = []
    for j in vivo:
        fid = j["fixture"]["id"]
        # Básico
        league = j["league"]["name"]
        stadium = j["fixture"]["venue"]["name"] or "Desconhecido"
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        score_home = j["goals"]["home"] or 0
        score_away = j["goals"]["away"] or 0
        status = j["fixture"]["status"]["long"]
        elapsed = j["fixture"]["status"].get("elapsed") or 0
        time_str = f"{status} {elapsed}′"
        # Estatísticas
        stats_resp = requests.get(
            f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fid}",
            headers={"x-apisports-key": API_KEY}
        ).json().get("response", [])
        stats = stats_resp[0]["statistics"] if stats_resp else []
        yellow_h, yellow_a = parse_stat(stats, "Yellow Cards")
        red_h, red_a       = parse_stat(stats, "Red Cards")
        cards = yellow_h + yellow_a + red_h + red_a
        corners_h, corners_a = parse_stat(stats, "Corner Kicks")
        shots_on_h, shots_on_a   = parse_stat(stats, "Shots on Goal")
        shots_off_h, shots_off_a = parse_stat(stats, "Shots off Goal")
        total_shots = shots_on_h + shots_on_a + shots_off_h + shots_off_a
        poss_h, poss_a = parse_stat(stats, "Ball Possession")
        att_h, att_a   = parse_stat(stats, "Attacks")
        dang_h, dang_a = parse_stat(stats, "Dangerous Attacks")
        # Odds 3-way
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
                            if "home" in val: odd_home = v["odd"]
                            if "draw" in val: odd_draw = v["odd"]
                            if "away" in val: odd_away = v["odd"]
                        break
                if odd_home is not None:
                    break
        # Dica: menor odd
        tip = "-"
        ods = [(odd_home, home), (odd_draw, "Empate"), (odd_away, away)]
        ods = [(o, t) for o, t in ods if o]
        if ods:
            best = min(ods, key=lambda x: float(x[0]))
            tip = f"{best[1]} ({best[0]})"
        # Horário local
        dt_local = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        block = (
            f"*{league}*\n"
            f"Estádio: {stadium}\n"
            f"{home} x {away}  → {score_home}–{score_away}\n"
            f"Tempo: {time_str}  Hora (SP): {dt_local.strftime('%H:%M')}\n"
            f"Cartões: {cards}  Escanteios: {corners_h+corners_a}\n"
            f"Finalizações: {total_shots}  Chutes no Gol: {shots_on_h+shots_on_a}\n"
            f"Poss. Bola: {poss_h}%–{poss_a}%\n"
            f"Ataques: {att_h+att_a}  Perigosos: {dang_h+dang_a}\n"
            f"Odds: Casa {odd_home or '-'} | Empate {odd_draw or '-'} | Fora {odd_away or '-'}\n"
            f"Dica: {tip}\n"
            + "—" * 20 + "\n"
        )
        lines.append(block)
    return "".join(lines)

def build_odds_message():
    agora    = datetime.now(timezone.utc)
    limite   = agora + timedelta(hours=config["window_hours"])
    ao_vivo  = fetch_fixtures(live=True)
    proximos = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]
    lines = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [("📺 Ao Vivo", ao_vivo), (f"⏳ Próximos ({config['window_hours']}h)", proximos)]:
        lines.append(f"{title}:\n")
        if not jogos:
            lines.append("_Nenhum jogo previsto._\n\n")
            continue
        for j in jogos:
            home = j["teams"]["home"]["name"]
            away = j["teams"]["away"]["name"]
            dt_local = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
            lines.append(f"🕒 {dt_local.strftime('%H:%M')} – {home} x {away}\n")
            fid = j["fixture"]["id"]
            odds = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={fid}",
                headers={"x-apisports-key": API_KEY}
            ).json().get("response", [])
            if not odds:
                lines.append("  Sem odds.\n\n")
                continue
            mercados = {}
            for b in odds[0].get("bookmakers", []):
                for bet in b.get("bets", []):
                    n = bet["name"].lower()
                    if "goals" in n:
                        mercados.setdefault("gols", bet["values"])
                    if "corners" in n:
                        mercados.setdefault("escanteios", bet["values"])
            if "gols" in mercados:
                for v in mercados["gols"][:2]:
                    lines.append(f"  ⚽ {v['value']}: {v['odd']}\n")
            if "escanteios" in mercados:
                for v in mercados["escanteios"][:2]:
                    lines.append(f"  🥅 {v['value']}: {v['odd']}\n")
            lines.append("\n")
    return "".join(lines)

def make_league_keyboard(page: int = 0):
    start = page * PAGE_SIZE
    end   = start + PAGE_SIZE
    chunk = all_leagues[start:end]
    buttons = []
    for lid, name in chunk:
        prefix = "✅ " if lid in config["leagues"] else ""
        buttons.append([InlineKeyboardButton(
            f"{prefix}{name} [{lid}]",
            callback_data=f"liga_toggle:{page}:{lid}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("👈 Anterior", callback_data=f"liga_nav:{page-1}"))
    if end < len(all_leagues):
        nav.append(InlineKeyboardButton("Próxima 👉", callback_data=f"liga_nav:{page+1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(buttons)

# ─── Handlers Telegram ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bot de Odds ativo!\n\n"
        "⚽ /liga list   – Menu de ligas\n"
        "📺 /jogos       – Detalhes dos jogos ao vivo\n"
        "⏳ /proximos    – Próximos jogos\n"
        "📊 /tendencias  – Tendências escanteios\n"
        "🎲 /odds        – Odds gols & escanteios\n"
        "⚙️ /config      – Configurações\n"
        "❓ /ajuda       – Este menu",
        parse_mode="Markdown"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def liga_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or args[0].lower() != "list":
        await update.message.reply_text("Use `/liga list` para abrir o menu de ligas.", parse_mode="Markdown")
        return
    total_pages = (len(all_leagues)-1)//PAGE_SIZE + 1
    await update.message.reply_text(
        f"⚽ _Filtrar ligas_ (página 1/{total_pages}):",
        reply_markup=make_league_keyboard(0),
        parse_mode="Markdown"
    )

async def liga_nav_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, page = query.data.split(":")
    page = int(page)
    total_pages = (len(all_leagues)-1)//PAGE_SIZE + 1
    await query.edit_message_text(
        f"⚽ _Filtrar ligas_ (página {page+1}/{total_pages}):",
        reply_markup=make_league_keyboard(page),
        parse_mode="Markdown"
    )
    await query.answer()

async def liga_toggle_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, page, lid = query.data.split(":")
    lid = int(lid)
    if lid in config["leagues"]:
        config["leagues"].remove(lid)
    else:
        config["leagues"].append(lid)
    await query.edit_message_reply_markup(reply_markup=make_league_keyboard(int(page)))
    await query.answer(f"Ligas: {config['leagues'] or 'todas'}")

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_jogos_detailed_message()
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=config["window_hours"])
    prox   = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]
    text = f"⏳ *Próximos ({config['window_hours']}h):*\n"
    text += "\n".join(
        f"🕒 {parse_dt(j['fixture']['date']).astimezone(LOCAL_TZ).strftime('%H:%M')} – "
        f"{j['teams']['home']['name']} x {j['teams']['away']['name']}"
        for j in prox
    ) or "_Nenhum._"
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def tendencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ao_vivo = fetch_fixtures(live=True)
    lista   = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in ao_vivo]
    text    = "📊 *Tendências Ao Vivo:*\n" + ("\n".join(lista) or "_Nenhum._")
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def odds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_odds_message()
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        status = (
            f"• Janela (h): {config['window_hours']}\n"
            f"• Auto: {'on' if config['auto_enabled'] else 'off'}\n"
            f"• Ligas: {config['leagues'] or 'todas'}"
        )
        await update.message.reply_text(f"⚙️ Config:\n{status}", parse_mode="Markdown")
        return
    cmd = args[0].lower()
    if cmd in ("janela", "window") and len(args)>1 and args[1].isdigit():
        config["window_hours"] = int(args[1])
        await update.message.reply_text(f"⏱️ Janela: {args[1]}h")
    elif cmd=="auto" and len(args)>1 and args[1].lower() in ("on","off"):
        flag = args[1].lower()=="on"
        config["auto_enabled"] = flag
        if auto_job: auto_job.resume() if flag else auto_job.pause()
        await update.message.reply_text(f"🔔 Auto {'ativado' if flag else 'desativado'}")
    else:
        await update.message.reply_text("❌ Uso: /config [janela <h>|auto on/off]")

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    if config["auto_enabled"]:
        msg = build_jogos_detailed_message()
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
        BotCommand("config","Config"),
        BotCommand("ajuda","Ajuda"),
    ])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("liga", liga_cmd))
    app.add_handler(CallbackQueryHandler(liga_nav_cb,    pattern=r"^liga_nav:"))
    app.add_handler(CallbackQueryHandler(liga_toggle_cb, pattern=r"^liga_toggle:"))
    app.add_handler(CommandHandler("jogos", jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias", tendencias))
    app.add_handler(CommandHandler("odds", odds_cmd))
    app.add_handler(CommandHandler("config", config_cmd))

    global auto_job
    auto_job = app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
