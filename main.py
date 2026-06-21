import os
import re
from datetime import datetime, timedelta
import telegram

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

# 📌 قائمة الروابط المسموحة
ALLOWED_DOMAINS = [
    "minepi.com",
    "pi.app",
]

# 📌 إعدادات مانع التكرار
FLOOD_LIMIT = 5
FLOOD_TIME = 4
MUTE_DURATION = 5

# 📌 الأنماط
LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|[a-zA-Z0-9-]+\.(com|net|org|io|app|xyz|me|co))",
    re.IGNORECASE
)
WALLET_PATTERN = re.compile(r"\b(0x[a-fA-F0-9]{40})\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<![a-zA-Z])(\+?\d{7,15})(?![a-zA-Z])")

# التخزين المؤقت
warnings_db = {}
user_messages = {}


async def send_log(bot, user, chat_title, deleted_text, violation_type="رابط"):
    if not LOG_CHANNEL_ID:
        return
    time_now = datetime.now().strftime("%I:%M %p - %d/%m/%Y")
    emoji_map = {
        "رابط غير مسموح": "🚫",
        "رقم هاتف": "📞",
        "محفظة رقمية": "💰",
        "⏳ سبام (تكرار)": "⏳",
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
    except Exception as e:
        print(f"❌ فشل إرسال اللوج: {type(e).__name__} - {e}")


async def mute_user(bot, chat_id, user_id, duration_minutes):
    try:
        until_date = datetime.now() + timedelta(minutes=duration_minutes)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=telegram.ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        return True
    except Exception as e:
        print(f"❌ فشل الكتم: {type(e).__name__} - {e}")
        return False


async def check_flood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    now = datetime.now()

    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["administrator", "creator"]:
            return False
    except:
        pass

    if user_id not in user_messages:
        user_messages[user_id] = []

    user_messages[user_id].append(now)
    cutoff = now - timedelta(seconds=FLOOD_TIME)
    user_messages[user_id] = [t for t in user_messages[user_id] if t > cutoff]

    if len(user_messages[user_id]) > FLOOD_LIMIT:
        success = await mute_user(
            bot=context.bot,
            chat_id=chat_id,
            user_id=user_id,
            duration_minutes=MUTE_DURATION
        )
        if success:
            await send_log(
                bot=context.bot,
                user=update.effective_user,
                chat_title=update.effective_chat.title or "المجموعة",
                deleted_text=f"تم كتم المستخدم لمدة {MUTE_DURATION} دقائق بسبب التكرار السريع ({len(user_messages[user_id])} رسائل في {FLOOD_TIME} ثوانٍ).",
                violation_type="⏳ سبام (تكرار)"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔇 {update.effective_user.first_name} تم كتمه لمدة {MUTE_DURATION} دقائق بسبب التكرار السريع للرسائل."
            )
        try:
            await update.message.delete()
        except:
            pass
        return True
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ Raskov Security Bot يعمل بنجاح.\n"
        "✅ القائمة البيضاء: minepi.com, pi.app\n"
        "⏳ مانع التكرار: 5 رسائل في 4 ثوانٍ = كتم 5 دقائق."
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

    # 🔥 فحص التكرار أولاً
    if await check_flood(update, context):
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat_title = update.effective_chat.title or "المجموعة"
    text = update.message.text

    # التحقق من المشرفين
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["administrator", "creator"]:
            return
    except Exception as e:
        print(f"Admin check error: {e}")

    is_violation = False
    violation_type = "رابط غير مسموح"

    # 1. محفظة
    if WALLET_PATTERN.search(text):
        is_violation = True
        violation_type = "محفظة رقمية"
    # 2. هاتف
    elif not is_violation and PHONE_PATTERN.search(text):
        is_violation = True
        violation_type = "رقم هاتف"
    # 3. رابط
    if not is_violation and LINK_PATTERN.search(text):
        is_allowed = any(domain in text.lower() for domain in ALLOWED_DOMAINS)
        if not is_allowed:
            is_violation = True
            violation_type = "رابط غير مسموح"

    if is_violation:
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Delete error: {e}")
            return

        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=chat_title,
            deleted_text=text,
            violation_type=violation_type
        )

        warnings_db[user_id] = warnings_db.get(user_id, 0) + 1
        count = warnings_db[user_id]

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
                    text=f"🚫 تم حظر {update.effective_user.first_name} تلقائياً بسبب تكرار المخالفات (3/3)."
                )
            except Exception as e:
                await send_log(
                    bot=context.bot,
                    user=update.effective_user,
                    chat_title=chat_title,
                    deleted_text=f"فشل حظر المستخدم بسبب: {e}",
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
