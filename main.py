#!/usr/bin/env python3
# main.py
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

# ─── CONFIGURAÇÃO & LOG ───────────────────────────────────────────────
load_dotenv()
API_KEY   = os.getenv("API_FOOTBALL_KEY")
TOKEN     = os.getenv("TELEGRAM_TOKEN")
CHAT_ID   = int(os.getenv("CHAT_ID", "0"))
LOCAL_TZ  = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s",
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── ESTADO GLOBAL ────────────────────────────────────────────────────
config = {
    "window_hours": 3,
    "auto_enabled": True,
    "leagues": []
}
all_leagues = []
PAGE_SIZE   = 8

# ─── HELPERS ───────────────────────────────────────────────────────────
def parse_dt(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
    url = "https://v3.football.api-sports.io/fixtures"
    params = {}
    if live is not None: params["live"] = "all"
    if date:             params["date"] = date
    if config["leagues"]:
        params["league"] = ",".join(map(str, config["leagues"]))
    resp = requests.get(
        url,
        headers={"x-apisports-key": API_KEY},
        params=params,
        timeout=10
    )
    data = resp.json().get("response", [])
    logger.info(f"fetch_fixtures(live={live}, date={date}) → {len(data)} itens")
    return data

def slugify(name: str) -> str:
    s = name.lower()
    for a,b in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ç","c")]:
        s = s.replace(a,b)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return re.sub(r"\s+", "-", s).strip("-")

def scrape_sofascore_stats(home: str, away: str, event_id: int):
    home_slug = slugify(home)
    away_slug = slugify(away)
    url = f"https://www.sofascore.com/{home_slug}-vs-{away_slug}/{event_id}/#statistics"
    r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
    soup = BeautifulSoup(r.text, "lxml")

    corners = (0,0)
    poss    = (0,0)
    el = soup.select_one("div:has(span:contains('Corners'))")
    if el:
        vals = el.select("div[data-test='stat-value']")
        if len(vals)>=2:
            corners = (int(vals[0].text), int(vals[1].text))
    el = soup.select_one("div:has(span:contains('Ball possession'))")
    if el:
        vals = el.select("div[data-test='stat-value']")
        if len(vals)>=2:
            poss = (int(vals[0].text.replace("%","")), int(vals[1].text.replace("%","")))
    return {"corners": corners, "possession": poss}

def load_leagues():
    year = datetime.now().year
    resp = requests.get(
        "https://v3.football.api-sports.io/leagues",
        headers={"x-apisports-key": API_KEY},
        params={"season": year},
        timeout=10
    ).json().get("response", [])
    global all_leagues
    all_leagues = [(e["league"]["id"], e["league"]["name"]) for e in resp]
    logger.info(f"Loaded leagues: {len(all_leagues)}")

def make_league_keyboard(page:int=0):
    start = page*PAGE_SIZE
    chunk = all_leagues[start:start+PAGE_SIZE]
    kb = []
    for lid,name in chunk:
        prefix = "✅ " if lid in config["leagues"] else ""
        kb.append([InlineKeyboardButton(
            f"{prefix}{name} [{lid}]", callback_data=f"liga_toggle:{page}:{lid}"
        )])
    nav = []
    if page>0:
        nav.append(InlineKeyboardButton("👈 Anterior",callback_data=f"liga_nav:{page-1}"))
    if start+PAGE_SIZE < len(all_leagues):
        nav.append(InlineKeyboardButton("Próxima 👉",callback_data=f"liga_nav:{page+1}"))
    if nav:
        kb.append(nav)
    return InlineKeyboardMarkup(kb)

# ─── HANDLERS ──────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Comandos:\n"
        "/liga list   – Filtrar ligas\n"
        "/jogos       – Estatísticas ao vivo\n"
        "/proximos    – Próximos jogos\n"
        "/tendencias  – Tendências escanteios\n"
        "/odds        – Odds gols & escanteios\n"
        "/config      – Configurações\n"
        "/ajuda       – Este menu",
        parse_mode="Markdown"
    )

async def ajuda(update, ctx):
    await start(update, ctx)

async def liga_cmd(update, ctx):
    if not ctx.args or ctx.args[0].lower()!="list":
        return await update.message.reply_text("Use `/liga list`.", parse_mode="Markdown")
    pages = (len(all_leagues)-1)//PAGE_SIZE+1
    await update.message.reply_text(
        f"🔍 Filtrar ligas (1/{pages}):",
        reply_markup=make_league_keyboard(0),
        parse_mode="Markdown"
    )

async def liga_nav_cb(update, ctx):
    _,pg = update.callback_query.data.split(":"); pg=int(pg)
    pages = (len(all_leagues)-1)//PAGE_SIZE+1
    await update.callback_query.edit_message_text(
        f"🔍 Filtrar ligas ({pg+1}/{pages}):",
        reply_markup=make_league_keyboard(pg),
        parse_mode="Markdown"
    )
    await update.callback_query.answer()

