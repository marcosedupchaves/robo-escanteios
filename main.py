#!/usr/bin/env python3
# main.py

import os
import logging
import requests
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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

# ─── CONFIG & LOGGING ────────────────────────────────────────────────
load_dotenv()
TOKEN    = os.getenv("TELEGRAM_TOKEN")
CHAT_ID  = int(os.getenv("CHAT_ID", "0"))
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(message)s")
logger = logging.getLogger(__name__)

# ─── ESTADO GLOBAL ────────────────────────────────────────────────────
config = {
    "window_hours": 3,
    "auto_enabled": False,
    "leagues": []
}
all_leagues = []

# ─── SELETORES (VOCÊ VAI SUBSTITUIR COM O `/debug`) ──────────────────
HOME_URL        = "https://www.sofascore.com/football"
MATCH_ROW       = "div.EventRow__Wrapper-sc-1yv5yf0-0"   # <== substitua aqui
LEAGUE_SELECTOR = "div.EventRow__Tournament-sc-1yv5yf0-1"
TIME_SELECTOR   = "div.EventRow__Time-sc-1yv5yf0-4"
TEAMS_SELECTOR  = "div.EventRow__TeamName-sc-1yv5yf0-7"
SCORE_SELECTOR  = "div.EventRow__Score-sc-1yv5yf0-5"

EVENT_STATS     = "div.EventStatistics__Item-sc-1m27qvp-0"
STAT_LABEL      = "div.EventStatistics__Label-sc-1m27qvp-1"
STAT_VALUE      = "div.EventStatistics__Value-sc-1m27qvp-2"

