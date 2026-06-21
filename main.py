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

# ===================== إعدادات البيئة =====================
TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# ===================== القائمة البيضاء =====================
ALLOWED_DOMAINS = ["minepi.com", "pi.app"]

# ===================== إعدادات مانع التكرار =====================
FLOOD_LIMIT = 5          # عدد الرسائل المسموح بها
FLOOD_TIME = 4           # في خلال X ثواني
MUTE_DURATION = 5        # مدة الكتم بالدقائق

# ===================== إعدادات القفل =====================
LOCK_LINKS = True        # مفعل افتراضياً
LOCK_MEDIA = False       # غير مفعل افتراضياً
LOCK_FORWARD = False     # غير مفعل افتراضياً

# ===================== الأنماط (Regex) =====================
LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|[a-zA-Z0-9-]+\.(com|net|org|io|app|xyz|me|co))",
    re.IGNORECASE
)
WALLET_PATTERN = re.compile(r"\b(0x[a-fA-F0-9]{40})\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<![a-zA-Z])(\+?\d{7,15})(?![a-zA-Z])")

# ===================== التخزين المؤقت =====================
warnings_db = {}          # {user_id: count}
user_messages = {}        # {user_id: [timestamps]}


# ===================== دوال المساعدة =====================

async def is_admin(bot, chat_id, user_id):
    """التحقق من صلاحيات المشرف"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False


def clean_obfuscated_text(text: str) -> str:
    """
    تنظيف النص من محاولات إخفاء الروابط (مسافات، dot، حروف مشابهة)
    """
    # إزالة المسافات
    cleaned = re.sub(r'\s+', '', text)
    # dot -> .
    cleaned = re.sub(r'dot', '.', cleaned, flags=re.IGNORECASE)
    # at -> @
    cleaned = re.sub(r'at', '@', cleaned, flags=re.IGNORECASE)
    # استبدال الأحرف المشابهة
    replacements = {
        '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's',
        '7': 't', '@': 'a', '¢': 'c', '₿': 'b'
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    # hxxp -> http
    cleaned = re.sub(r'hxxps?', 'https', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'hxxp', 'http', cleaned, flags=re.IGNORECASE)
    return cleaned


async def send_log(bot, user, chat_title, deleted_text, violation_type="رابط"):
    """إرسال تقرير إلى قناة اللوجات"""
    if not LOG_CHANNEL_ID:
        return

    time_now = datetime.now().strftime("%I:%M %p - %d/%m/%Y")
    emoji_map = {
        "رابط غير مسموح": "🚫",
        "رابط غير مسموح (ملتف)": "🚫",
        "رقم هاتف": "📞",
        "محفظة رقمية": "💰",
        "⏳ سبام (تكرار)": "⏳",
        "صورة/فيديو": "🖼️",
        "رسالة معاد توجيهها": "↩️",
        "⚠️ إدارة": "⚙️",
        "🔄 إعادة تعيين مخالفات": "🔄",
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
    """كتم مستخدم لمدة محددة"""
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
    """فحص التكرار، وإذا تجاوز الحد يُكتم المستخدم"""
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


# ===================== أوامر المشرفين =====================

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حظر عضو (بالرد على رسالته)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ قم بالرد على رسالة العضو المستهدف.")
        return

    target = update.message.reply_to_message.from_user
    target_id = target.id

    if await is_admin(context.bot, chat_id, target_id):
        await update.message.reply_text("❌ لا يمكنك حظر مشرف.")
        return

    try:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=target_id)
        await update.message.reply_text(f"✅ تم حظر {target.first_name}.")
        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=update.effective_chat.title or "المجموعة",
            deleted_text=f"قام {update.effective_user.first_name} بحظر {target.first_name} (ID: {target_id})",
            violation_type="⚠️ إدارة (حظر)"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الحظر: {e}")


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فك حظر عضو باستخدام المعرف"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ استخدم: /unban [معرف المستخدم]")
        return

    try:
        target_id = int(args[0])
        await context.bot.unban_chat_member(chat_id=chat_id, user_id=target_id)
        await update.message.reply_text(f"✅ تم فك الحظر عن {target_id}.")
        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=update.effective_chat.title or "المجموعة",
            deleted_text=f"قام {update.effective_user.first_name} بفك الحظر عن {target_id}",
            violation_type="⚠️ إدارة (فك حظر)"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ فشل فك الحظر: {e}")


async def reset_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة تعيين مخالفات عضو (بالرد على رسالته)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ قم بالرد على رسالة العضو المستهدف.")
        return

    target = update.message.reply_to_message.from_user
    target_id = target.id

    if target_id in warnings_db:
        del warnings_db[target_id]

    await update.message.reply_text(f"✅ تم إعادة تعيين مخالفات {target.first_name}.")
    await send_log(
        bot=context.bot,
        user=update.effective_user,
        chat_title=update.effective_chat.title or "المجموعة",
        deleted_text=f"قام {update.effective_user.first_name} بإعادة تعيين مخالفات {target.first_name} (ID: {target_id})",
        violation_type="🔄 إعادة تعيين مخالفات"
    )


async def toggle_lock_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    global LOCK_FORWARD
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    LOCK_FORWARD = not LOCK_FORWARD
    status = "مفعل ✅" if LOCK_FORWARD else "معطل ❌"
    await update.message.reply_text(f"↩️ منع الرسائل المعاد توجيهها: {status}")


# ===================== الأوامر العامة =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡️ <b>Raskov Security Bot v4.0</b>\n\n"
        "🔹 <b>القائمة البيضاء</b>: minepi.com, pi.app\n"
        "🔹 <b>مانع التكرار</b>: 5 رسائل / 4 ثوان = كتم 5د\n"
        "🔹 <b>منع الروابط</b>: مفعل ✅\n"
        "🔹 <b>منع الميديا</b>: معطل ❌\n"
        "🔹 <b>منع التوجيه</b>: معطل ❌\n\n"
        "👑 <b>أوامر المشرفين</b>:\n"
        "/ban - رد على رسالة العضو\n"
        "/unban [ID]\n"
        "/resetwarnings - رد على رسالة العضو\n"
        "/locklinks - تبديل\n"
        "/lockmedia - تبديل\n"
        "/lockforward - تبديل\n\n"
        "👤 <b>أوامر الأعضاء</b>:\n"
        "/warnings - عرض مخالفاتك\n"
        "/testlog - اختبار اللوجات (للمشرفين)",
        parse_mode="HTML"
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
            text="🧪 رسالة اختبار - الإعدادات صحيحة ✅"
        )
        await update.message.reply_text("✅ تم الإرسال إلى القناة بنجاح.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")


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

    # ====== 3. فحص الميديا ======
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
            deleted_text=f"[معاد توجيهها من: {update.message.forward_sender_name or 'مجهول'}]",
            violation_type="↩️ رسالة معاد توجيهها (ممنوع)"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ {user.first_name} ممنوع إعادة توجيه الرسائل."
        )
        return

    # ====== 5. فحص النص ======
    if not update.message.text:
        return

    original_text = update.message.text
    cleaned_text = clean_obfuscated_text(original_text)  # تنظيف النص

    is_violation = False
    violation_type = "رابط غير مسموح"

    # 5a. محفظة رقمية
    if WALLET_PATTERN.search(cleaned_text):
        is_violation = True
        violation_type = "محفظة رقمية"

    # 5b. رقم هاتف
    elif not is_violation and PHONE_PATTERN.search(cleaned_text):
        is_violation = True
        violation_type = "رقم هاتف"

    # 5c. رابط (مع مراعاة القفل والقائمة البيضاء)
    if not is_violation and LOCK_LINKS and LINK_PATTERN.search(cleaned_text):
        is_allowed = any(domain in cleaned_text.lower() for domain in ALLOWED_DOMAINS)
        if not is_allowed:
            is_violation = True
            violation_type = "رابط غير مسموح" if original_text == cleaned_text else "رابط غير مسموح (ملتف)"

    if is_violation:
        # حذف الرسالة
        try:
            await update.message.delete()
        except Exception as e:
            print(f"Delete error: {e}")
            return

        # إرسال التقرير إلى اللوجات (مع النص الأصلي)
        await send_log(
            bot=context.bot,
            user=user,
            chat_title=chat_title,
            deleted_text=original_text,
            violation_type=violation_type
        )

        # تحديث المخالفات
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
    app.add_handler(CommandHandler("resetwarnings", reset_warnings))
    app.add_handler(CommandHandler("locklinks", toggle_lock_links))
    app.add_handler(CommandHandler("lockmedia", toggle_lock_media))
    app.add_handler(CommandHandler("lockforward", toggle_lock_forward))

    # أوامر عامة
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("testlog", test_log))

    # معالج جميع الرسائل (يأتي أخيراً)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, anti_link))

    print("🤖 البوت يعمل الآن...")
    app.run_polling()


if __name__ == "__main__":
    main()
