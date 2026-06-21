import os
import re
from datetime import datetime, timedelta
import telegram

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# 📌 القائمة البيضاء
ALLOWED_DOMAINS = ["minepi.com", "pi.app"]

# 📌 إعدادات مانع التكرار
FLOOD_LIMIT = 5
FLOOD_TIME = 4
MUTE_DURATION = 5

# 📌 إعدادات القفل (جديدة)
LOCK_LINKS = True      # مفعل افتراضياً
LOCK_MEDIA = False     # غير مفعل افتراضياً
LOCK_FORWARD = False   # غير مفعل افتراضياً

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


# ===================== دوال المساعدة =====================

async def is_admin(bot, chat_id, user_id):
    """التحقق مما إذا كان المستخدم مشرفاً"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False


async def send_log(bot, user, chat_title, deleted_text, violation_type="رابط"):
    if not LOG_CHANNEL_ID:
        return
    time_now = datetime.now().strftime("%I:%M %p - %d/%m/%Y")
    emoji_map = {
        "رابط غير مسموح": "🚫",
        "رقم هاتف": "📞",
        "محفظة رقمية": "💰",
        "⏳ سبام (تكرار)": "⏳",
        "صورة/فيديو": "🖼️",
        "رسالة معاد توجيهها": "↩️",
        "⚠️ إدارة": "⚙️",
    }
    emoji = emoji_map.get(violation_type, "⚠️")
    log_message = (
        f"🕒 {time_now}\n"
        f"{emoji} <b>{violation_type}</b>\n"
        f"👤 المستخدم: {user.first_name}\n"
        f"🆔 معرفه: <code>{user.id}</code>\n"
        f"🏠 المجموعة: {chat_title}\n"
        f"📝 التفاصيل:\n<code>{deleted_text[:150]}</code>"
    )
    try:
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode="HTML")
    except Exception as e:
        print(f"❌ فشل إرسال اللوج: {e}")


async def mute_user(bot, chat_id, user_id, duration_minutes):
    try:
        until_date = datetime.now() + timedelta(minutes=duration_minutes)
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        return True
    except Exception as e:
        print(f"❌ فشل الكتم: {e}")
        return False


async def check_flood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    now = datetime.now()

    if await is_admin(context.bot, chat_id, user_id):
        return False

    if user_id not in user_messages:
        user_messages[user_id] = []

    user_messages[user_id].append(now)
    cutoff = now - timedelta(seconds=FLOOD_TIME)
    user_messages[user_id] = [t for t in user_messages[user_id] if t > cutoff]

    if len(user_messages[user_id]) > FLOOD_LIMIT:
        success = await mute_user(context.bot, chat_id, user_id, MUTE_DURATION)
        if success:
            await send_log(
                bot=context.bot,
                user=update.effective_user,
                chat_title=update.effective_chat.title or "المجموعة",
                deleted_text=f"كتم لمدة {MUTE_DURATION} دقائق (تكرار: {len(user_messages[user_id])} رسائل في {FLOOD_TIME} ثوانٍ).",
                violation_type="⏳ سبام (تكرار)"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔇 {update.effective_user.first_name} تم كتمه {MUTE_DURATION} دقائق للتكرار السريع."
            )
        try:
            await update.message.delete()
        except:
            pass
        return True
    return False


# ===================== أوامر المشرفين (جديدة) =====================

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حظر عضو بالرد على رسالته"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # التحقق من صلاحيات الآمر
    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    # الرد على رسالة العضو المستهدف
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ قم بالرد على رسالة العضو الذي تريد حظره.")
        return

    target_user = update.message.reply_to_message.from_user
    target_id = target_user.id

    # منع حظر المشرفين
    if await is_admin(context.bot, chat_id, target_id):
        await update.message.reply_text("❌ لا يمكنك حظر مشرف.")
        return

    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        await update.message.reply_text(f"✅ تم حظر {target_user.first_name}.")
        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=update.effective_chat.title or "المجموعة",
            deleted_text=f"قام {update.effective_user.first_name} بحظر {target_user.first_name} (ID: {target_id})",
            violation_type="⚠️ إدارة (حظر)"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الحظر: {e}")


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فك حظر عضو"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    # محاولة قراءة ID من الأمر
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ استخدم: /unban [معرف المستخدم]")
        return

    try:
        target_id = int(args[0])
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=target_id)
        await update.message.reply_text(f"✅ تم فك الحظر عن المستخدم {target_id}.")
        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=update.effective_chat.title or "المجموعة",
            deleted_text=f"قام {update.effective_user.first_name} بفك الحظر عن {target_id}",
            violation_type="⚠️ إدارة (فك حظر)"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ فشل فك الحظر: {e}")


async def toggle_lock_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تشغيل/إيقاف منع الروابط"""
    global LOCK_LINKS
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    LOCK_LINKS = not LOCK_LINKS
    status = "مفعل ✅" if LOCK_LINKS else "معطل ❌"
    await update.message.reply_text(f"🔗 منع الروابط: {status}")


