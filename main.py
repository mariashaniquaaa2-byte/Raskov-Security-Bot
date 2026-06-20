import os
import re
from datetime import datetime  # 📌 إضافة جديدة للتاريخ والوقت

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

# 📌 جلب معرف قناة اللوجات من متغيرات البيئة (ضعه في Railway)
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# تخزين المخالفات
warnings_db = {}

LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|[a-zA-Z0-9-]+\.(com|net|org|io|app|xyz|me|co))",
    re.IGNORECASE
)


# 📌 دالة إرسال التقرير إلى قناة المشرفين (جديدة)
async def send_log(bot, user, chat_title, deleted_text):
    """
    ترسل تقريراً مفصلاً إلى قناة اللوجات الخاصة
    """
    if not LOG_CHANNEL_ID:  # إذا لم يُحدد المعرف، لا تفعل شيئاً
        return

    # تنسيق الوقت (مثال: 03:45 PM - 21/06/2026)
    time_now = datetime.now().strftime("%I:%M %p - %d/%m/%Y")

    log_message = (
        f"🕒 {time_now}\n"
        f"🚫 <b>تم حذف رابط مخالف</b>\n"
        f"👤 المستخدم: {user.first_name}\n"
        f"🆔 معرفه: <code>{user.id}</code>\n"
        f"🏠 المجموعة: {chat_title}\n"
        f"📝 النص المحذوف:\n<code>{deleted_text[:150]}</code>"
    )

    try:
        await bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=log_message,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ فشل إرسال اللوج: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ Raskov Security Bot يعمل بنجاح."
    )


async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = warnings_db.get(user_id, 0)
    await update.message.reply_text(
        f"⚠️ عدد مخالفاتك: {count}/3"
    )


async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat_title = update.effective_chat.title or "المجموعة"

    # التحقق من صلاحيات المشرف
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["administrator", "creator"]:
            return
    except Exception as e:
        print(f"Admin check error: {e}")

    text = update.message.text

    if LINK_PATTERN.search(text):
        # 1. حذف الرسالة
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Delete error: {e}")
            return

        # 2. 📌 إرسال التقرير إلى قناة اللوجات (الإضافة الجديدة)
        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=chat_title,
            deleted_text=text
        )

        # 3. تحديث المخالفات
        warnings_db[user_id] = warnings_db.get(user_id, 0) + 1
        count = warnings_db[user_id]

        print(f"LINK DELETED | User={user_id} | Chat={chat_id} | Warnings={count}")

        # 4. إرسال تحذير أو حظر
        if count == 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {update.effective_user.first_name} تحذير 1/3 - يمنع نشر الروابط."
            )
        elif count == 2:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {update.effective_user.first_name} تحذير 2/3 - التحذير الأخير."
            )
        elif count >= 3:
            try:
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🚫 تم حظر {update.effective_user.first_name} تلقائياً بسبب تكرار نشر الروابط."
                )
            except Exception as e:
                print(f"Ban error: {e}")


# ----- تشغيل البوت -----
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("warnings", warnings))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))

app.run_polling()
