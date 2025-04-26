import os
import logging
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
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

# ─── Config Dinâmica ─────────────────────────────────────────────────
config = {
    "window_hours": 3,
    "auto_enabled": True
}
auto_job = None

# ─── Helpers ─────────────────────────────────────────────────────────
def parse_dt(ts: str) -> datetime:
    """Converte ISO (Z ou +00:00) em datetime tz-aware."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

def fetch_fixtures(live: bool=None, date: str=None):
    url = "https://v3.football.api-sports.io/fixtures"
    params = {}
    if live is not None: params["live"] = "all"
    if date:           params["date"] = date
    headers = {"x-apisports-key": API_KEY}
    r = requests.get(url, headers=headers, params=params)
    return r.json().get("response", [])

def format_games(jogos):
    if not jogos:
        return "_Nenhum jogo encontrado._\n"
    out = []
    for j in jogos:
        dt = parse_dt(j["fixture"]["date"])
        out.append(f"🕒 {dt.strftime('%H:%M')} – ⚽ "
                   f"{j['teams']['home']['name']} x {j['teams']['away']['name']}")
    return "\n".join(out) + "\n"

def build_odds_message():
    """
    Monta texto de odds de gols e escanteios (ao vivo + próximos window_hours).
    Envolve tudo num try/except para não quebrar em caso de erro inesperado.
    """
    try:
        agora    = datetime.now(timezone.utc)
        limite   = agora + timedelta(hours=config["window_hours"])
        ao_vivo  = fetch_fixtures(live=True)
        proximos = [
            j for j in fetch_fixtures(date=agora.date().isoformat())
            if agora <= parse_dt(j["fixture"]["date"]) <= limite
        ]

        lines = ["📊 *Odds de Gols e Escanteios:*\n"]
        for title, jogos in [
            ("📺 Jogos Ao Vivo", ao_vivo),
            (f"⏳ Próximos ({config['window_hours']}h)", proximos),
        ]:
            lines.append(f"{title}:\n")
            if not jogos:
                lines.append("_Nenhum jogo encontrado._\n\n")
                continue

            for j in jogos:
                home = j["teams"]["home"]["name"]
                away = j["teams"]["away"]["name"]
                fid  = j["fixture"]["id"]
                try:
                    dt = parse_dt(j["fixture"]["date"])
                    lines.append(f"🕒 {dt.strftime('%H:%M')} – ⚽ {home} x {away}\n")

                    odds_resp = requests.get(
                        f"https://v3.football.api-sports.io/odds?fixture={fid}",
                        headers={"x-apisports-key": API_KEY}
                    )
                    odds_data = odds_resp.json().get("response", [])
                    if not odds_data:
                        lines.append("  Sem odds disponíveis.\n\n")
                        continue

                    mercados = {}
                    for book in odds_data[0].get("bookmakers", []):
                        for bet in book.get("bets", []):
                            nm = bet["name"].lower()
                            if "goals" in nm:
                                mercados.setdefault("gols", bet["values"])
                            if "corners" in nm:
                                mercados.setdefault("escanteios", bet["values"])

                    if "gols" in mercados:
                        for v in mercados["gols"][:2]:
                            lines.append(f"  ⚽ {v['value']}: {v['odd']}\n")
                    if "escanteios" in mercados:
                        for v in mercados["escanteios"][:2]:
                            lines.append(f"  🥅 {v['value']}: {v['odd']}\n")
                    lines.append("\n")

                except Exception:
                    logger.exception(f"Falha ao buscar odds para {home} x {away}")
                    lines.append(f"❌ Falha nas odds de {home} x {away}\n\n")

        return "".join(lines)

    except Exception:
        logger.exception("Erro geral em build_odds_message")
        return "❌ *Erro interno* ao montar dados de odds, tente novamente mais tarde."

# ─── Handlers Telegram ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Bot de Odds ativo!\n\n"
        "/jogos      – Jogos ao vivo\n"
        "/proximos   – Próximos (≦ janela)\n"
        "/tendencias – Tendências de escanteios\n"
        "/odds       – Odds de gols & escanteios\n"
        "/config     – Ver/ajustar configurações\n"
        "/ajuda      – Esta ajuda"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def jogos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📺 *Jogos Ao Vivo:*\n" + format_games(fetch_fixtures(live=True))
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
    logger.info("Received /odds")
    msg = build_odds_message()
    await context.bot.send_message(update.effective_chat.id, msg, parse_mode="Markdown")

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        status = (
            f"• Janela (h): {config['window_hours']}\n"
            f"• Auto-enviar: {'on' if config['auto_enabled'] else 'off'}"
        )
        await update.message.reply_text(f"⚙️ *Config atual:*\n{status}", parse_mode="Markdown")
        return

    cmd = args[0].lower()
    if cmd in ("janela","window") and len(args)>1 and args[1].isdigit():
        h = int(args[1])
        config["window_hours"] = h
        await update.message.reply_text(f"⏱️ Janela alterada para {h}h.")
    elif cmd=="auto" and len(args)>1 and args[1].lower() in ("on","off"):
        flag = args[1].lower()=="on"
        config["auto_enabled"] = flag
        if auto_job:
            auto_job.resume() if flag else auto_job.pause()
        await update.message.reply_text(
            f"🔔 Auto-enviar {'ativado' if flag else 'desativado'}."
        )
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
    try:
        msg = build_odds_message()
        await context.bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except Exception:
        logger.exception("Erro no envio automático")

# ─── Setup & Run ─────────────────────────────────────────────────────
def main():
    global auto_job
    app = ApplicationBuilder().token(TOKEN).build()

    app.bot.set_my_commands([
        BotCommand("start","Boas-vindas"),
        BotCommand("ajuda","Mostra ajuda"),
        BotCommand("jogos","Jogos ao vivo"),
        BotCommand("proximos","Próximos"),
        BotCommand("tendencias","Tendências escanteios"),
        BotCommand("odds","Odds de gols & escanteios"),
        BotCommand("config","Ver/ajustar config"),
    ])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("jogos", jogos))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("tendencias", tendencias))
    app.add_handler(CommandHandler("odds", odds_cmd))
    app.add_handler(CommandHandler("config", config_cmd))

    auto_job = app.job_queue.run_repeating(auto_odds, interval=600, first=5)

    logger.info("🤖 Bot iniciado e polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
