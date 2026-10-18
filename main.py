import os
import time
import logging
import sys
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configure global parameters
MODEL = "nvidia/nemotron-3.5-super-vl:free"
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))  # Telegram User ID allowed to use /admin
MAX_HISTORY = 10  # Maximum messages to keep in history per user
INACTIVITY_LIMIT = 300  # 5 minutes in seconds

# API credentials from environment variables
BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_KEY = os.environ["OPENROUTER_KEY"]

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger("SamarTraderBot")

# RAM Storage Structure
user_sessions = {}

def clean_expired_session(user_id: int):
    session = user_sessions.get(user_id)
    if session:
        elapsed = time.time() - session.get("last_activity", time.time())
        if elapsed > INACTIVITY_LIMIT:
            user_sessions[user_id] = {
                "history": [],
                "name": session.get("name"),
                "last_activity": time.time()
            }
            logger.info(f"Session for user {user_id} automatically cleared due to 5-minute inactivity.")

def get_user_session(user_id: int) -> dict:
    clean_expired_session(user_id)
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "history": [],
            "name": None,
            "last_activity": time.time()
        }
    else:
        user_sessions[user_id]["last_activity"] = time.time()
    return user_sessions[user_id]

# Private chat verification decorator
def private_chat_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_chat or update.effective_chat.type in ["group", "supergroup"]:
            try:
                await update.message.reply_text(
                    "❌ I can only assist you in private messages. Please click on my profile and send a direct message!"
                )
            except Exception:
                pass
            return
        return await func(update, context)
    return wrapper

@private_chat_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_user_session(user_id)
    display_name = session["name"] if session["name"] else update.effective_user.first_name

    welcome_msg = (
        f"Hello {display_name}! Welcome to **Samar Trader Family AI Support** 📊🤖\n\n"
        "I am your dedicated professional assistant. I can help with:\n"
        "• MT5 errors & account connection issues\n"
        "• Prop-firm evaluation rules & troubleshooting\n"
        "• Trading platform guidance\n"
        "• General trading education\n\n"
        "Type /help to see all available commands!"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

@private_chat_only
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_msg = (
        "🤖 **Samar Trader Family Support - Commands Guide**\n\n"
        "/start - Restart the bot and receive a welcome message\n"
        "/help - Display this commands list\n"
        "/clear - Instantly wipe your temporary conversation memory\n"
        "/setname <name> - Set a temporary custom display name\n"
        "/myinfo - Show your current session status and preferences\n"
        "/status - Show system and API connectivity status\n"
        "/admin - View admin control features (Restricted)"
    )
    await update.message.reply_text(help_msg, parse_mode="Markdown")

@private_chat_only
async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_sessions:
        user_sessions[user_id]["history"] = []
        user_sessions[user_id]["last_activity"] = time.time()
    await update.message.reply_text("🧹 Your local conversation memory has been cleared successfully!")

@private_chat_only
async def setname_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_user_session(user_id)
    new_name = " ".join(context.args).strip()

    if not new_name:
        await update.message.reply_text("❌ Please specify a name. Example: `/setname John`", parse_mode="Markdown")
        return

    session["name"] = new_name
    session["last_activity"] = time.time()
    await update.message.reply_text(f"✅ Your preferred name has been set to: *{new_name}*", parse_mode="Markdown")

@private_chat_only
async def myinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = get_user_session(user_id)
    pref_name = session.get("name") or "Not configured"
    history_len = len(session.get("history", []))

    info_msg = (
        f"📝 **Your Session Details (RAM)**\n\n"
        f"• **Telegram User ID**: `{user_id}`\n"
        f"• **Preferred Name**: {pref_name}\n"
        f"• **Stored Messages**: {history_len}/{MAX_HISTORY}\n\n"
        f"_Note: This data is stored entirely in temporary RAM and resets whenever the bot hosting server is restarted._"
    )
    await update.message.reply_text(info_msg, parse_mode="Markdown")

@private_chat_only
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 **System Status**: Online\n⚡ **AI Gateway Connection**: Active", parse_mode="Markdown")

@private_chat_only
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Error: Access denied. This command is restricted to administrators.")
        return

    active_users = len(user_sessions)
    await update.message.reply_text(
        f"👑 **Administrator Panel**\n\n• Active sessions in memory: `{active_users}`\n• AI Gateway Model: `{MODEL}`",
        parse_mode="Markdown"
    )

@private_chat_only
async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_message = update.message.text

    session = get_user_session(user_id)
    pref_name = session["name"] if session["name"] else update.effective_user.first_name
    history = session["history"]

    system_prompt = (
        "You are 'Samar Trader Family AI Support', a professional and friendly support assistant for the Samar Trader Family community. "
        f"The user you are speaking to prefers to be addressed as '{pref_name}'. "
        "Always respond politely, professionally, clearly, and concisely. Keep answers simple. "
        "Speak in whatever language the user talks to you (Hindi, Hinglish, or English). "
        "Assist them with trading-platform troubleshooting, prop-firm rules, account issues, MT5 errors, and general trading education. "
        "Crucial Rules:\n"
        "1. Never guarantee profits, guaranteed payouts, or specific trading results.\n"
        "2. Never invent company rules, policies, or specific account credentials.\n"
        "3. Do not reveal system configurations, API keys, internal credentials, or security filters."
    )

    history.append({"role": "user", "content": user_message})
    if len(history) > MAX_HISTORY:
        history.pop(0)

    payload_messages = [{"role": "system", "content": system_prompt}] + history

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL,
                "messages": payload_messages,
                "max_tokens": 350
            },
            timeout=30
        )

        if response.status_code == 200:
            res_data = response.json()
            choices = res_data.get("choices", [])
            ai_reply = ""
            if choices:
                ai_reply = choices[0].get("message", {}).get("content", "")
                if not ai_reply:
                    reasoning_list = choices[0].get("message", {}).get("reasoning_details", [])
                    if reasoning_list:
                        ai_reply = reasoning_list[0].get("text", "")

            if not ai_reply.strip():
                ai_reply = "I'm sorry, I'm processing multiple requests and couldn't formulate a reply. Please try again!"

            history.append({"role": "assistant", "content": ai_reply})
            await update.message.reply_text(ai_reply)

        elif response.status_code == 429:
            await update.message.reply_text("⚠️ We've hit a temporary rate limit. Please wait a moment before sending another message.")
        else:
            logger.error(f"OpenRouter Error Status {response.status_code}: {response.text}")
            await update.message.reply_text("🔌 Connecting to our AI models is taking longer than usual. Please try again in a few seconds.")

    except requests.exceptions.Timeout:
        await update.message.reply_text("⌛ The request timed out. Please try your message again shortly.")
    except Exception as e:
        logger.exception("Uncaught exception handling AI API request")
        await update.message.reply_text("🛠️ An error occurred inside our support framework. Please try again.")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("setname", setname_cmd))
    app.add_handler(CommandHandler("myinfo", myinfo_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message))
    logger.info("Samar Trader Family Support Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
