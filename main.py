#!/usr/bin/env python3
# main.py

import os
import re
import logging
import asyncio
from datetime import datetime, timedelta
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
    "leagues": []   # se vazio = todas as ligas
}
all_leagues = []  # iremos extrair da página principal
PAGE_SIZE   = 8

# ─── SELETORES (ajuste caso a página mude) ───────────────────────────
HOME_URL       = "https://www.sofascore.com/football"
MATCH_ROW      = "div.EventRow__Wrapper-sc-1yv5yf0-0"      # wrapper de cada partida
LEAGUE_SELECTOR= "div.EventRow__Tournament-sc-1yv5yf0-1"   # liga dentro do row
TIME_SELECTOR  = "div.EventRow__Time-sc-1yv5yf0-4"         # horário ou live
TEAMS_SELECTOR = "div.EventRow__TeamName-sc-1yv5yf0-7"     # nome dos times (vem dois)
SCORE_SELECTOR = "div.EventRow__Score-sc-1yv5yf0-5"        # placar (ou vazio)

EVENT_STATS    = "div.EventStatistics__Item-sc-1m27qvp-0"  # container estatísticas
STAT_LABEL     = "div.EventStatistics__Label-sc-1m27qvp-1" # rótulo (Corners, Possession)
STAT_VALUE     = "div.EventStatistics__Value-sc-1m27qvp-2" # valor