# ─── SCRAPING HELPERS ────────────────────────────────────────────────
def fetch_page():
    r = requests.get(HOME_URL, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def parse_all_leagues(soup):
    x = []
    for row in soup.select(MATCH_ROW):
        t = row.select_one(LEAGUE_SELECTOR)
        if t:
            name = t.get_text(strip=True)
            if name not in x:
                x.append(name)
    return x

def parse_matches(soup):
    jogos = []
    for row in soup.select(MATCH_ROW):
        league_el = row.select_one(LEAGUE_SELECTOR)
        time_el   = row.select_one(TIME_SELECTOR)
        teams     = row.select(TEAMS_SELECTOR)
        score_el  = row.select_one(SCORE_SELECTOR)
        link_el   = row.find("a", href=True)

        league    = league_el.get_text(strip=True) if league_el else "—"
        time_text = time_el.get_text(strip=True) if time_el else ""
        home      = teams[0].get_text(strip=True) if len(teams)>0 else ""
        away      = teams[1].get_text(strip=True) if len(teams)>1 else ""
        score     = score_el.get_text(strip=True) if score_el else ""
        url       = "https://www.sofascore.com" + link_el["href"] if link_el else None

        jogos.append({
            "league": league,
            "time":   time_text,
            "home":   home,
            "away":   away,
            "score":  score,
            "url":    url
        })
    return jogos

def fetch_event_stats(event_url):
    try:
        r = requests.get(event_url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        corners = (0,0)
        possession = (0,0)
        for it in soup.select(EVENT_STATS):
            lab = it.select_one(STAT_LABEL)
            vals= it.select(STAT_VALUE)
            if lab and len(vals)>=2:
                key = lab.get_text(strip=True)
                v1  = vals[0].get_text(strip=True).replace("%","")
                v2  = vals[1].get_text(strip=True).replace("%","")
                if key.lower().startswith("corn"):
                    corners = (int(v1), int(v2))
                if key.lower().startswith("ball"):
                    possession = (int(v1), int(v2))
        return {"Corners":corners, "Ball possession":possession}
    except Exception as e:
        logger.warning(f"stats fail {e}")
        return {"Corners":(0,0),"Ball possession":(0,0)}

# ─── TELEGRAM HANDLERS ───────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bot de Monitoramento via scraping* 👇\n"
        "/debug         – Mostrar HTML cru (ajuste _MATCH_ROW_)\n"
        "/liga list     – Filtrar ligas\n"
        "/jogos         – Jogos ao vivo\n"
        "/proximos      – Próximos jogos (janela)\n"
        "/tendencias    – Tendências escanteios\n"
        "/odds          – Odds (não disponível)\n"
        "/config        – Ajustar config\n"
        "/ajuda         – Este menu",
        parse_mode="Markdown"
    )

async def ajuda(update, ctx):
    await start(update, ctx)

async def debug(update, ctx):
    """Envia o HTML cru das primeiras linhas para você copiar o SELECTOR correto."""
    soup = fetch_page()
    rows = soup.select(MATCH_ROW)
    text = []
    for i,row in enumerate(rows[:4]):
        html_snip = row.prettify()[:500]
        text.append(f"Row #{i+1}:\n```html\n{html_snip}\n```")
    await update.message.reply_text("\n\n".join(text), parse_mode="Markdown")

async def liga_cmd(update, ctx):
    soup  = fetch_page()
    ligas = parse_all_leagues(soup)
    global all_leagues
    all_leagues = ligas
    kb = []
    for idx, lig in enumerate(ligas):
        sel = "✅ " if lig in config["leagues"] else ""
        kb.append([InlineKeyboardButton(f"{sel}{lig}", callback_data=f"liga_toggle:{idx}")])
    await update.message.reply_text(
        "🔍 *Filtrar ligas* (toque para selecionar):",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def liga_toggle_cb(update, ctx):
    idx = int(update.callback_query.data.split(":")[1])
    lig = all_leagues[idx]
    if lig in config["leagues"]:
        config["leagues"].remove(lig)
    else:
        config["leagues"].append(lig)
    await update.callback_query.answer(f"Ligas: {config['leagues'] or ['todas']}")
    await liga_cmd(update, ctx)

async def jogos(update, ctx):
    soup  = fetch_page()
    jogos = parse_matches(soup)
    if config["leagues"]:
        jogos = [j for j in jogos if j["league"] in config["leagues"]]
    if not jogos:
        return await update.message.reply_text("_Nenhum jogo ao vivo._", parse_mode="Markdown")

    msgs = []
    for j in jogos:
        stats = fetch_event_stats(j["url"]) if j["url"] else {}
        cor  = sum(stats["Corners"])
        pos  = stats["Ball possession"]
        msgs.append(
            f"*{j['league']}*\n"
            f"{j['home']} x {j['away']}  → {j['score']}\n"
            f"🕒 {j['time']} (SP)\n"
            f"Esc: {cor} | Pos: {pos[0]}%–{pos[1]}%\n"
            + "—"*12
        )
    await update.message.reply_text("\n\n".join(msgs), parse_mode="Markdown")

async def proximos(update, ctx):
    janela = config["window_hours"]
    now    = datetime.now(LOCAL_TZ)
    limite = now + timedelta(hours=janela)

    soup  = fetch_page()
    jogos = parse_matches(soup)
    out   = []
    for j in jogos:
        m = re.search(r"(\d{2}):(\d{2})", j["time"])
        if not m: continue
        hh,mm = map(int,m.groups())
        dt = now.replace(hour=hh, minute=mm)
        if now<=dt<=limite:
            out.append(f"🕒 {j['time']} – {j['home']} x {j['away']}")
    if not out:
        return await update.message.reply_text("_Nenhum próximo._", parse_mode="Markdown")
    await update.message.reply_text("\n".join(out), parse_mode="Markdown")

async def tendencias(update, ctx):
    soup  = fetch_page()
    jogos = parse_matches(soup)
    if config["leagues"]:
        jogos = [j for j in jogos if j["league"] in config["leagues"]]
    out = []
    for j in jogos:
        stats = fetch_event_stats(j["url"]) if j["url"] else {}
        cor = sum(stats["Corners"])
        if cor>=4:
            out.append(f"{j['home']} x {j['away']} ({cor} esc)")
    text = out and "\n".join(out) or "_Nenhum_"
    await update.message.reply_text(f"📊 *Tendências de escanteios:*\n{text}", parse_mode="Markdown")

async def odds_cmd(update, ctx):
    await update.message.reply_text("_Odds não disponíveis via scraping no SofaScore_", parse_mode="Markdown")

async def config_cmd(update, ctx):
    if not ctx.args:
        txt = (
            f"Janela: {config['window_hours']}h\n"
            f"Ligas: {config['leagues'] or ['todas']}\n"
            f"Auto envio: {'on' if config['auto_enabled'] else 'off'}"
        )
        return await update.message.reply_text(f"⚙️ Config:\n{txt}", parse_mode="Markdown")
    cmd = ctx.args[0].lower()
    if cmd=="janela" and len(ctx.args)>1 and ctx.args[1].isdigit():
        config["window_hours"] = int(ctx.args[1])
        await update.message.reply_text(f"Janela ajustada para {ctx.args[1]}h")
    elif cmd=="auto" and len(ctx.args)>1 and ctx.args[1].lower() in ("on","off"):
        config["auto_enabled"] = ctx.args[1].lower()=="on"
        await update.message.reply_text(f"Auto envio {'ativado' if config['auto_enabled'] else 'desativado'}")
    else:
        await update.message.reply_text("Uso: `/config [janela <h> | auto on/off]`", parse_mode="Markdown")

# ─── BOOT ──────────────────────────────────────────────────────────────
def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(lambda ap: ap.bot.set_my_commands([
            BotCommand("start","Iniciar"),
            BotCommand("debug","Debug HTML"),
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

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("debug",    debug))
    app.add_handler(CommandHandler("ajuda",    ajuda))
    app.add_handler(CommandHandler("liga",     liga_cmd))
    app.add_handler(CallbackQueryHandler(liga_toggle_cb, pattern=r"^liga_toggle:"))
    app.add_handler(CommandHandler("jogos",    jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias",tendencias))
    app.add_handler(CommandHandler("odds",     odds_cmd))
    app.add_handler(CommandHandler("config",   config_cmd))

    logger.info("🤖 Bot iniciado — polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
