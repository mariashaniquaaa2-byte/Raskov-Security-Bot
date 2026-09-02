import os
import re
from datetime import datetime, timedelta

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ============================================================
# RASKOV SECURITY BOT V5.1
# ============================================================

# ===================== إعدادات البيئة =====================

TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

# ===================== القائمة البيضاء =====================

ALLOWED_DOMAINS = [
    "minepi.com",
    "pi.app"
]

# ===================== إعدادات مانع التكرار =====================

FLOOD_LIMIT = 5
FLOOD_TIME = 4
MUTE_DURATION = 5

# ===================== إعدادات الحماية =====================

LOCK_LINKS = True
LOCK_MEDIA = False
LOCK_FORWARD = False

# ===================== شروط المجموعة =====================

REQUIRE_TERMS_ACCEPTANCE = True

TERMS_TEXT = (
    "📜 <b>شروط المجموعة</b>\n\n"
    "يرجى قراءة الشروط والموافقة عليها قبل المشاركة في المجموعة:\n\n"

    "1️⃣ يمنع نشر الروابط غير المسموح بها.\n"
    "2️⃣ يمنع نشر المحتوى المخالف أو الاحتيالي.\n"
    "3️⃣ يمنع إرسال الإعلانات والرسائل المزعجة.\n"
    "4️⃣ يمنع نشر أرقام الهاتف أو المحافظ الرقمية بشكل مخالف.\n"
    "5️⃣ يمنع الإساءة أو المضايقة أو انتحال الشخصية.\n"
    "6️⃣ يجب احترام أعضاء المجموعة والمشرفين.\n\n"

    "بالضغط على «أوافق على الشروط» أنت تؤكد موافقتك على هذه القواعد."
)

# ===================== الأنماط =====================

LINK_PATTERN = re.compile(
    r"(https?://|www\.|t\.me/|telegram\.me/|"
    r"[a-zA-Z0-9-]+\.(com|net|org|io|app|xyz|me|co))",
    re.IGNORECASE
)

WALLET_PATTERN = re.compile(
    r"\b(0x[a-fA-F0-9]{40})\b",
    re.IGNORECASE
)

PHONE_PATTERN = re.compile(
    r"(?<![a-zA-Z])(\+?\d{7,15})(?![a-zA-Z])"
)

# ===================== التخزين المؤقت =====================

warnings_db = {}
user_messages = {}

# المستخدمون الذين وافقوا على الشروط
accepted_terms = set()


# ============================================================
# دوال المساعدة
# ============================================================

async def is_admin(bot, chat_id, user_id):
    try:
        member = await bot.get_chat_member(
            chat_id,
            user_id
        )

        return member.status in [
            "administrator",
            "creator"
        ]

    except Exception:
        return False


def clean_obfuscated_text(text: str) -> str:

    cleaned = re.sub(
        r'\s+',
        '',
        text
    )

    cleaned = re.sub(
        r'dot',
        '.',
        cleaned,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(
        r'at',
        '@',
        cleaned,
        flags=re.IGNORECASE
    )

    replacements = {
        '0': 'o',
        '1': 'i',
        '3': 'e',
        '4': 'a',
        '5': 's',
        '7': 't',
        '@': 'a',
        '¢': 'c',
        '₿': 'b'
    }

    for old, new in replacements.items():
        cleaned = cleaned.replace(
            old,
            new
        )

    cleaned = re.sub(
        r'hxxps?',
        'https',
        cleaned,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(
        r'hxxp',
        'http',
        cleaned,
        flags=re.IGNORECASE
    )

    return cleaned


async def send_log(
    bot,
    user,
    chat_title,
    deleted_text,
    violation_type="رابط"
):

    if not LOG_CHANNEL_ID:
        return

    time_now = datetime.now().strftime(
        "%I:%M %p - %d/%m/%Y"
    )

    emoji_map = {
        "رابط غير مسموح": "🚫",
        "رابط غير مسموح (ملتف)": "🚫",
        "رقم هاتف": "📞",
        "محفظة رقمية": "💰",
        "⏳ سبام (تكرار)": "⏳",
        "🖼️ صورة/فيديو (ممنوع)": "🖼️",
        "↩️ رسالة معاد توجيهها (ممنوع)": "↩️",
        "⚠️ إدارة (حظر)": "🔨",
        "⚠️ إدارة (فك حظر)": "🔓",
        "🔄 إعادة تعيين مخالفات": "🔄",
        "قبول الشروط": "✅",
        "❌ رفض الشروط": "❌",
        "عضو جديد": "👤",
    }

    emoji = emoji_map.get(
        violation_type,
        "⚠️"
    )

    first_name = (
        user.first_name
        or "غير معروف"
    )

    log_message = (
        f"🕒 {time_now}\n"
        f"{emoji} <b>{violation_type}</b>\n"
        f"👤 المستخدم: {first_name}\n"
        f"🆔 معرفه: <code>{user.id}</code>\n"
        f"🏠 المجموعة: {chat_title}\n"
        f"📝 التفاصيل:\n"
        f"<code>{deleted_text[:150]}</code>"
    )

    try:

        await bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=log_message,
            parse_mode="HTML"
        )

    except Exception as e:

        print(
            f"❌ فشل إرسال اللوج: {e}"
        )


async def mute_user(
    bot,
    chat_id,
    user_id,
    duration_minutes
):

    try:

        until_date = (
            datetime.now()
            + timedelta(
                minutes=duration_minutes
            )
        )

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False
            ),
            until_date=until_date
        )

        return True

    except Exception as e:

        print(
            f"❌ فشل الكتم: {e}"
        )

        return False


