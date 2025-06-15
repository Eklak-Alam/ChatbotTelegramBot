import os
import logging
from typing import List, Dict, Optional
import httpx

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load secrets from .env
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BOT_USERNAME = os.getenv("BOT_USERNAME", "genz_mediator_bot").lower()

# Conversation states
CHATTING = 1

# Gemini API configuration - Updated to use gemini-2.0-flash
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
HEADERS = {"Content-Type": "application/json"}

async def generate_gemini_response(prompt: str, chat_history: List[Dict] = None) -> str:
    """Generate response using Gemini API with gemini-2.0-flash model"""
    if chat_history is None:
        chat_history = []
    
    contents = []
    
    # Add chat history if available
    for msg in chat_history:
        if msg['role'] == 'user':
            contents.append({"role": "user", "parts": [{"text": msg['content']}]})
        else:
            contents.append({"role": "model", "parts": [{"text": msg['content']}]})
    
    # Add current prompt
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    
    data = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 500
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                headers=HEADERS,
                json=data,
                timeout=30.0
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'candidates' in result and result['candidates']:
                    return result['candidates'][0]['content']['parts'][0]['text']
                return "Sorry, I couldn't generate a response."
            else:
                logger.error(f"Gemini API Error: {response.text}")
                return f"⚠️ API Error (Status: {response.status_code}): {response.text}"
                
    except Exception as e:
        logger.error(f"Request Error: {str(e)}")
        return "⚠️ Sorry, I encountered an error. Please try again later."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the command /start is issued."""
    user = update.effective_user
    welcome_message = (
        f"👋 Hi {user.first_name}! I'm your AI Mediator Bot powered by Gemini Flash.\n\n"
        f"In groups, mention me (@{BOT_USERNAME}) to analyze conversations.\n\n"
        "Commands available:\n"
        "/help - Show help message\n"
        "/chat - Start a conversation\n"
        "/stop - End conversation"
    )
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message when the command /help is issued."""
    help_text = (
        "🤖 <b>AI Mediator Bot Help</b> 🤖\n\n"
        "<b>Group Chat Features:</b>\n"
        f"- Mention me (@{BOT_USERNAME}) to analyze recent messages\n"
        "- I'll provide neutral summaries and suggestions\n\n"
        "<b>Private Chat Commands:</b>\n"
        "/start - Welcome message\n"
        "/help - Show this help\n"
        "/chat - Start 1-on-1 conversation\n"
        "/stop - End conversation\n\n"
        "Powered by Google's Gemini Flash (Free Version)"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')

async def analyze_conversation(messages: List[str]) -> str:
    """Analyzes group messages and returns a summary + suggestion."""
    prompt = (
        "You are an unbiased, emotionally intelligent AI mediator. "
        "Given these group messages, provide:\n"
        "1. A short, neutral summary\n"
        "2. An unbiased suggestion\n"
        "Format strictly as:\n"
        "Summary: <summary>\n"
        "Suggestion: <suggestion>\n"
        "Messages:\n" + "\n".join(messages[-10:])
    )
    
    return await generate_gemini_response(prompt)

async def chat_with_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts a conversation with the AI."""
    context.user_data["chat_history"] = []
    await update.message.reply_text(
        "💬 You're now chatting with Gemini Flash AI. Send me any message!\n"
        "Type /stop to end the chat.",
        reply_markup=ReplyKeyboardRemove()
    )
    return CHATTING

async def stop_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ends the conversation with the AI."""
    if "chat_history" in context.user_data:
        del context.user_data["chat_history"]
    await update.message.reply_text(
        "👍 Chat ended. Start again with /chat!",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def handle_ai_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles user messages in private chat."""
    try:
        user_message = update.message.text
        
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, 
            action="typing"
        )
        
        # Get or initialize chat history
        chat_history = context.user_data.get("chat_history", [])
        
        # Generate response
        response = await generate_gemini_response(user_message, chat_history)
        
        # Update chat history
        chat_history.append({"role": "user", "content": user_message})
        chat_history.append({"role": "model", "content": response})
        context.user_data["chat_history"] = chat_history[-6:]  # Keep last 3 exchanges
        
        await update.message.reply_text(response)
        
        return CHATTING
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("⚠️ An error occurred. Please try again.")
        return CHATTING

async def cache_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Caches recent group messages for context."""
    if message := update.effective_message:
        if text := message.text:
            chat_history = context.chat_data.setdefault("recent_msgs", [])
            chat_history.append(f"{message.from_user.first_name}: {text}")
            context.chat_data["recent_msgs"] = chat_history[-10:]

async def handle_group_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles when bot is mentioned in a group."""
    try:
        message = update.effective_message
        if not message or not message.text or not update.effective_chat:
            return

        if f"@{BOT_USERNAME}" not in message.text.lower():
            return

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, 
            action="typing"
        )

        chat_history = context.chat_data.get("recent_msgs", [])
        chat_history.append(f"{message.from_user.first_name}: {message.text}")
        context.chat_data["recent_msgs"] = chat_history[-10:]

        analysis = await analyze_conversation(chat_history)
        await message.reply_text(analysis, reply_to_message_id=message.message_id)

    except Exception as e:
        logger.error(f"Group error: {e}")
        await update.effective_message.reply_text("⚠️ Error processing request.")

def main():
    """Run the bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN in .env")
        return
    if not GEMINI_API_KEY:
        logger.error("Missing GEMINI_API_KEY in .env")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("chat", chat_with_ai)],
        states={
            CHATTING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_response),
            ],
        },
        fallbacks=[CommandHandler("stop", stop_chat)],
    )
    app.add_handler(conv_handler)

    # Group message handlers
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            cache_messages
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & filters.Entity("mention"),
            handle_group_mention
        )
    )

    logger.info("🤖 Gemini Flash-powered bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()