import os
import re
import random
from datetime import datetime, timedelta
import telegram

from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ===================== إعدادات البيئة =====================
TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# ===================== قوانين المجموعة =====================
GROUP_RULES = (
    "📜 <b>قوانين المجموعة</b> 📜\n\n"
    "1️⃣ ممنوع نشر الروابط (ما عدا minepi.com و pi.app).\n"
    "2️⃣ ممنوع نشر أرقام الهواتف أو المحافظ الرقمية.\n"
    "3️⃣ ممنوع التكرار السريع للرسائل (سبام).\n"
    "4️⃣ ممنوع نشر الصور أو الفيديوهات غير المفيدة.\n"
    "5️⃣ احترام جميع الأعضاء، والابتعاد عن الشتائم.\n"
    "6️⃣ التقيد بمواضيع المجموعة الأساسية.\n\n"
    "⚠️ المخالفة = تحذير، والمخالفة الثالثة = حظر تلقائي.\n"
    "🔐 للتحقق البشري، اكتب نتيجة العملية الحسابية في الخاص أو المجموعة."
)

# ===================== إعدادات الحماية =====================
AUTO_KICK_TIMEOUT = 60        # مهلة الكابتشا بالثواني
MIN_ACCOUNT_AGE_DAYS = 1      # الحد الأدنى لعمر الحساب (أيام)
CAPTCHA_ATTEMPTS = 3          # عدد المحاولات المسموحة

# ===================== إعدادات مانع التكرار =====================
FLOOD_LIMIT = 5
FLOOD_TIME = 4
MUTE_DURATION = 5

# ===================== القائمة البيضاء =====================
ALLOWED_DOMAINS = ["minepi.com", "pi.app"]

# ===================== إعدادات القفل =====================
LOCK_LINKS = True
LOCK_MEDIA = False
LOCK_FORWARD = False

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
pending_captcha = {}      # {user_id: {"answer": int, "attempts": int, "job": job}}


# ===================== دوال المساعدة الأساسية =====================

async def is_admin(bot, chat_id, user_id):
    """التحقق من صلاحيات المشرف"""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except:
        return False


def clean_obfuscated_text(text: str) -> str:
    """تنظيف النص من محاولات إخفاء الروابط"""
    cleaned = re.sub(r'\s+', '', text)
    cleaned = re.sub(r'dot', '.', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'at', '@', cleaned, flags=re.IGNORECASE)
    replacements = {'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a'}
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
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
        "👋 ترحيب": "👋",
        "🚪 مغادرة": "🚪",
        "❌ طرد بسبب عدم الموافقة": "⛔",
        "🤖 كابتشا - نجاح": "✅",
        "🤖 كابتشا - فشل": "❌",
        "🛑 حساب جديد (ممنوع)": "🛑",
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


# ===================== دوال الكابتشا =====================

def generate_captcha() -> tuple:
    """توليد مسألة حسابية عشوائية"""
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    op = random.choice(['+', '-'])
    if op == '-':
        if a < b:
            a, b = b, a
        answer = a - b
    else:
        answer = a + b
    return f"{a} {op} {b} = ؟", answer


async def send_captcha(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, first_name: str):
    """إرسال الكابتشا للعضو الجديد"""
    question, answer = generate_captcha()
    pending_captcha[user_id] = {
        "answer": answer,
        "attempts": 0,
        "chat_id": chat_id,
        "first_name": first_name
    }
    keyboard = [[InlineKeyboardButton("🔄 تحديث الكابتشا", callback_data=f"refresh_captcha_{user_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🤖 تحقق بشري مطلوب!\nأجب على السؤال التالي (اكتب الرقم فقط):\n\n{question}\n\n⏳ لديك {AUTO_KICK_TIMEOUT} ثانية، وإلا ستُطرد.",
            reply_markup=reply_markup
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔐 {first_name}، تم إرسال كابتشا إلى خاصك. أجب خلال {AUTO_KICK_TIMEOUT} ثانية."
        )
    except:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔐 {first_name}، أجب على الكابتشا التالية (اكتب الرقم فقط) في المجموعة:\n\n{question}\n\n⏳ لديك {AUTO_KICK_TIMEOUT} ثانية.",
            reply_markup=reply_markup
        )

    job = context.job_queue.run_once(
        callback=kick_if_no_captcha,
        when=AUTO_KICK_TIMEOUT,
        data={"chat_id": chat_id, "user_id": user_id, "first_name": first_name},
        name=f"captcha_{user_id}"
    )
    pending_captcha[user_id]["job"] = job


async def kick_if_no_captcha(context: ContextTypes.DEFAULT_TYPE):
    """طرد العضو إذا لم يجب على الكابتشا خلال المهلة"""
    data = context.job.data
    chat_id = data["chat_id"]
    user_id = data["user_id"]
    first_name = data["first_name"]

    if user_id in pending_captcha:
        try:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⛔ {first_name} تم طرده لعدم إجابة الكابتشا خلال {AUTO_KICK_TIMEOUT} ثانية."
            )
            await send_log(
                bot=context.bot,
                user=telegram.User(id=user_id, first_name=first_name, is_bot=False),
                chat_title="المجموعة",
                deleted_text=f"طرد بسبب عدم إجابة الكابتشا.",
                violation_type="❌ طرد بسبب عدم الموافقة"
            )
        except Exception as e:
            print(f"فشل طرد العضو {user_id}: {e}")
        finally:
            if user_id in pending_captcha:
                del pending_captcha[user_id]


