import os
import logging
from datetime import datetime, timedelta, timezone
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

logging.basicConfig(
    format="%(asctime)s %(levelname)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Estado Dinâmico ─────────────────────────────────────────────────
config = {
    "window_hours": 3,
    "auto_enabled": True,
    "leagues": []    # IDs de ligas selecionadas; vazio = todas
}
all_leagues = []    # será preenchido no startup
PAGE_SIZE  = 8      # quantas ligas por página
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
    headers = {"x-apisports-key": API_KEY}
    return requests.get(url, headers=headers, params=params).json().get("response", [])

def format_games(jogos):
    if not jogos:
        return "_Nenhum jogo._\n"
    out = []
    for j in jogos:
        dt = parse_dt(j["fixture"]["date"])
        out.append(f"🕒 {dt.strftime('%H:%M')} – ⚽ "
                   f"{j['teams']['home']['name']} x {j['teams']['away']['name']}")
    return "\n".join(out) + "\n"

def load_leagues():
    global all_leagues
    now_year = datetime.now().year
    resp = requests.get(
        "https://v3.football.api-sports.io/leagues",
        headers={"x-apisports-key": API_KEY},
        params={"season": now_year}
    )
    arr = resp.json().get("response", [])
    # guardamos lista de tuplas (id, nome)
    all_leagues = [
        (e["league"]["id"], e["league"]["name"])
        for e in arr
    ]

def build_odds_message():
    agora    = datetime.now(timezone.utc)
    limite   = agora + timedelta(hours=config["window_hours"])
    ao_vivo  = fetch_fixtures(live=True)
    proximos = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]

    lines = ["📊 *Odds de Gols e Escanteios:*\n"]
    for title, jogos in [
        ("📺 Ao Vivo", ao_vivo),
        (f"⏳ Próximos ({config['window_hours']}h)", proximos),
    ]:
        lines.append(f"{title}:\n")
        if not jogos:
            lines.append("_Nenhum jogo disponível._\n\n")
            continue

        for j in jogos:
            home = j["teams"]["home"]["name"]
            away = j["teams"]["away"]["name"]
            fid  = j["fixture"]["id"]
            try:
                dt = parse_dt(j["fixture"]["date"])
                lines.append(f"🕒 {dt.strftime('%H:%M')} – ⚽ {home} x {away}\n")

                odds = requests.get(
                    f"https://v3.football.api-sports.io/odds?fixture={fid}",
                    headers={"x-apisports-key": API_KEY}
                ).json().get("response", [])
                if not odds:
                    lines.append("  Sem odds.\n\n")
                    continue

                mercados = {}
                for b in odds[0]["bookmakers"]:
                    for bet in b["bets"]:
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

            except Exception:
                logger.exception(f"Erro nas odds de {home} x {away}")
                lines.append(f"❌ Falha nas odds de {home} x {away}\n\n")

    return "".join(lines)

# ─── Menu de Ligas ───────────────────────────────────────────────────
def make_league_keyboard(page: int = 0):
    """
    Retorna InlineKeyboardMarkup com PAGE_SIZE ligas por página.
    """
    start = page * PAGE_SIZE
    end   = start + PAGE_SIZE
    chunk = all_leagues[start:end]
    buttons = []
    for lid, name in chunk:
        prefix = "✅ " if lid in config["leagues"] else ""
        text = f"{prefix}{name} [{lid}]"
        cb   = f"liga_toggle:{page}:{lid}"
        buttons.append([InlineKeyboardButton(text, callback_data=cb)])
    # navegação
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
        "👋 Bot de Odds ativo!\n"
        "/liga – Gerenciar filtro de ligas\n"
        "/jogos – Jogos ao vivo  /proximos – Próximos\n"
        "/tendencias /odds /config /ajuda"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def liga_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # manda página 0 do menu de ligas
    await update.message.reply_text(
        f"⚽ *Filtrar ligas* (página 1/{(len(all_leagues)-1)//PAGE_SIZE+1}):",
        reply_markup=make_league_keyboard(0),
        parse_mode="Markdown"
    )

async def liga_nav_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # navegação de página
    query = update.callback_query
    _, page = query.data.split(":")
    page = int(page)
    await query.edit_message_text(
        f"⚽ Filtrar ligas (página {page+1}/{(len(all_leagues)-1)//PAGE_SIZE+1}):",
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
    # re-renderiza mesma página
    page = int(page)
    await query.edit_message_reply_markup(reply_markup=make_league_keyboard(page))
    await query.answer(f"Filtro de ligas agora: {config['leagues'] or 'todas'}")

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📺 *Ao Vivo:*\n" + format_games(fetch_fixtures(live=True))
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agora  = datetime.now(timezone.utc)
    limite = agora + timedelta(hours=config["window_hours"])
    prox   = [
        j for j in fetch_fixtures(date=agora.date().isoformat())
        if agora <= parse_dt(j["fixture"]["date"]) <= limite
    ]
    text = f"⏳ *Próximos ({config['window_hours']}h):*\n" + format_games(prox)
    await context.bot.send_message(update.effective_chat.id, text, parse_mode="Markdown")

async def tendencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ao_vivo = fetch_fixtures(live=True)
    lista   = [f"{j['teams']['home']['name']} x {j['teams']['away']['name']}" for j in ao_vivo]
    text    = "📊 *Tendências Ao Vivo:*\n" + ("\n".join(lista) or "_Nenhum_\n")
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
        await update.message.reply_text(f"⚙️ Config atual:\n{status}", parse_mode="Markdown")
        return
    # mantém config de janela/auto como antes...

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    if not config["auto_enabled"]:
        return
    msg = build_odds_message()
    await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# ─── Main ─────────────────────────────────────────────────────────────
def main():
    load_leagues()  # busca e preenche all_leagues

    app = ApplicationBuilder().token(TOKEN).build()

    # comandos sugeridos
    app.bot.set_my_commands([
        BotCommand("start","Boas-vindas"),
        BotCommand("liga","Filtro de ligas"),
        BotCommand("jogos","Ao vivo"),
        BotCommand("proximos","Próximos"),
        BotCommand("tendencias","Tendências"),
        BotCommand("odds","Odds"),
        BotCommand("config","Config geral"),
        BotCommand("ajuda","Ajuda"),
    ])

    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("liga", liga_cmd))
    app.add_handler(CallbackQueryHandler(liga_nav_cb,   pattern=r"^liga_nav:"))
    app.add_handler(CallbackQueryHandler(liga_toggle_cb,pattern=r"^liga_toggle:"))
    app.add_handler(CommandHandler("jogos", jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias", tendencias))
    app.add_handler(CommandHandler("odds", odds_cmd))
    app.add_handler(CommandHandler("config", config_cmd))

    # job automático
    global auto_job
    auto_job = app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado com filtro de ligas!")
    app.run_polling()

if __name__ == "__main__":
    main()