# ============================================================
# نظام قبول الشروط
# ============================================================

async def restrict_new_member(
    bot,
    chat_id,
    user_id
):

    try:

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
                can_manage_topics=False,
            )
        )

        return True

    except Exception as e:

        print(
            f"❌ فشل تقييد العضو الجديد: {e}"
        )

        return False


async def restore_member_permissions(
    bot,
    chat_id,
    user_id
):

    try:

        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
                can_manage_topics=True,
            )
        )

        return True

    except Exception as e:

        print(
            f"❌ فشل إعادة صلاحيات العضو: {e}"
        )

        return False


async def new_member_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.chat_member:
        return

    member_update = update.chat_member

    old_status = (
        member_update
        .old_chat_member
        .status
    )

    new_status = (
        member_update
        .new_chat_member
        .status
    )

    joined_statuses = [
        "member",
        "restricted"
    ]

    if new_status not in joined_statuses:
        return

    if old_status in joined_statuses:
        return

    user = (
        member_update
        .new_chat_member
        .user
    )

    chat = update.effective_chat

    if user.is_bot:
        return

    user_id = user.id
    chat_id = chat.id

    if not REQUIRE_TERMS_ACCEPTANCE:
        return

    # المشرفون لا يحتاجون للموافقة
    if await is_admin(
        context.bot,
        chat_id,
        user_id
    ):

        accepted_terms.add(
            (chat_id, user_id)
        )

        return

    await restrict_new_member(
        context.bot,
        chat_id,
        user_id
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ أوافق على الشروط",
                callback_data=(
                    f"accept_terms:"
                    f"{chat_id}:"
                    f"{user_id}"
                )
            )
        ],
        [
            InlineKeyboardButton(
                "❌ لا أوافق",
                callback_data=(
                    f"reject_terms:"
                    f"{chat_id}:"
                    f"{user_id}"
                )
            )
        ]
    ])

    try:

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"👋 مرحبًا "
                f"<b>{user.first_name}</b>!\n\n"
                f"{TERMS_TEXT}\n\n"
                "👇 اختر أحد الخيارات:"
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )

        await send_log(
            bot=context.bot,
            user=user,
            chat_title=(
                chat.title
                or "المجموعة"
            ),
            deleted_text=(
                "عضو جديد - "
                "تم طلب قبول شروط المجموعة"
            ),
            violation_type="عضو جديد"
        )

    except Exception as e:

        print(
            f"❌ فشل إرسال شروط المجموعة: {e}"
        )


# ============================================================
# معالجة قبول الشروط
# ============================================================

async def terms_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data or ""

    parts = data.split(":")

    if len(parts) != 3:

        await query.answer()

        return

    action = parts[0]

    try:

        chat_id = int(parts[1])
        target_user_id = int(parts[2])

    except ValueError:

        await query.answer()

        return

    user = query.from_user

    if user.id != target_user_id:

        await query.answer(
            "❌ هذا الزر مخصص للعضو الجديد فقط.",
            show_alert=True
        )

        return

    await query.answer()

    chat = await context.bot.get_chat(
        chat_id
    )

    if action == "accept_terms":

        accepted_terms.add(
            (chat_id, user.id)
        )

        success = await restore_member_permissions(
            context.bot,
            chat_id,
            user.id
        )

        if success:

            await query.edit_message_text(
                "✅ <b>تم قبول الشروط بنجاح!</b>\n\n"
                "🎉 يمكنك الآن المشاركة في المجموعة.\n"
                "🛡️ نتمنى لك وقتًا ممتعًا.",
                parse_mode="HTML"
            )

            await send_log(
                bot=context.bot,
                user=user,
                chat_title=(
                    chat.title
                    or "المجموعة"
                ),
                deleted_text=(
                    "وافق العضو على شروط المجموعة."
                ),
                violation_type="قبول الشروط"
            )

        else:

            await query.edit_message_text(
                "⚠️ تمت الموافقة، لكن حدث خطأ "
                "أثناء إعادة صلاحيات الكتابة.\n"
                "يرجى التواصل مع أحد المشرفين."
            )

    elif action == "reject_terms":

        await query.edit_message_text(
            "❌ <b>لم تتم الموافقة على شروط المجموعة.</b>\n\n"
            "لن تتمكن من المشاركة حتى توافق على الشروط.",
            parse_mode="HTML"
        )

        await send_log(
            bot=context.bot,
            user=user,
            chat_title=(
                chat.title
                or "المجموعة"
            ),
            deleted_text=(
                "رفض العضو شروط المجموعة."
            ),
            violation_type="❌ رفض الشروط"
        )


# ============================================================
# مانع التكرار
# ============================================================