async def refresh_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث الكابتشا عند الضغط على الزر"""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("refresh_captcha_"):
        return
    user_id = int(data.split("_")[2])
    user = query.from_user
    if user.id != user_id:
        await query.edit_message_text("❌ هذا الزر ليس مخصصاً لك.")
        return
    if user_id not in pending_captcha:
        await query.edit_message_text("ℹ️ انتهت مهلة الكابتشا أو تم التحقق مسبقاً.")
        return
    question, new_answer = generate_captcha()
    pending_captcha[user_id]["answer"] = new_answer
    await query.edit_message_text(
        text=f"🔄 تم تحديث الكابتشا:\n\n{question}\n\nأجب بالرقم فقط.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث الكابتشا", callback_data=f"refresh_captcha_{user_id}")]
        ])
    )


async def handle_captcha_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إجابة المستخدم على الكابتشا (رسالة نصية)"""
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    if user_id not in pending_captcha:
        return
    if await is_admin(context.bot, chat_id, user_id):
        return

    data = pending_captcha[user_id]
    correct_answer = data["answer"]
    first_name = data["first_name"]
    original_chat_id = data["chat_id"]

    try:
        await update.message.delete()
    except:
        pass

    try:
        user_answer = int(update.message.text.strip())
    except ValueError:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ يجب إدخال رقم صحيح. حاول مرة أخرى."
        )
        return

    if user_answer == correct_answer:
        # ✅ إجابة صحيحة
        if "job" in data:
            data["job"].schedule_removal()
        del pending_captcha[user_id]

        await context.bot.send_message(
            chat_id=original_chat_id,
            text=f"🎉 أهلاً وسهلاً بك {first_name} في المجموعة! تم التحقق بنجاح ✅"
        )
        await send_log(
            bot=context.bot,
            user=user,
            chat_title=update.effective_chat.title or "المجموعة",
            deleted_text=f"أجاب الكابتشا بشكل صحيح.",
            violation_type="🤖 كابتشا - نجاح"
        )
    else:
        # ❌ إجابة خاطئة
        attempts = data.get("attempts", 0) + 1
        data["attempts"] = attempts
        pending_captcha[user_id] = data

        if attempts >= CAPTCHA_ATTEMPTS:
            # طرد فوري بعد المحاولات الخاطئة
            try:
                await context.bot.ban_chat_member(chat_id=original_chat_id, user_id=user_id)
                await context.bot.send_message(
                    chat_id=original_chat_id,
                    text=f"⛔ {first_name} تم طرده لتكرار الإجابة الخاطئة ({CAPTCHA_ATTEMPTS} محاولات)."
                )
                if "job" in data:
                    data["job"].schedule_removal()
                del pending_captcha[user_id]
                await send_log(
                    bot=context.bot,
                    user=user,
                    chat_title=update.effective_chat.title or "المجموعة",
                    deleted_text=f"طرد بسبب فشل الكابتشا {CAPTCHA_ATTEMPTS} مرات.",
                    violation_type="🤖 كابتشا - فشل"
                )
            except Exception as e:
                print(f"فشل الطرد: {e}")
        else:
            # إرسال كابتشا جديدة
            question, new_answer = generate_captcha()
            data["answer"] = new_answer
            pending_captcha[user_id] = data

            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ إجابة خاطئة. حاول مرة أخرى ({attempts}/{CAPTCHA_ATTEMPTS}):\n\n{question}"
                )
            except:
                await context.bot.send_message(
                    chat_id=original_chat_id,
                    text=f"❌ {first_name} إجابة خاطئة. حاول مرة أخرى ({attempts}/{CAPTCHA_ATTEMPTS}):\n\n{question}"
                )


