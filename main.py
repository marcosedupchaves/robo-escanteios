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

# ─── CONFIGURAÇÃO ────────────────────────────────────────────────────
load_dotenv()
API_KEY      = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID      = int(os.getenv("CHAT_ID") or 0)
LOCAL_TZ     = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(
    format="%(asctime)s %(levelname)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── ESTADO DINÂMICO ─────────────────────────────────────────────────
config = {
    "window_hours": 3,
    "auto_enabled": True,
    "leagues": []    # IDs de ligas selecionadas; vazio = todas
}
all_leagues = []    # será preenchido no startup
PAGE_SIZE   = 8     # ligas por página
auto_job    = None  # Job para envio automático

# ─── HELPERS ─────────────────────────────────────────────────────────
def parse_dt(ts: str) -> datetime:
    """Converte ISO timestamp (UTC) para datetime com timezone."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
    """Chama API-Football para buscar fixtures. live=True retorna ao vivo."""
    url = "https://v3.football.api-sports.io/fixtures"
    params = {}
    if live is not None:
        params["live"] = "all"
    if date:
        params["date"] = date
    if config["leagues"]:
        params["league"] = ",".join(map(str, config["leagues"]))
    resp = requests.get(
        url,
        headers={"x-apisports-key": API_KEY},
        params=params,
        timeout=10
    )
    data = resp.json().get("response", [])
    logger.info(f"fetch_fixtures(live={live}, date={date}) → {len(data)} items")
    return data

def parse_stat(stats, name):
    """
    Retorna (home, away) para estatística de nome `name`. 
    stats é a lista de item["type","statistics"] da API.
    """
    for item in stats:
        if item["type"].lower() == name.lower():
            vals = item["statistics"]
            home = vals[0].get("value") or 0
            away = vals[1].get("value") or 0
            return home, away
    return 0, 0

def load_leagues():
    """Carrega todas ligas da API para seleção de filtro."""
    now = datetime.now().year
    resp = requests.get(
        "https://v3.football.api-sports.io/leagues",
        headers={"x-apisports-key": API_KEY},
        params={"season": now},
        timeout=10
    ).json().get("response", [])
    global all_leagues
    all_leagues = [(e["league"]["id"], e["league"]["name"]) for e in resp]
    logger.info(f"Loaded {len(all_leagues)} leagues")

def format_games(jogos):
    """Formata lista de jogos simples: horário – home x away."""
    if not jogos:
        return "_Nenhum jogo disponível._"
    out = []
    for j in jogos:
        dt = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        out.append(f"🕒 {dt.strftime('%H:%M')} – ⚽ {home} x {away}")
    return "\n".join(out)

def build_jogos_detailed_message():
    """Monta mensagem detalhada para /jogos com estatísticas e odds."""
    vivo = fetch_fixtures(live=True)
    if not vivo:
        return "_Nenhum jogo ao vivo no momento._"
    lines = []
    for j in vivo:
        fid = j["fixture"]["id"]
        league = j["league"]["name"]
        stadium = j["fixture"]["venue"]["name"] or "Desconhecido"
        home = j["teams"]["home"]["name"]
        away = j["teams"]["away"]["name"]
        score_h = j["goals"]["home"] or 0
        score_a = j["goals"]["away"] or 0
        status = j["fixture"]["status"]["long"]
        elapsed = j["fixture"]["status"].get("elapsed") or 0
        time_str = f"{status} {elapsed}′"
        # estatísticas
        stats_resp = requests.get(
            f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fid}",
            headers={"x-apisports-key": API_KEY},
            timeout=10
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
        # odds 3-way
        odd_home = odd_draw = odd_away = None
        odds_resp = requests.get(
            f"https://v3.football.api-sports.io/odds?fixture={fid}",
            headers={"x-apisports-key": API_KEY},
            timeout=10
        ).json().get("response", [])
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
        # dica de aposta: menor odd
        tip = "-"
        candidates = [(odd_home, home), (odd_draw, "Empate"), (odd_away, away)]
        candidates = [(o,t) for o,t in candidates if o]
        if candidates:
            best = min(candidates, key=lambda x: float(x[0]))
            tip = f"{best[1]} ({best[0]})"
        # monta bloco
        dt_local = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        block = (
            f"*{league}*\n"
            f"Estádio: {stadium}\n"
            f"{home} x {away}  → {score_h}–{score_a}\n"
            f"Tempo: {time_str}  Hora (SP): {dt_local.strftime('%H:%M')}\n"
            f"Cartões: {cards}  Escanteios: {corners_h+corners_a}\n"
            f"Finalizações: {total_shots}  Chutes no Gol: {shots_on_h+shots_on_a}\n"
            f"Posse: {poss_h}%–{poss_a}%\n"
            f"Ataques: {att_h+att_a}  Perigosos: {dang_h+dang_a}\n"
            f"Odds: Casa {odd_home or '-'} | Empate {odd_draw or '-'} | Fora {odd_away or '-'}\n"
            f"Dica: {tip}\n"
            + "—" * 20 + "\n"
        )
        lines.append(block)
    return "".join(lines)

def build_odds_message():
    """Monta mensagem para /odds (ao vivo + próximos)."""
    agora   = datetime.now(timezone.utc)
    limite  = agora + timedelta(hours=config["window_hours"])
    ao_vivo = fetch_fixtures(live=True)
    proximos = []
    dias = {agora.date(), limite.date()}
    for d in dias:
        proximos += fetch_fixtures(date=d.isoformat())
    proximos = [
        j for j in proximos
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]

    lines = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [("📺 Ao Vivo", ao_vivo), (f"⏳ Próximos ({config['window_hours']}h)", proximos)]:
        lines.append(f"{title}:\n")
        if not jogos:
            lines.append("_Nenhum_\n\n"); continue
        for j in jogos:
            dt = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
            home = j["teams"]["home"]["name"]
            away = j["teams"]["away"]["name"]
            lines.append(f"🕒 {dt.strftime('%H:%M')} – {home} x {away}\n")
            odds_resp = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={j['fixture']['id']}",
                headers={"x-apisports-key": API_KEY},
                timeout=10
            ).json().get("response", [])
            if not odds_resp:
                lines.append("  Sem odds.\n\n"); continue
            mercados = {}
            for b in odds_resp[0].get("bookmakers", []):
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
    """Gera teclado inline para seleção de ligas."""
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

# ─── HANDLERS TELEGRAM ─────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bot de Monitoramento:\n\n"
        "/liga list   – Filtrar ligas\n"
        "/jogos       – Detalhes jogos ao vivo\n"
        "/proximos    – Próximos (janela)\n"
        "/tendencias  – Tendências escanteios\n"
        "/odds        – Odds gols & escanteios\n"
        "/config      – Ajustar configurações\n"
        "/ajuda       – Este menu",
        parse_mode="Markdown"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def liga_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or args[0].lower() != "list":
        return await update.message.reply_text("Use `/liga list` para abrir o menu.", parse_mode="Markdown")
    total_pages = (len(all_leagues) - 1) // PAGE_SIZE + 1
    await update.message.reply_text(
        f"⚽ _Filtrar ligas_ (página 1/{total_pages}):",
        reply_markup=make_league_keyboard(0),
        parse_mode="Markdown"
    )

async def liga_nav_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, page = update.callback_query.data.split(":")
    page = int(page)
    total_pages = (len(all_leagues) - 1) // PAGE_SIZE + 1
    await update.callback_query.edit_message_text(
        f"⚽ _Filtrar ligas_ (página {page+1}/{total_pages}):",
        reply_markup=make_league_keyboard(page),
        parse_mode="Markdown"
    )
    await update.callback_query.answer()

async def liga_toggle_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, page, lid = update.callback_query.data.split(":")
    lid = int(lid)
    if lid in config["leagues"]:
        config["leagues"].remove(lid)
    else:
        config["leagues"].append(lid)
    await update.callback_query.edit_message_reply_markup(make_league_keyboard(int(page)))
    await update.callback_query.answer(f"Ligas agora: {config['leagues'] or 'todas'}")

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_jogos_detailed_message()
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=config["window_hours"])
    dias   = {agora.date(), limite.date()}
    fixtures = []
    for d in dias:
        fixtures += fetch_fixtures(date=d.isoformat())
    proximos = [j for j in fixtures if agora <= parse_dt(j["fixture"]["date"]) <= limite]
    text = format_games(proximos)
    await update.message.reply_text(text or "_Nenhum jogo próximo._", parse_mode="Markdown")

async def tendencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ao_vivo = fetch_fixtures(live=True)
    lista   = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in ao_vivo]
    text    = "📊 *Tendências Ao Vivo:*\n" + ("\n".join(lista) or "_Nenhum_")
    await update.message.reply_text(text, parse_mode="Markdown")

async def odds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_odds_message()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        status = (
            f"Janela (h): {config['window_hours']}\n"
            f"Auto: {'on' if config['auto_enabled'] else 'off'}\n"
            f"Ligas: {config['leagues'] or 'todas'}"
        )
        return await update.message.reply_text(f"⚙️ Config atual:\n{status}", parse_mode="Markdown")
    cmd = args[0].lower()
    if cmd == "janela" and len(args) > 1 and args[1].isdigit():
        config["window_hours"] = int(args[1])
        await update.message.reply_text(f"⏱️ Janela ajustada para {args[1]}h.")
    elif cmd == "auto" and len(args) > 1 and args[1].lower() in ("on","off"):
        flag = args[1].lower() == "on"
        config["auto_enabled"] = flag
        if auto_job:
            auto_job.resume() if flag else auto_job.pause()
        await update.message.reply_text(f"🔔 Auto {'ativado' if flag else 'desativado'}.")
    else:
        await update.message.reply_text("❌ Uso: /config [janela <h> | auto on/off]")

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    if config["auto_enabled"]:
        msg = build_odds_message()
        await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# ─── MAIN ─────────────────────────────────────────────────────────────
def main():
    load_leagues()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # comandos bot
    app.bot.set_my_commands([
        BotCommand("start","Iniciar"),
        BotCommand("ajuda","Ajuda"),
        BotCommand("liga","Filtrar ligas"),
        BotCommand("jogos","Detalhes ao vivo"),
        BotCommand("proximos","Próximos"),
        BotCommand("tendencias","Tendências"),
        BotCommand("odds","Odds"),
        BotCommand("config","Configurações"),
    ])

    # handlers
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

    # job automático
    global auto_job
    auto_job = app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
