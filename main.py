from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8617112358:AAFY9k6hnIqQ_lSh_7o0OA_-SBmJB3YsW7s"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ Security Bot يعمل بنجاح!")

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))

app.run_polling()