# ===================== الترحيب والوداع =====================

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج انضمام أعضاء جدد مع كابتشا"""
    chat = update.effective_chat
    chat_title = chat.title or "المجموعة"

    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if bot_member.status not in ["administrator", "creator"]:
            return
    except:
        return

    for new_member in update.message.new_chat_members:
        user = new_member
        if user.id == context.bot.id:
            continue
        if await is_admin(context.bot, chat.id, user.id):
            continue

        # فحص عمر الحساب
        account_age = datetime.now() - user.date
        if account_age.days < MIN_ACCOUNT_AGE_DAYS:
            try:
                await context.bot.ban_chat_member(chat.id, user.id)
                await context.bot.send_message(
                    chat.id,
                    text=f"🛑 {user.first_name} تم طردك لأن حسابك جديد (عمره أقل من {MIN_ACCOUNT_AGE_DAYS} يوم)."
                )
                await send_log(
                    bot=context.bot,
                    user=user,
                    chat_title=chat_title,
                    deleted_text=f"حساب جديد (عمره {account_age.days} يوم) - تم الطرد.",
                    violation_type="🛑 حساب جديد (ممنوع)"
                )
            except Exception as e:
                print(f"فشل طرد حساب جديد: {e}")
            continue

        # إرسال الكابتشا
        await send_captcha(context, chat.id, user.id, user.first_name)
        await send_log(
            bot=context.bot,
            user=user,
            chat_title=chat_title,
            deleted_text=f"انضم العضو. جاري إرسال الكابتشا.",
            violation_type="👋 ترحيب (كابتشا)"
        )


async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج مغادرة الأعضاء"""
    chat = update.effective_chat
    chat_title = chat.title or "المجموعة"
    user = update.message.left_chat_member

    if user.id == context.bot.id:
        return

    await context.bot.send_message(
        chat_id=chat.id,
        text=f"🚪 وداعاً {user.first_name}، نتمنى لك التوفيق! 🤍"
    )

    # حذف من قوائم الانتظار إذا كان موجوداً
    if user.id in pending_captcha:
        job = pending_captcha[user.id].get("job")
        if job:
            job.schedule_removal()
        del pending_captcha[user.id]

    await send_log(
        bot=context.bot,
        user=user,
        chat_title=chat_title,
        deleted_text="غادر العضو المجموعة.",
        violation_type="🚪 مغادرة"
    )


# ===================== أوامر المشرفين =====================

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "🛡️ <b>Raskov Security Bot v6.0</b>\n\n"
        "🔹 <b>القائمة البيضاء</b>: minepi.com, pi.app\n"
        "🔹 <b>مانع التكرار</b>: 5 رسائل / 4 ثوان = كتم 5د\n"
        "🔹 <b>منع الروابط</b>: مفعل ✅\n"
        "🔹 <b>منع الميديا</b>: معطل ❌\n"
        "🔹 <b>منع التوجيه</b>: معطل ❌\n"
        "🔹 <b>الترحيب</b>: كابتشا بشري ✅\n"
        "🔹 <b>حماية الحسابات الجديدة</b>: عمر < {MIN_ACCOUNT_AGE_DAYS} يوم = طرد ❌\n\n"
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

    # إذا كان المستخدم في قائمة انتظار الكابتشا، نمنعه من الكلام
    if user_id in pending_captcha:
        try:
            await update.message.delete()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ {user.first_name}، أنت في مرحلة التحقق البشري. أجب على الكابتشا أولاً."
            )
        except:
            pass
        return

    # فحص التكرار
    if await check_flood(update, context):
        return

    # التحقق من المشرفين
    if await is_admin(context.bot, chat_id, user_id):
        return

    # ====== فحص الميديا ======
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

    # ====== فحص الرسائل المعاد توجيهها ======
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

    # ====== فحص النص ======
    if not update.message.text:
        return

    original_text = update.message.text
    cleaned_text = clean_obfuscated_text(original_text)

    is_violation = False
    violation_type = "رابط غير مسموح"

    if WALLET_PATTERN.search(cleaned_text):
        is_violation = True
        violation_type = "محفظة رقمية"
    elif not is_violation and PHONE_PATTERN.search(cleaned_text):
        is_violation = True
        violation_type = "رقم هاتف"
    elif not is_violation and LOCK_LINKS and LINK_PATTERN.search(cleaned_text):
        is_allowed = any(domain in cleaned_text.lower() for domain in ALLOWED_DOMAINS)
        if not is_allowed:
            is_violation = True
            violation_type = "رابط غير مسموح" if original_text == cleaned_text else "رابط غير مسموح (ملتف)"

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
            deleted_text=original_text,
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
                # إعادة تعيين المخالفات بعد الحظر (اختياري)
                if user_id in warnings_db:
                    del warnings_db[user_id]
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

    # معالج الترحيب (انضمام أعضاء جدد)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    # معالج الوداع (مغادرة أعضاء)
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))

    # معالج الكابتشا (يستمع للرسائل النصية)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_captcha_answer))

    # معالج أزرار الكابتشا
    app.add_handler(CallbackQueryHandler(refresh_captcha, pattern="^refresh_captcha_"))

    # معالج جميع الرسائل (يأتي أخيراً)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, anti_link))

    print("🤖 البوت يعمل الآن مع الكابتشا وحماية الحسابات الجديدة...")
    app.run_polling()


if __name__ == "__main__":
    main()
