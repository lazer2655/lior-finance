import os
import logging
from decimal import Decimal
from urllib.parse import quote

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("lior-finance")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SOLANA_RPC = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")

PAPER_BALANCE = Decimal("100")

MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔍 Scanner Solana", callback_data="scan")],
    [InlineKeyboardButton("📊 Analyser un token", callback_data="analyze")],
    [InlineKeyboardButton("🤖 Assistant IA", callback_data="ai")],
    [InlineKeyboardButton("💼 Portefeuille Devnet", callback_data="wallet")],
    [InlineKeyboardButton("🧪 Paper trading", callback_data="paper")]
])


async def get_json(url):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def start(update, context):
    await update.message.reply_text(
        "Bienvenue sur LIOR FINANCE 🚀\n\n"
        "Bot Solana : analyse, scanner, IA et trading simulé.\n"
        "Aucune transaction réelle n'est autorisée.",
        reply_markup=MENU
    )


async def scan(update, context):
    try:
        data = await get_json(
            "https://api.dexscreener.com/token-profiles/latest/v1"
        )

        tokens = [
            token for token in data
            if token.get("chainId") == "solana"
        ][:8]

        if not tokens:
            result = "Aucun token trouvé."
        else:
            result = "🔍 TOKENS SOLANA RÉCENTS\n\n"
            for token in tokens:
                address = token.get("tokenAddress", "")
                name = token.get("name") or token.get("description") or "Token"
                url = token.get("url", "")
                result += f"• {name}\n{address}\n{url}\n\n"

        await update.message.reply_text(result)

    except Exception as e:
        await update.message.reply_text(f"Erreur scanner : {e}")


async def analyze_token(address):
    url = (
        "https://api.dexscreener.com/latest/dex/tokens/"
        + quote(address, safe="")
    )

    data = await get_json(url)

    pairs = [
        p for p in data.get("pairs", [])
        if p.get("chainId") == "solana"
    ]

    if not pairs:
        return "Aucune paire Solana trouvée."

    pairs.sort(
        key=lambda p: float(
            (p.get("liquidity") or {}).get("usd") or 0
        ),
        reverse=True
    )

    p = pairs[0]
    base = p.get("baseToken", {})

    return (
        f"📊 {base.get('name', 'Token')}\n"
        f"Symbole : {base.get('symbol', '?')}\n"
        f"Prix : ${p.get('priceUsd', 'N/A')}\n"
        f"Liquidité : ${(p.get('liquidity') or {}).get('usd', 0):,.0f}\n"
        f"Volume 24h : ${(p.get('volume') or {}).get('h24', 0):,.0f}\n"
        f"Variation 24h : {(p.get('priceChange') or {}).get('h24', 0)}%\n"
        f"DEX : {p.get('dexId', 'N/A')}\n"
        f"{p.get('url', '')}\n\n"
        "⚠️ Analyse indicative, pas un conseil financier."
    )


async def analyze_command(update, context):
    if not context.args:
        context.user_data["waiting"] = "token"
        await update.message.reply_text(
            "Envoie l'adresse du token Solana."
        )
        return

    try:
        result = await analyze_token(context.args[0])
    except Exception as e:
        result = f"Erreur : {e}"

    await update.message.reply_text(result)


async def wallet(update, context):
    context.user_data["waiting"] = "wallet"
    await update.message.reply_text(
        "Envoie une adresse publique Solana. "
        "La vérification utilise Devnet en lecture seule."
    )


async def check_wallet(address):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address]
    }

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(SOLANA_RPC, json=payload)
        response.raise_for_status()
        data = response.json()

    if "error" in data:
        raise ValueError(data["error"])

    lamports = data["result"]["value"]
    return Decimal(lamports) / Decimal(1_000_000_000)


async def ai_answer(question):
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=(
            "Réponds en français. Tu es un assistant pédagogique "
            "spécialisé en crypto et Solana. Explique les risques "
            "et ne promets jamais de rendement. Question : "
            + question
        )
    )

    return response.output_text


async def handle_text(update, context):
    waiting = context.user_data.get("waiting")
    message = update.message.text.strip()

    if waiting == "token":
        context.user_data.pop("waiting", None)
        try:
            result = await analyze_token(message)
        except Exception as e:
            result = f"Erreur : {e}"

        await update.message.reply_text(result)

    elif waiting == "wallet":
        context.user_data.pop("waiting", None)
        try:
            balance = await check_wallet(message)
            result = f"Solde Devnet : {balance} SOL"
        except Exception as e:
            result = f"Erreur : {e}"

        await update.message.reply_text(result)

    elif waiting == "ai":
        context.user_data.pop("waiting", None)

        if not OPENAI_API_KEY:
            await update.message.reply_text(
                "Clé OpenAI non configurée."
            )
            return

        try:
            result = await ai_answer(message)
        except Exception as e:
            result = f"Erreur IA : {e}"

        await update.message.reply_text(result[:4000])

    else:
        await update.message.reply_text(
            "Utilise /start pour afficher le menu."
        )


async def buttons(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "scan":
        await query.edit_message_text("Utilise /scan pour lancer le scanner.")

    elif query.data == "analyze":
        context.user_data["waiting"] = "token"
        await query.edit_message_text("Envoie l'adresse du token.")

    elif query.data == "ai":
        context.user_data["waiting"] = "ai"
        await query.edit_message_text("Pose ta question à ChatGPT.")

    elif query.data == "wallet":
        context.user_data["waiting"] = "wallet"
        await query.edit_message_text("Envoie une adresse publique Solana.")

    elif query.data == "paper":
        await query.edit_message_text(
            f"🧪 Trading simulé\nSolde fictif : {PAPER_BALANCE} unités.\n"
            "Aucune transaction réelle."
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    print("LIOR FINANCE démarre...")
    app.run_webhook(
    listen="0.0.0.0",
    port=int(os.environ.get("PORT", "10000")),
    url_path=BOT_TOKEN,
    webhook_url=f"{os.environ['RENDER_EXTERNAL_URL']}/{BOT_TOKEN}"
)


if __name__ == "__main__":
    main()