# ─── HELPERS DE SCRAPING ──────────────────────────────────────────────
def fetch_main_page():
    r = requests.get(HOME_URL, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def parse_all_leagues(soup):
    """Extrai todas as ligas disponíveis (lista de strings)."""
    ligas = []
    for row in soup.select(MATCH_ROW):
        liga = row.select_one(LEAGUE_SELECTOR)
        if liga:
            text = liga.get_text(strip=True)
            if text not in ligas:
                ligas.append(text)
    return ligas

def parse_matches(soup):
    """
    Devolve lista de dicts:
    {
      league, time_text, home, away, score, url
    }
    """
    jogos = []
    for row in soup.select(MATCH_ROW):
        liga_el = row.select_one(LEAGUE_SELECTOR)
        time_el = row.select_one(TIME_SELECTOR)
        teams   = row.select(TEAMS_SELECTOR)
        score_el= row.select_one(SCORE_SELECTOR)
        link_el = row.find("a", href=True)

        league    = liga_el.get_text(strip=True) if liga_el else "—"
        time_text = time_el.get_text(strip=True) if time_el else ""
        home      = teams[0].get_text(strip=True) if len(teams)>=1 else ""
        away      = teams[1].get_text(strip=True) if len(teams)>=2 else ""
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
    """Scrape corners e posse de bola de uma partida."""
    try:
        r = requests.get(event_url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        stats = {"Corners":(0,0), "Ball possession":(0,0)}
        items = soup.select(EVENT_STATS)
        for it in items:
            label = it.select_one(STAT_LABEL)
            vals  = it.select(STAT_VALUE)
            if label and vals and len(vals)>=2:
                key = label.get_text(strip=True)
                v1  = vals[0].get_text(strip=True).replace("%","")
                v2  = vals[1].get_text(strip=True).replace("%","")
                stats[key] = (int(v1), int(v2))
        return stats
    except Exception as e:
        logger.warning(f"Falha ao scrapear stats em {event_url}: {e}")
        return {"Corners":(0,0),"Ball possession":(0,0)}

# ─── HANDLERS DO TELEGRAM ──────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bot de Monitoramento via scraping* 👇\n"
        "/liga list   – Filtrar ligas\n"
        "/jogos       – Jogos ao vivo\n"
        "/proximos    – Próximos jogos (janela)\n"
        "/tendencias  – Tendências escanteios\n"
        "/odds        – Odds (não disponível)\n"
        "/config      – Ajustar config\n"
        "/ajuda       – Este menu",
        parse_mode="Markdown"
    )

async def ajuda(update, ctx):
    await start(update, ctx)

async def liga_cmd(update, ctx):
    soup = fetch_main_page()
    ligas = parse_all_leagues(soup)
    global all_leagues
    all_leagues = ligas  # sobrescreve o global
    # monta teclado página única (já que são poucas)
    kb = []
    for idx,lig in enumerate(ligas):
        sel = "✅ " if lig in config["leagues"] else ""
        kb.append([InlineKeyboardButton(f"{sel}{lig}", callback_data=f"liga_toggle:{idx}")])
    await update.message.reply_text(
        "🔍 *Filtrar ligas* (toque para selecionar/deselecionar):",
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
    await liga_cmd(update, ctx)  # redesenha o teclado

async def jogos(update, ctx):
    soup = fetch_main_page()
    jogos = parse_matches(soup)
    # filtra por ligas, se houver configuração
    if config["leagues"]:
        jogos = [j for j in jogos if j["league"] in config["leagues"]]
    if not jogos:
        return await update.message.reply_text("_Nenhum jogo ao vivo._", parse_mode="Markdown")

    msgs = []
    for j in jogos:
        stats = fetch_event_stats(j["url"]) if j["url"] else {}
        cor = sum(stats.get("Corners",(0,0)))
        pos = stats.get("Ball possession",(0,0))
        msgs.append(
            f"*{j['league']}*\n"
            f"{j['home']} x {j['away']}  → {j['score']}\n"
            f"🕒 {j['time']} (SP)\n"
            f"Esc: {cor} | Pos: {pos[0]}%–{pos[1]}%\n"
            + "—"*15
        )
    await update.message.reply_text("\n\n".join(msgs), parse_mode="Markdown")

async def proximos(update, ctx):
    janela = config["window_hours"]
    now = datetime.now(LOCAL_TZ)
    limite = now + timedelta(hours=janela)

    soup = fetch_main_page()
    jogos = parse_matches(soup)
    # extrai hora e filtra entre now e limite
    out=[]
    for j in jogos:
        m = re.search(r"(\d{2}):(\d{2})", j["time"])
        if not m: continue
        hh,mm = map(int, m.groups())
        dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now<=dt<=limite:
            out.append(f"🕒 {j['time']} – {j['home']} x {j['away']}")
    if not out:
        return await update.message.reply_text("_Nenhum próximo._", parse_mode="Markdown")
    await update.message.reply_text("\n".join(out), parse_mode="Markdown")

async def tendencias(update, ctx):
    soup = fetch_main_page()
    jogos = parse_matches(soup)
    if config["leagues"]:
        jogos = [j for j in jogos if j["league"] in config["leagues"]]
    out=[]
    for j in jogos:
        stats = fetch_event_stats(j["url"]) if j["url"] else {}
        cor = sum(stats.get("Corners",(0,0)))
        if cor>=4:  # só lista se muitos escanteios
            out.append(f"{j['home']} x {j['away']} ({cor} esc)")
    text = out and "\n".join(out) or "_Nenhum_"
    await update.message.reply_text(f"📊 *Tendências de escanteios:*\n{text}", parse_mode="Markdown")

async def odds_cmd(update, ctx):
    await update.message.reply_text("_Odds não estão disponíveis via scraping no SofaScore_", parse_mode="Markdown")

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
        config["window_hours"]=int(ctx.args[1])
        await update.message.reply_text(f"Janela atualizada para {ctx.args[1]}h")
    elif cmd=="auto" and len(ctx.args)>1 and ctx.args[1].lower() in ("on","off"):
        config["auto_enabled"] = ctx.args[1].lower()=="on"
        await update.message.reply_text(f"Auto envio {'ativado' if config['auto_enabled'] else 'desativado'}")
    else:
        await update.message.reply_text("Uso: `/config [janela <h> | auto on/off]`", parse_mode="Markdown")

# ─── BOOT & POLLING ────────────────────────────────────────────────
def main():
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(lambda app: app.bot.set_my_commands([
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

    app.add_handler(CommandHandler("start",    start))
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
