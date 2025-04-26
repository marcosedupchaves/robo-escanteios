import os
import re
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
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

# ─── CONFIGURAÇÃO & LOGGING ───────────────────────────────────────────
load_dotenv()
API_KEY       = os.getenv("API_FOOTBALL_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID       = int(os.getenv("CHAT_ID") or 0)
LOCAL_TZ      = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(
    format="%(asctime)s %(levelname)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── ESTADO ────────────────────────────────────────────────────────────
config = {
    "window_hours": 3,
    "auto_enabled": True,
    "leagues": []    # IDs de ligas; vazio = todas
}
all_leagues = []
PAGE_SIZE   = 8
auto_job    = None

# ─── HELPERS ───────────────────────────────────────────────────────────
def parse_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
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

def slugify(name: str) -> str:
    s = name.lower()
    for a,b in [("á","a"),("ã","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ç","c")]:
        s = s.replace(a,b)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return re.sub(r"\s+", "-", s).strip("-")

def scrape_sofascore_stats(home: str, away: str, event_id: int):
    """
    Extrai escanteios e posse de bola do SofaScore.
    """
    home_slug = slugify(home)
    away_slug = slugify(away)
    url = f"https://www.sofascore.com/{home_slug}-vs-{away_slug}/{event_id}/#statistics"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(resp.text, "html.parser")

    corners = (0, 0)
    poss    = (0, 0)

    # Escanteios
    el = soup.select_one("div:has(> span:contains('Corners'))")
    if el:
        nums = el.select("div[data-test='stat-value']")
        if len(nums) >= 2:
            corners = (int(nums[0].text), int(nums[1].text))

    # Posse de bola
    el = soup.select_one("div:has(> span:contains('Ball possession'))")
    if el:
        nums = el.select("div[data-test='stat-value']")
        if len(nums) >= 2:
            poss = (
                int(nums[0].text.replace("%","")),
                int(nums[1].text.replace("%",""))
            )

    return {"corners": corners, "possession": poss}

def load_leagues():
    now = datetime.now().year
    resp = requests.get(
        "https://v3.football.api-sports.io/leagues",
        headers={"x-apisports-key": API_KEY},
        params={"season": now},
        timeout=10
    ).json().get("response", [])
    global all_leagues
    all_leagues = [(e["league"]["id"], e["league"]["name"]) for e in resp]
    logger.info(f"Loaded leagues: {len(all_leagues)}")

def make_league_keyboard(page: int = 0):
    start = page * PAGE_SIZE
    chunk = all_leagues[start:start+PAGE_SIZE]
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
    if start+PAGE_SIZE < len(all_leagues):
        nav.append(InlineKeyboardButton("Próxima 👉", callback_data=f"liga_nav:{page+1}"))
    if nav:
        buttons.append(nav)
    return InlineKeyboardMarkup(buttons)

# ─── HANDLERS ──────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Comandos:\n"
        "/liga list   – Filtrar ligas\n"
        "/jogos       – Detalhes ao vivo\n"
        "/proximos    – Próximos\n"
        "/tendencias  – Tendências escanteios\n"
        "/odds        – Odds gols & escanteios\n"
        "/config      – Configurações\n"
        "/ajuda       – Este menu",
        parse_mode="Markdown"
    )

async def ajuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)

async def liga_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or ctx.args[0].lower() != "list":
        return await update.message.reply_text(
            "Use `/liga list` para abrir seleção de ligas.",
            parse_mode="Markdown"
        )
    total_pages = (len(all_leagues)-1)//PAGE_SIZE + 1
    await update.message.reply_text(
        f"⚽ Filtrar ligas (1/{total_pages}):",
        reply_markup=make_league_keyboard(0),
        parse_mode="Markdown"
    )

async def liga_nav_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _, page = update.callback_query.data.split(":")
    page = int(page)
    total_pages = (len(all_leagues)-1)//PAGE_SIZE + 1
    await update.callback_query.edit_message_text(
        f"⚽ Filtrar ligas ({page+1}/{total_pages}):",
        reply_markup=make_league_keyboard(page),
        parse_mode="Markdown"
    )
    await update.callback_query.answer()

async def liga_toggle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _, page, lid = update.callback_query.data.split(":")
    lid = int(lid)
    if lid in config["leagues"]:
        config["leagues"].remove(lid)
    else:
        config["leagues"].append(lid)
    await update.callback_query.edit_message_reply_markup(make_league_keyboard(int(page)))
    await update.callback_query.answer()