async def toggle_lock_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تشغيل/إيقاف منع الصور والفيديوهات"""
    global LOCK_MEDIA
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    LOCK_MEDIA = not LOCK_MEDIA
    status = "مفعل ✅" if LOCK_MEDIA else "معطل ❌"
    await update.message.reply_text(f"🖼️ منع الصور والفيديوهات: {status}")


async def toggle_lock_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تشغيل/إيقاف منع الرسائل المعاد توجيهها"""
    global LOCK_FORWARD
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    LOCK_FORWARD = not LOCK_FORWARD
    status = "مفعل ✅" if LOCK_FORWARD else "معطل ❌"
    await update.message.reply_text(f"↩️ منع الرسائل المعاد توجيهها: {status}")


# ===================== الأمر الأساسي start =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ Raskov Security Bot v3.0\n"
        "✅ قائمة بيضاء: minepi.com, pi.app\n"
        "⏳ مانع تكرار: 5 رسائل / 4 ثوان = كتم 5د\n"
        "🔗 منع الروابط: مفعل\n"
        "🖼️ منع الميديا: معطل\n"
        "↩️ منع التوجيه: معطل\n\n"
        "👑 أوامر المشرفين:\n"
        "/ban - رد على رسالة\n"
        "/unban [ID]\n"
        "/locklinks - تبديل\n"
        "/lockmedia - تبديل\n"
        "/lockforward - تبديل"
    )


async def warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = warnings_db.get(user_id, 0)
    await update.message.reply_text(f"⚠️ مخالفاتك: {count}/3")


async def test_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not LOG_CHANNEL_ID:
        await update.message.reply_text("❌ LOG_CHANNEL_ID غير مضبوط.")
        return
    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text="🧪 رسالة اختبار - الإعدادات صحيحة ✅"
        )
        await update.message.reply_text("✅ تم الإرسال إلى القناة.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل: {e}")


# ===================== المعالج الرئيسي =====================

async def anti_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat_title = update.effective_chat.title or "المجموعة"
    user = update.effective_user

    # 1. فحص التكرار
    if await check_flood(update, context):
        return

    # 2. التحقق من المشرفين
    if await is_admin(context.bot, chat_id, user_id):
        return

    # ====== 3. فحص الميديا (صور وفيديوهات) ======
    if LOCK_MEDIA and (update.message.photo or update.message.video):
        try:
            await update.message.delete()
        except:
            pass
        await send_log(
            bot=context.bot,
            user=user,
            chat_title=chat_title,
            deleted_text="[تم حذف صورة أو فيديو]",
            violation_type="🖼️ صورة/فيديو (ممنوع)"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ {user.first_name} ممنوع نشر الصور والفيديوهات."
        )
        return

    # ====== 4. فحص الرسائل المعاد توجيهها ======
    if LOCK_FORWARD and update.message.forward_date:
        try:
            await update.message.delete()
        except:
            pass
        await send_log(
            bot=context.bot,
            user=user,
            chat_title=chat_title,
            deleted_text=f"[رسالة معاد توجيهها من: {update.message.forward_sender_name or 'مجهول'}]",
            violation_type="↩️ رسالة معاد توجيهها (ممنوع)"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ {user.first_name} ممنوع إعادة توجيه الرسائل."
        )
        return

    # ====== 5. فحص النص (روابط، أرقام، محافظ) ======
    if not update.message.text:
        return

    text = update.message.text
    is_violation = False
    violation_type = "رابط غير مسموح"

    # محفظة
    if WALLET_PATTERN.search(text):
        is_violation = True
        violation_type = "محفظة رقمية"
    # هاتف
    elif not is_violation and PHONE_PATTERN.search(text):
        is_violation = True
        violation_type = "رقم هاتف"
    # رابط (مع مراعاة قفل الروابط)
    if not is_violation and LOCK_LINKS and LINK_PATTERN.search(text):
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
            user=user,
            chat_title=chat_title,
            deleted_text=text,
            violation_type=violation_type
        )

        warnings_db[user_id] = warnings_db.get(user_id, 0) + 1
        count = warnings_db[user_id]

        if count == 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {user.first_name} تحذير 1/3 - ممنوع النشر المخالف."
            )
        elif count == 2:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {user.first_name} تحذير 2/3 - التحذير الأخير."
            )
        elif count >= 3:
            try:
                await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🚫 تم حظر {user.first_name} تلقائياً (3/3)."
                )
            except Exception as e:
                await send_log(
                    bot=context.bot,
                    user=user,
                    chat_title=chat_title,
                    deleted_text=f"فشل الحظر: {e}",
                    violation_type="⚠️ خطأ صلاحيات"
                )


# ===================== تشغيل البوت =====================

def main():
    app = Application.builder().token(TOKEN).build()

    # أوامر المشرفين
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CommandHandler("locklinks", toggle_lock_links))
    app.add_handler(CommandHandler("lockmedia", toggle_lock_media))
    app.add_handler(CommandHandler("lockforward", toggle_lock_forward))

    # أوامر عامة
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("testlog", test_log))

    # معالج الرسائل (يأتي آخراً)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, anti_link))

    app.run_polling()


if __name__ == "__main__":
    main()
