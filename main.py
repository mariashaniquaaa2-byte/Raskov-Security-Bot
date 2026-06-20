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

# 📌 قائمة الروابط المسموحة (خاص بـ Pi)
ALLOWED_DOMAINS = [
    "minepi.com",
    "pi.app",
]

# 📌 الأنماط (محسّنة)
LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|[a-zA-Z0-9-]+\.(com|net|org|io|app|xyz|me|co))",
    re.IGNORECASE
)

# 🔥 نمط المحفظة (الأولوية القصوى) - يبحث عن 0x + 40 حرفاً
WALLET_PATTERN = re.compile(
    r"\b(0x[a-fA-F0-9]{40})\b",
    re.IGNORECASE
)

# 🔥 نمط رقم الهاتف (محسّن) - فقط أرقام، من 7 إلى 15 رقماً، مع + اختياري
# يتجنب التقاط 0x... لأن x ليس رقماً
PHONE_PATTERN = re.compile(
    r"(?<![a-zA-Z])(\+?\d{7,15})(?![a-zA-Z])"
)

# تخزين المخالفات (ملاحظة: سيتم مسحها عند إعادة تشغيل البوت)
warnings_db = {}


async def send_log(bot, user, chat_title, deleted_text, violation_type="رابط"):
    if not LOG_CHANNEL_ID:
        print("⚠️ LOG_CHANNEL_ID غير مضبوط")
        return

    time_now = datetime.now().strftime("%I:%M %p - %d/%m/%Y")
    
    emoji_map = {
        "رابط غير مسموح": "🚫",
        "رقم هاتف": "📞",
        "محفظة رقمية": "💰",
    }
    emoji = emoji_map.get(violation_type, "⚠️")

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

    # 1. التحقق من المشرفين (تجاوز الفلتر)
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["administrator", "creator"]:
            return
    except Exception as e:
        print(f"Admin check error: {e}")

    # 2. تحديد المخالفة (مع الأولويات)
    is_violation = False
    violation_type = "رابط غير مسموح"
    matched_text = text

    # 🔥 الأولوية 1: المحفظة الرقمية (تتحقق أولاً)
    if WALLET_PATTERN.search(text):
        is_violation = True
        violation_type = "محفظة رقمية"

    # 🔥 الأولوية 2: رقم الهاتف (إذا لم تكن محفظة)
    elif not is_violation and PHONE_PATTERN.search(text):
        is_violation = True
        violation_type = "رقم هاتف"

    # 🔥 الأولوية 3: الرابط (إذا لم يكن محظوراً بالأعلى)
    if not is_violation and LINK_PATTERN.search(text):
        # نفحص القائمة البيضاء
        is_allowed = False
        for domain in ALLOWED_DOMAINS:
            if domain in text.lower():
                is_allowed = True
                break
        if not is_allowed:
            is_violation = True
            violation_type = "رابط غير مسموح"

    # 3. معالجة المخالفة
    if is_violation:
        # حذف الرسالة
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Delete error: {e}")
            return

        # إرسال التقرير إلى القناة
        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=chat_title,
            deleted_text=text,
            violation_type=violation_type
        )

        # تحديث المخالفات
        warnings_db[user_id] = warnings_db.get(user_id, 0) + 1
        count = warnings_db[user_id]

        print(f"VIOLATION | User={user_id} | Type={violation_type} | Count={count}")

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
                # محاولة الحظر
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🚫 تم حظر {update.effective_user.first_name} تلقائياً بسبب تكرار المخالفات (3/3)."
                )
                print(f"✅ تم حظر المستخدم {user_id} بنجاح")
            except Exception as e:
                # 🔥 رسالة خطأ واضحة في السجلات
                error_msg = f"❌ فشل الحظر: {type(e).__name__} - {e}"
                print(error_msg)
                # إرسال تنبيه للمشرفين في قناة اللوجات
                await send_log(
                    bot=context.bot,
                    user=update.effective_user,
                    chat_title=chat_title,
                    deleted_text=f"فشل حظر المستخدم بسبب: {e}\nتأكد من أن البوت Admin ولديه صلاحية الحظر.",
                    violation_type="⚠️ خطأ في الصلاحيات"
                )


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("testlog", test_log))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anti_link))

    app.run_polling()


if __name__ == "__main__":
    main()
