from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8617112358:AAFY9k6hnIqQ_lSh_7o0OA_-SBmJB3YsW7s"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ Security Bot يعمل بنجاح!")

async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        text = update.message.text.lower()

        blocked = [
            "http://",
            "https://",
            "t.me/",
            "telegram.me/"
        ]

        if any(word in text for word in blocked):
            await update.message.delete()

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ تم حذف رابط أرسله {update.effective_user.first_name}"
            )

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT, anti_link))

app.run_polling()