async def jogos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fixtures = fetch_fixtures(live=True)
    if not fixtures:
        return await update.message.reply_text("_Nenhum jogo ao vivo no momento._", parse_mode="Markdown")
    msgs = []
    for j in fixtures:
        fid    = j["fixture"]["id"]
        league = j["league"]["name"]
        home   = j["teams"]["home"]["name"]
        away   = j["teams"]["away"]["name"]
        score_h = j["goals"]["home"] or 0
        score_a = j["goals"]["away"] or 0
        # scrap SofaScore
        st = scrape_sofascore_stats(home, away, fid)
        cor_h, cor_a = st["corners"]
        pos_h, pos_a = st["possession"]
        dt = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        block = (
            f"*{league}*\n"
            f"{home} x {away}  → {score_h}–{score_a}\n"
            f"🕒 {dt.strftime('%H:%M')} (SP)\n"
            f"Escanteios: {cor_h+cor_a}  Posse: {pos_h}%–{pos_a}%\n"
            + "—"*20
        )
        msgs.append(block)
    await update.message.reply_text("\n\n".join(msgs), parse_mode="Markdown")

async def proximos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=config["window_hours"])
    dias   = {agora.date(), limite.date()}
    fixtures = []
    for d in dias:
        fixtures += fetch_fixtures(date=d.isoformat())
    próximos = [j for j in fixtures if agora <= parse_dt(j["fixture"]["date"]) <= limite]
    if not próximos:
        return await update.message.reply_text("_Nenhum jogo próximo._", parse_mode="Markdown")
    text = "\n".join(
        f"🕒 {parse_dt(j['fixture']['date']).astimezone(LOCAL_TZ).strftime('%H:%M')} – "
        f"{j['teams']['home']['name']} x {j['teams']['away']['name']}"
        for j in próximos
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def tendencias(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    vivo = fetch_fixtures(live=True)
    lista = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in vivo]
    text  = "📊 *Tendências Ao Vivo:*\n" + ( "\n".join(lista) or "_Nenhum_" )
    await update.message.reply_text(text, parse_mode="Markdown")

async def odds_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # (pode usar build_odds_message do exemplo anterior)
    await update.message.reply_text("_Implementar odds aqui_", parse_mode="Markdown")

async def config_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        txt = (
            f"Janela (h): {config['window_hours']}\n"
            f"Auto: {'on' if config['auto_enabled'] else 'off'}\n"
            f"Ligas: {config['leagues'] or 'todas'}"
        )
        return await update.message.reply_text(f"⚙️ Config atual:\n{txt}", parse_mode="Markdown")
    cmd = ctx.args[0].lower()
    if cmd=="janela" and len(ctx.args)>1 and ctx.args[1].isdigit():
        config["window_hours"]=int(ctx.args[1])
        await update.message.reply_text(f"Janela ajustada para {ctx.args[1]}h.")
    elif cmd=="auto" and len(ctx.args)>1 and ctx.args[1].lower() in ("on","off"):
        flag = ctx.args[1].lower()=="on"
        config["auto_enabled"]=flag
        await update.message.reply_text(f"Auto {'ativado' if flag else 'desativado'}.")
    else:
        await update.message.reply_text("Uso: /config [janela <h> | auto on/off]")

async def auto_odds(ctx: ContextTypes.DEFAULT_TYPE):
    if config["auto_enabled"]:
        # reutilize odds_cmd ou build_odds_message
        await ctx.bot.send_message(CHAT_ID, "_Enviando odds automáticas..._")

# ─── INICIALIZAÇÃO ────────────────────────────────────────────────────
def main():
    load_leagues()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

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

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("ajuda",   ajuda))
    app.add_handler(CommandHandler("liga",    liga_cmd))
    app.add_handler(CallbackQueryHandler(liga_nav_cb,    pattern="^liga_nav:"))
    app.add_handler(CallbackQueryHandler(liga_toggle_cb, pattern="^liga_toggle:"))
    app.add_handler(CommandHandler("jogos",   jogos))
    app.add_handler(CommandHandler("proximos",proximos))
    app.add_handler(CommandHandler("tendencias",tendencias))
    app.add_handler(CommandHandler("odds",    odds_cmd))
    app.add_handler(CommandHandler("config",  config_cmd))

    global auto_job
    auto_job = app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e ouvindo comandos...")
    app.run_polling()

if __name__ == "__main__":
    main()