async def check_flood(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> bool:

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    now = datetime.now()

    if await is_admin(
        context.bot,
        chat_id,
        user_id
    ):
        return False

    if user_id not in user_messages:

        user_messages[user_id] = []

    user_messages[user_id].append(
        now
    )

    cutoff = (
        now
        - timedelta(
            seconds=FLOOD_TIME
        )
    )

    user_messages[user_id] = [
        t
        for t in user_messages[user_id]
        if t > cutoff
    ]

    if (
        len(user_messages[user_id])
        > FLOOD_LIMIT
    ):

        success = await mute_user(
            context.bot,
            chat_id,
            user_id,
            MUTE_DURATION
        )

        if success:

            await send_log(
                bot=context.bot,
                user=update.effective_user,
                chat_title=(
                    update.effective_chat.title
                    or "المجموعة"
                ),
                deleted_text=(
                    f"كتم لمدة "
                    f"{MUTE_DURATION} دقائق "
                    f"(تكرار: "
                    f"{len(user_messages[user_id])} "
                    f"رسائل في "
                    f"{FLOOD_TIME} ثوانٍ)."
                ),
                violation_type=(
                    "⏳ سبام (تكرار)"
                )
            )

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🔇 "
                    f"{update.effective_user.first_name} "
                    f"تم كتمه "
                    f"{MUTE_DURATION} دقائق "
                    "للتكرار السريع."
                )
            )

        try:

            await update.message.delete()

        except Exception:
            pass

        return True

    return False


# ============================================================
# أوامر المشرفين
# ============================================================

async def ban_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(
        context.bot,
        chat_id,
        user_id
    ):

        await update.message.reply_text(
            "❌ هذا الأمر للمشرفين فقط."
        )

        return

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "⚠️ قم بالرد على رسالة العضو المستهدف."
        )

        return

    target = (
        update
        .message
        .reply_to_message
        .from_user
    )

    target_id = target.id

    if await is_admin(
        context.bot,
        chat_id,
        target_id
    ):

        await update.message.reply_text(
            "❌ لا يمكنك حظر مشرف."
        )

        return

    try:

        await context.bot.ban_chat_member(
            chat_id=chat_id,
            user_id=target_id
        )

        await update.message.reply_text(
            f"✅ تم حظر {target.first_name}."
        )

        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=(
                update.effective_chat.title
                or "المجموعة"
            ),
            deleted_text=(
                f"قام "
                f"{update.effective_user.first_name} "
                f"بحظر "
                f"{target.first_name} "
                f"(ID: {target_id})"
            ),
            violation_type="⚠️ إدارة (حظر)"
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ فشل الحظر: {e}"
        )


async def unban_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(
        context.bot,
        chat_id,
        user_id
    ):

        await update.message.reply_text(
            "❌ هذا الأمر للمشرفين فقط."
        )

        return

    args = context.args

    if not args:

        await update.message.reply_text(
            "⚠️ استخدم: /unban [معرف المستخدم]"
        )

        return

    try:

        target_id = int(
            args[0]
        )

        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=target_id
        )

        await update.message.reply_text(
            f"✅ تم فك الحظر عن {target_id}."
        )

        await send_log(
            bot=context.bot,
            user=update.effective_user,
            chat_title=(
                update.effective_chat.title
                or "المجموعة"
            ),
            deleted_text=(
                f"قام "
                f"{update.effective_user.first_name} "
                f"بفك الحظر عن {target_id}"
            ),
            violation_type=(
                "⚠️ إدارة (فك حظر)"
            )
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ فشل فك الحظر: {e}"
        )


async def reset_warnings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(
        context.bot,
        chat_id,
        user_id
    ):

        await update.message.reply_text(
            "❌ هذا الأمر للمشرفين فقط."
        )

        return

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "⚠️ قم بالرد على رسالة العضو المستهدف."
        )

        return

    target = (
        update
        .message
        .reply_to_message
        .from_user
    )

    target_id = target.id

    if target_id in warnings_db:

        del warnings_db[target_id]

    await update.message.reply_text(
        f"✅ تم إعادة تعيين مخالفات "
        f"{target.first_name}."
    )

    await send_log(
        bot=context.bot,
        user=update.effective_user,
        chat_title=(
            update.effective_chat.title
            or "المجموعة"
        ),
        deleted_text=(
            f"قام "
            f"{update.effective_user.first_name} "
            f"بإعادة تعيين مخالفات "
            f"{target.first_name} "
            f"(ID: {target_id})"
        ),
        violation_type=(
            "🔄 إعادة تعيين مخالفات"
        )
    )


async def toggle_lock_links(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global LOCK_LINKS

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if not await is_admin(
        context.bot,
        chat_id,
        user_id
    ):

        await update.message.reply_text(
            "❌ هذا الأمر للمشرفين فقط."
        )

        return

    LOCK_LINKS = not LOCK_LINKS

    status = (
        "مفعل ✅"
        if LOCK_LINKS
        else "معطل ❌"
    )

    await update.message.reply_text(
        f"🔗 منع الروابط: {status}"
    )


async def toggle_lock_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global LOCK_MEDIA

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

   
