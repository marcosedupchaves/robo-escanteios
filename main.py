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

# define fuso horário do usuário
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

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
        return "_Nenhum jogo disponível._\n"
    out = []
    for j in jogos:
        dt_utc   = parse_dt(j["fixture"]["date"])
        dt_local = dt_utc.astimezone(LOCAL_TZ)
        out.append(f"🕒 {dt_local.strftime('%H:%M')} – ⚽ "
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
                dt_local = parse_dt(j["fixture"]["date"]).astimezone(LOCAL_TZ)
                lines.append(f"🕒 {dt_local.strftime('%H:%M')} – ⚽ {home} x {away}\n")

                odds = requests.get(
                    f"https://v3.football.api-sports.io/odds?fixture={fid}",
                    headers={"x-apisports-key": API_KEY}
                ).json().get("response", [])
                if not odds:
                    lines.append("  Sem odds disponíveis.\n\n")
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

            except Exception:
                logger.exception(f"Erro nas odds de {home} x {away}")
                lines.append(f"❌ Falha nas odds de {home} x {away}\n\n")

    return "".join(lines)

# ─── Menu de Ligas ───────────────────────────────────────────────────
def make_league_keyboard(page: int = 0):
    start = page * PAGE_SIZE
    end   = start + PAGE_SIZE
    chunk = all_leagues[start:end]
    buttons = []
    for lid, name in chunk:
        prefix = "✅ " if lid in config["leagues"] else ""
        text = f"{prefix}{name} [{lid}]"
        cb   = f"liga_toggle:{page}:{lid}"
        buttons.append([InlineKeyboardButton(text, callback_data=cb)])
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
        "⚽ /liga       – Gerenciar filtro de ligas\n"
        "📺 /jogos      – Mostrar jogos ao vivo\n"
        "⏳ /proximos   – Jogos que começam em até janela configurada\n"
        "📊 /tendencias – Tendências de escanteios ao vivo\n"
        "🎲 /odds       – Odds de gols e escanteios\n"
        "⚙️ /config     – Ver/ajustar configurações\n"
        "❓ /ajuda      – Este menu de ajuda",
        parse_mode="Markdown"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def liga_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"⚽ _Filtrar ligas_ (página 1/{(len(all_leagues)-1)//PAGE_SIZE+1}):",
        reply_markup=make_league_keyboard(0),
        parse_mode="Markdown"
    )

async def liga_nav_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, page = query.data.split(":")
    page = int(page)
    await query.edit_message_text(
        f"⚽ _Filtrar ligas_ (página {page+1}/{(len(all_leagues)-1)//PAGE_SIZE+1}):",
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
    await query.answer(f"Ligas agora: {config['leagues'] or 'todas'}")

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
    cmd = args[0].lower()
    if cmd in ("janela", "window") and len(args) > 1 and args[1].isdigit():
        h = int(args[1]); config["window_hours"] = h
        await update.message.reply_text(f"⏱️ Janela alterada para {h}h.")
    elif cmd == "auto" and len(args) > 1 and args[1].lower() in ("on", "off"):
        flag = args[1].lower() == "on"
        config["auto_enabled"] = flag
        if auto_job:
            auto_job.resume() if flag else auto_job.pause()
        await update.message.reply_text(f"🔔 Auto-enviar {'ativado' if flag else 'desativado'}.")
    else:
        await update.message.reply_text(
            "❌ Uso:\n"
            "/config\n"
            "/config janela <horas>\n"
            "/config auto on/off"
        )

async def auto_odds(context: ContextTypes.DEFAULT_TYPE):
    if not config["auto_enabled"]:
        return
    msg = build_odds_message()
    await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

# ─── Main ─────────────────────────────────────────────────────────────
def main():
    load_leagues()
    app = ApplicationBuilder().token(TOKEN).build()

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
