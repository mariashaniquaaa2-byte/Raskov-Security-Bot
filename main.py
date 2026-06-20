import os
import re
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# 📌 قائمة الروابط المسموحة فقط (خاص بمجتمع Pi)
ALLOWED_DOMAINS = [
    "minepi.com",
    "pi.app",
]

# 📌 أنماط الكشف (Regex)
LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|[a-zA-Z0-9-]+\.(com|net|org|io|app|xyz|me|co))",
    re.IGNORECASE
)

# نمط رقم الهاتف (يدعم معظم الصيغ)
PHONE_PATTERN = re.compile(
    r"(\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,5}[-.\s]?\d{1,5})"
)

# نمط محفظة إيثيريوم / BSC (تبدأ بـ 0x وتليها 40 حرفاً)
WALLET_PATTERN = re.compile(
    r"(0x[a-fA-F0-9]{40})"
)

# تخزين المخالفات
warnings_db = {}


async def send_log(bot, user, chat_title, deleted_text, violation_type="رابط"):
    """
    إرسال تقرير إلى قناة المشرفين مع نوع المخالفة
    """
    if not LOG_CHANNEL_ID:
        print("⚠️ LOG_CHANNEL_ID غير مضبوط")
        return

    time_now = datetime.now().strftime("%I:%M %p - %d/%m/%Y")
    
    # اختيار الإيموجي حسب نوع المخالفة
    if violation_type == "رقم هاتف":
        emoji = "📞"
    elif violation_type == "محفظة رقمية":
        emoji = "💰"
    else:
        emoji = "🚫"

    log_message = (
        f"🕒 {time_now}\n"
        f"{emoji} <b>تم حذف مخالفة: {violation_type}</b>\n"
        f"👤 المستخدم: {user.first_name}\n"
        f"🆔 معرفه: <code>{user.id}</code>\n"
        f"🏠 المجموعة: {chat_title}\n"
        f"📝 النص المحذوف:\n<code>{deleted_text[:150]}</code>"
    )

    try:
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode="HTML")
        print("✅ تم إرسال اللوج بنجاح")
    except Exception as e:
        print(f"❌ فشل إرسال اللوج: {type(e).__name__} - {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ Raskov Security Bot يعمل بنجاح.\n"
        "✅ القائمة البيضاء: minepi.com, pi.app"
    )


async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = warnings_db.get(user_id, 0)
    await update.message.reply_text(f"⚠️ عدد مخالفاتك: {count}/3")


async def test_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر لاختبار الإرسال إلى القناة"""
    if not LOG_CHANNEL_ID:
        await update.message.reply_text("❌ LOG_CHANNEL_ID غير مضبوط.")
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text="🧪 رسالة اختبار من البوت - إذا وصلتك فهذا يعني أن الإعدادات صحيحة."
        )
        await update.message.reply_text("✅ تم الإرسال إلى القناة بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {type(e).__name__} - {e}")


async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat_title = update.effective_chat.title or "المجموعة"
    text = update.message.text

    # 1. التحقق من صلاحيات المشرف (تجاوز الفلتر)
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["administrator", "creator"]:
            return
    except Exception as e:
        print(f"Admin check error: {e}")

    # 2. متغيرات لتحديد المخالفة
    is_violation = False
    violation_type = "رابط"
    matched_text = text

    # ----- التحقق من الرابط (مع القائمة البيضاء) -----
    if LINK_PATTERN.search(text):
        # نفحص هل الرابط ضمن القائمة المسموحة؟
        is_allowed = False
        for domain in ALLOWED_DOMAINS:
            if domain in text.lower():
                is_allowed = True
                break
        
        if not is_allowed:
            is_violation = True
            violation_type = "رابط غير مسموح"

    # ----- التحقق من رقم الهاتف -----
    if not is_violation and PHONE_PATTERN.search(text):
        is_violation = True
        violation_type = "رقم هاتف"

    # ----- التحقق من المحفظة الرقمية -----
    if not is_violation and WALLET_PATTERN.search(text):
        is_violation = True
        violation_type = "محفظة رقمية"

    # 3. إذا كانت مخالفة، قم بالمعالجة
    if is_violation:
        # حذف الرسالة
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Delete error: {e}")
            return

        # إرسال التقرير إلى قناة اللوجات (مع نوع المخالفة)
        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=chat_title,
            deleted_text=text,
            violation_type=violation_type
        )

        # تحديث عدد المخالفات
        warnings_db[user_id] = warnings_db.get(user_id, 0) + 1
        count = warnings_db[user_id]

        print(f"VIOLATION | User={user_id} | Chat={chat_id} | Type={violation_type} | Warnings={count}")

        # إرسال تحذير أو حظر
        if count == 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {update.effective_user.first_name} تحذير 1/3 - ممنوع نشر الروابط أو الأرقام أو المحافظ."
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
                    text=f"🚫 تم حظر {update.effective_user.first_name} تلقائياً بسبب تكرار المخالفات."
                )
            except Exception as e:
                print(f"Ban error: {e}")


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("testlog", test_log))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))

    app.run_polling()


if __name__ == "__main__":
    main()