async def liga_toggle_cb(update, ctx):
    _,pg,lid = update.callback_query.data.split(":"); lid=int(lid)
    if lid in config["leagues"]:
        config["leagues"].remove(lid)
    else:
        config["leagues"].append(lid)
    await update.callback_query.edit_message_reply_markup(make_league_keyboard(int(pg)))
    await update.callback_query.answer(f"Ligas: {config['leagues'] or 'todas'}")

async def jogos(update, ctx):
    fixtures = fetch_fixtures(live=True)
    if not fixtures:
        return await update.message.reply_text("_Nenhum jogo ao vivo._", parse_mode="Markdown")
    out=[]
    for j in fixtures:
        fid    = j["fixture"]["id"]
        league = j["league"]["name"]
        home   = j["teams"]["home"]["name"]
        away   = j["teams"]["away"]["name"]
        sh     = j["goals"]["home"] or 0
        sa     = j["goals"]["away"] or 0
        st     = scrape_sofascore_stats(home, away, fid)
        cor_h,cor_a = st["corners"]
        pos_h,pos_a = st["possession"]
        dt = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        out.append(
            f"*{league}*\n"
            f"{home} x {away} → {sh}–{sa}\n"
            f"🕒 {dt.strftime('%H:%M')} (SP)\n"
            f"Esc: {cor_h+cor_a} | Pos: {pos_h}%–{pos_a}%\n"
            + "—"*15
        )
    await update.message.reply_text("\n\n".join(out), parse_mode="Markdown")

async def proximos(update, ctx):
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=config["window_hours"])
    dias   = {agora.date(), limite.date()}
    fx=[]
    for d in dias:
        fx += fetch_fixtures(date=d.isoformat())
    prox = [
        j for j in fx
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]
    if not prox:
        return await update.message.reply_text("_Nenhum próximo._", parse_mode="Markdown")
    txt = "\n".join(
        f"🕒 {parse_dt(j['fixture']['date']).astimezone(LOCAL_TZ).strftime('%H:%M')} – "
        f"{j['teams']['home']['name']} x {j['teams']['away']['name']}"
        for j in prox
    )
    await update.message.reply_text(txt, parse_mode="Markdown")

async def tendencias(update, ctx):
    vivo = fetch_fixtures(live=True)
    lst  = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in vivo]
    txt  = "📊 Tendências:\n" + ("\n".join(lst) or "_Nenhum_")
    await update.message.reply_text(txt, parse_mode="Markdown")

async def odds_cmd(update, ctx):
    await update.message.reply_text("_Odds a implementar…_", parse_mode="Markdown")

async def config_cmd(update, ctx):
    if not ctx.args:
        txt = (
            f"Janela: {config['window_hours']}h\n"
            f"Auto: {'on' if config['auto_enabled'] else 'off'}\n"
            f"Ligas: {config['leagues'] or 'todas'}"
        )
        return await update.message.reply_text(f"⚙️ Config:\n{txt}", parse_mode="Markdown")
    c = ctx.args[0].lower()
    if c=="janela" and len(ctx.args)>1 and ctx.args[1].isdigit():
        config["window_hours"] = int(ctx.args[1])
        await update.message.reply_text(f"Janela: {ctx.args[1]}h")
    elif c=="auto" and len(ctx.args)>1 and ctx.args[1].lower() in ("on","off"):
        flag = ctx.args[1].lower()=="on"
        config["auto_enabled"] = flag
        await update.message.reply_text(f"Auto {'ativado' if flag else 'desativado'}")
    else:
        await update.message.reply_text("Uso: /config [janela <h> | auto on/off]")

# ─── BOOT & POLLING ──────────────────────────────────────────────
def main():
    load_leagues()
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(lambda x: x.bot.set_my_commands([
            BotCommand("start","Iniciar"),
            BotCommand("ajuda","Ajuda"),
            BotCommand("liga","Filtrar ligas"),
            BotCommand("jogos","Ao vivo"),
            BotCommand("proximos","Próximos"),
            BotCommand("tendencias","Tendências"),
            BotCommand("odds","Odds"),
            BotCommand("config","Config"),
        ]))
        .build()
    )

    # registra handlers
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("ajuda",    ajuda))
    app.add_handler(CommandHandler("liga",     liga_cmd))
    app.add_handler(CallbackQueryHandler(liga_nav_cb,    pattern=r"^liga_nav:"))
    app.add_handler(CallbackQueryHandler(liga_toggle_cb, pattern=r"^liga_toggle:"))
    app.add_handler(CommandHandler("jogos",    jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias",tendencias))
    app.add_handler(CommandHandler("odds",     odds_cmd))
    app.add_handler(CommandHandler("config",   config_cmd))

    logger.info("🤖 Bot iniciado e polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
