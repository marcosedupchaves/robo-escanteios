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
    MessageHandler,
    filters,
    ContextTypes,
)

# ─── CONFIGURAÇÃO & DEBUG ─────────────────────────────────────────────
load_dotenv()
API_KEY  = os.getenv("API_FOOTBALL_KEY")
TOKEN    = os.getenv("TELEGRAM_TOKEN")
CHAT_ID  = int(os.getenv("CHAT_ID"))
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

logging.basicConfig(
    format="%(asctime)s %(levelname)s: %(message)s",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# ─── ESTADO DINÂMICO ───────────────────────────────────────────────────
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
    if live is not None:    params["live"] = "all"
    if date:                params["date"] = date
    if config["leagues"]:
        params["league"] = ",".join(map(str, config["leagues"]))
    resp = requests.get(url, headers={"x-apisports-key": API_KEY}, params=params)
    return resp.json().get("response", [])

def load_leagues():
    now = datetime.now().year
    resp = requests.get(
        "https://v3.football.api-sports.io/leagues",
        headers={"x-apisports-key": API_KEY},
        params={"season": now}
    ).json().get("response", [])
    global all_leagues
    all_leagues = [(e["league"]["id"], e["league"]["name"]) for e in resp]

# ─── FORMATAÇÃO DE MENSAGENS ──────────────────────────────────────────
def format_games(jogos):
    if not jogos:
        return "_Nenhum jogo disponível._"
    out = []
    for j in jogos:
        dt_local = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        out.append(
            f"🕒 {dt_local.strftime('%H:%M')} – ⚽ "
            f"{j['teams']['home']['name']} x {j['teams']['away']['name']}"
        )
    return "\n".join(out)

def build_odds_message():
    agora   = datetime.now(timezone.utc)
    limite  = agora + timedelta(hours=config["window_hours"])
    ao_vivo = fetch_fixtures(live=True)
    prox    = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]

    lines = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [
        ("📺 Ao Vivo", ao_vivo),
        (f"⏳ Próximos ({config['window_hours']}h)", prox),
    ]:
        lines.append(f"{title}:\n")
        if not jogos:
            lines.append("_Nenhum_\n\n")
            continue
        for j in jogos:
            dt = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
            lines.append(
                f"🕒 {dt.strftime('%H:%M')} – "
                f"{j['teams']['home']['name']} x {j['teams']['away']['name']}\n"
            )
            odds = requests.get(
                f"https://v3.football.api-sports.io/odds?fixture={j['fixture']['id']}",
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
    kb = []
    for lid, name in chunk:
        prefix = "✅ " if lid in config["leagues"] else ""
        kb.append([InlineKeyboardButton(
            f"{prefix}{name} [{lid}]",
            callback_data=f"liga_toggle:{page}:{lid}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("👈 Anterior", callback_data=f"liga_nav:{page-1}"))
    if end < len(all_leagues):
        nav.append(InlineKeyboardButton("Próxima 👉", callback_data=f"liga_nav:{page+1}"))
    if nav:
        kb.append(nav)
    return InlineKeyboardMarkup(kb)

# ─── HANDLERS ────────────────────────────────────────────────────────
async def debug_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Apenas loga o texto recebido, não bloqueia outros handlers
    if update.message:
        logger.debug(f"DEBUG_ALL received: {update.message.text!r}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bot ativo.\n"
        "⚽ /liga list\n📺 /jogos\n⏳ /proximos\n📊 /tendencias\n🎲 /odds\n⚙️ /config\n❓ /ajuda",
        parse_mode="Markdown"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def liga_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or args[0].lower() != "list":
        return await update.message.reply_text("Use `/liga list`.", parse_mode="Markdown")
    total = (len(all_leagues) - 1) // PAGE_SIZE + 1
    await update.message.reply_text(
        f"⚽ _Filtrar ligas_ (página 1/{total}):",
        reply_markup=make_league_keyboard(0),
        parse_mode="Markdown"
    )

async def liga_nav_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, page = update.callback_query.data.split(":")
    page = int(page)
    total = (len(all_leagues) - 1) // PAGE_SIZE + 1
    await update.callback_query.edit_message_text(
        f"⚽ _Filtrar ligas_ (página {page+1}/{total}):",
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
    await update.callback_query.answer(f"Ligas: {config['leagues'] or 'todas'}")

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_games(fetch_fixtures(live=True))
    await update.message.reply_text(text or "_Nenhum jogo ao vivo._", parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=config["window_hours"])
    prox   = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]
    lines = ["⏳ *Próximos*:\n"]
    for j in prox:
        dt = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
        lines.append(f"🕒 {dt.strftime('%H:%M')} – {j['teams']['home']['name']} x {j['teams']['away']['name']}")
    await update.message.reply_text("\n".join(lines) or "_Nenhum_", parse_mode="Markdown")

async def tendencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ao_vivo = fetch_fixtures(live=True)
    lista = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in ao_vivo]
    await update.message.reply_text(
        "📊 *Tendências*\n" + ("\n".join(lista) or "_Nenhum_"),
        parse_mode="Markdown"
    )

async def odds_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = build_odds_message()
    await update.message.reply_text(msg, parse_mode="Markdown")

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        status = (
            f"Janela: {config['window_hours']}h\n"
            f"Auto: {'on' if config['auto_enabled'] else 'off'}\n"
            f"Ligas: {config['leagues'] or 'todas'}"
        )
        return await update.message.reply_text(f"⚙️ Config:\n{status}", parse_mode="Markdown")
    cmd = args[0].lower()
    if cmd == "janela" and len(args) > 1 and args[1].isdigit():
        config["window_hours"] = int(args[1])
        await update.message.reply_text(f"⏱️ Janela agora é {args[1]}h.")
    elif cmd == "auto" and len(args) > 1 and args[1].lower() in ("on", "off"):
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

# ─── INICIALIZAÇÃO ────────────────────────────────────────────────────
def main():
    load_leagues()
    app = ApplicationBuilder().token(TOKEN).build()

    # comandos Telegram
    app.bot.set_my_commands([
        BotCommand("start","Boas-vindas"),
        BotCommand("liga","Menu de ligas"),
        BotCommand("jogos","Ao vivo"),
        BotCommand("proximos","Próximos"),
        BotCommand("tendencias","Tendências"),
        BotCommand("odds","Odds"),
        BotCommand("config","Config"),
        BotCommand("ajuda","Ajuda"),
    ])

    # handlers de comandos (grupo 0)
    app.add_handler(CommandHandler("start", start),     group=0)
    app.add_handler(CommandHandler("ajuda", ajuda),     group=0)
    app.add_handler(CommandHandler("liga", liga_cmd),   group=0)
    app.add_handler(CallbackQueryHandler(liga_nav_cb,    pattern=r"^liga_nav:"),    group=0)
    app.add_handler(CallbackQueryHandler(liga_toggle_cb, pattern=r"^liga_toggle:"), group=0)
    app.add_handler(CommandHandler("jogos", jogos),     group=0)
    app.add_handler(CommandHandler("proximos", proximos), group=0)
    app.add_handler(CommandHandler("tendencias", tendencias), group=0)
    app.add_handler(CommandHandler("odds", odds_cmd),    group=0)
    app.add_handler(CommandHandler("config", config_cmd), group=0)

    # debug ALL (só no grupo 1, após comandos)
    app.add_handler(MessageHandler(filters.ALL, debug_all), group=1)

    # job automático de odds
    global auto_job
    auto_job = app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
