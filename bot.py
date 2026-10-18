import os
import time
import logging
from collections import defaultdict

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Set these as Railway Variables. Never paste API keys into this file.
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-super-vl:free").strip()

if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN environment variable.")
if not OPENROUTER_API_KEY:
    raise RuntimeError("Missing OPENROUTER_API_KEY environment variable.")

try:
    ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW else 0
except ValueError:
    raise RuntimeError("ADMIN_ID must be your numeric Telegram user ID.")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("telegram-ai-bot")

# In-memory only: disappears whenever the bot restarts.
# Each user's history expires after 5 minutes of inactivity.
sessions = {}
BOT_PERSONA_NAME = "Samar AI"


def is_private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == "private")


def is_admin(update: Update) -> bool:
    return bool(update.effective_user and ADMIN_ID and update.effective_user.id == ADMIN_ID)


def get_session(user_id: int) -> dict:
    now = time.time()
    session = sessions.get(user_id)
    if not session or now - session["last_seen"] > 300:
        session = {"history": [], "last_seen": now}
        sessions[user_id] = session
    session["last_seen"] = now
    return session


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return
    await update.effective_message.reply_text(
        f"🤖 {BOT_PERSONA_NAME} online!\n"
        "Apna question bhejo.\n\n"
        "Commands: /help, /clear, /myinfo, /status"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return
    await update.effective_message.reply_text(
        "🤖 Commands:\n"
        "/start - Bot start\n"
        "/help - Commands list\n"
        "/clear - Apni temporary chat memory clear karo\n"
        "/myinfo - Apni Telegram ID dekho\n"
        "/status - Bot status\n\n"
        "Chat history 5 minute inactivity ke baad clear hoti hai. "
        "History database mein save nahi hoti."
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return
    user_id = update.effective_user.id
    sessions.pop(user_id, None)
    await update.effective_message.reply_text("🧹 Temporary chat memory clear ho gayi.")


async def myinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return
    await update.effective_message.reply_text(
        f"Your Telegram user ID: {update.effective_user.id}"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return
    await update.effective_message.reply_text(
        f"✅ Bot online\nModel: {MODEL}\nMemory: RAM only, 5-minute inactivity expiry"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return
    if not is_admin(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    await update.effective_message.reply_text(
        f"🔐 Admin panel\nActive temporary sessions: {len(sessions)}\nModel: {MODEL}"
    )


async def setname_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global BOT_PERSONA_NAME
    if not is_private(update):
        return
    if not is_admin(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    new_name = " ".join(context.args).strip()
    if not new_name:
        await update.effective_message.reply_text("Usage: /setname New Name")
        return
    BOT_PERSONA_NAME = new_name[:40]
    await update.effective_message.reply_text(f"✅ Chat greeting name changed to: {BOT_PERSONA_NAME}")


async def ask_openrouter(messages: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://railway.app",
        "X-Title": "Samar Trader Family Telegram Bot",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 500,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("The AI provider returned no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return "AI ne empty response diya. Dobara try karo."


async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_private(update):
        return

    message = update.effective_message
    user_id = update.effective_user.id
    user_text = (message.text or "").strip()
    if not user_text:
        return

    session = get_session(user_id)
    session["history"].append({"role": "user", "content": user_text})
    # Keep only the last 10 messages to limit request size.
    history = session["history"][-10:]
    prompt = [
        {
            "role": "system",
            "content": (
                f"You are {BOT_PERSONA_NAME}, a helpful assistant for Samar Trader Family. "
                "Answer clearly and responsibly. Do not claim to provide guaranteed trading profits."
            ),
        },
        *history,
    ]

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        answer = await ask_openrouter(prompt)
        session["history"].append({"role": "assistant", "content": answer})
        session["history"] = session["history"][-10:]
        # Telegram messages have a 4096-character limit; split long answers safely.
        for i in range(0, len(answer), 4000):
            await message.reply_text(answer[i:i + 4000])
    except httpx.HTTPStatusError as exc:
        log.error("OpenRouter HTTP error: %s", exc.response.status_code)
        await message.reply_text(
            f"⚠️ AI API error ({exc.response.status_code}). Railway logs check karo."
        )
    except Exception:
        log.exception("Reply failed")
        await message.reply_text("⚠️ AI reply nahi aa paya. Railway logs check karo.")


async def cleanup_expired_sessions(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()
    expired = [
        user_id for user_id, session in sessions.items()
        if now - session["last_seen"] > 300
    ]
    for user_id in expired:
        sessions.pop(user_id, None)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("myinfo", myinfo_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("setname", setname_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))

    # Remove inactive sessions even if nobody sends a new message.
    app.job_queue.run_repeating(cleanup_expired_sessions, interval=60, first=60)

    log.info("Starting Telegram bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
