import os
import re
import time
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

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

from supabase import create_client, Client


# ============================================================
# RASKOV SECURITY BOT V6.0
# Professional Telegram Security & Moderation System
# ============================================================


# ============================================================
# ENVIRONMENT
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

RENDER_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://raskov-security-bot.onrender.com"
)

PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_PATH = f"telegram/{TOKEN}" if TOKEN else "telegram/webhook"


if not TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL is missing")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY is missing")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("RASKOV")


# ============================================================
# SUPABASE
# ============================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# MEMORY CACHE
# ============================================================

flood_tracker = defaultdict(deque)

raid_tracker = defaultdict(deque)

# Temporary cache to reduce database requests
settings_cache = {}

SETTINGS_CACHE_SECONDS = 30


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_SETTINGS = {
    "lock_links": True,
    "lock_media": False,
    "lock_forward": False,
    "lock_ads": True,
    "lock_wallets": True,
    "lock_phone_numbers": False,

    "anti_spam": True,
    "flood_limit": 5,
    "flood_window": 4,
    "flood_mute_minutes": 5,

    "anti_raid": True,
    "raid_join_limit": 10,
    "raid_window_seconds": 60,
    "raid_lock_minutes": 10,

    "require_terms": True,

    "max_warnings": 3,
    "warning_mute_minutes": 10,

    "welcome_enabled": True,

    "security_score": 100,
}


# ============================================================
# PATTERNS
# ============================================================

URL_PATTERN = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s]+"
    r"|\b(?:t\.me|telegram\.me|discord\.gg|discord\.com/invite)/[^\s]+"
)

DOMAIN_PATTERN = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?([a-z0-9.-]+\.[a-z]{2,})(?:/[^\s]*)?"
)

WALLET_PATTERN = re.compile(
    r"\b0x[a-fA-F0-9]{40}\b"
)

SOLANA_PATTERN = re.compile(
    r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"
)

PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)"
)

OBFUSCATED_PATTERN = re.compile(
    r"(?i)"
    r"(https?\s*:\s*/\s*/|"
    r"www\s*\.\s*|"
    r"\b(?:dot|point)\b|"
    r"\[\s*dot\s*\]|\(\s*dot\s*\)"
)

SCAM_KEYWORDS = [
    "send crypto",
    "send usdt",
    "send pi",
    "double your",
    "double pi",
    "double crypto",
    "free crypto",
    "free pi",
    "giveaway",
    "airdrop",
    "claim reward",
    "wallet verification",
    "verify wallet",
    "connect wallet",
    "seed phrase",
    "recovery phrase",
    "private key",
    "mnemonic",
    "investment guaranteed",
    "guaranteed profit",
    "profit guaranteed",

    "أرسل pi",
    "ارسل pi",
    "ضاعف",
    "ربح مضمون",
    "استثمار مضمون",
    "عبارة الاسترداد",
    "المفتاح الخاص",
    "تحقق من محفظتك",
    "اربط محفظتك",
    "ارسل العملات",
]

AD_KEYWORDS = [
    "promo",
    "promotion",
    "advertisement",
    "advertising",
    "buy now",
    "sale",
    "discount",
    "contact me",
    "dm me",
    "join my",
    "subscribe",
    "visit my",
    "marketing",

    "إعلان",
    "اعلان",
    "تخفيض",
    "خصم",
    "تواصل معي",
    "راسلني",
    "اشترك",
    "عرض خاص",
    "للبيع",
]


# ============================================================
# UTILITY
# ============================================================

def now_ts():
    return int(time.time())


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u200b", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")
    text = text.replace("\ufeff", "")

    text = re.sub(r"[\u2060-\u2064]", "", text)

    return text.strip()


def normalize_text(text: str) -> str:
    text = clean_text(text).lower()

    replacements = {
        "dot": ".",
        "[.]": ".",
        "(.)": ".",
        " point ": ".",
        " : ": ":",
        " / ": "/",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def get_user_display(user):
    if not user:
        return "Unknown"

    if user.username:
        return f"@{user.username}"

    return user.full_name or str(user.id)


# ============================================================
# SUPABASE HELPERS
# ============================================================

def get_group(chat_id, chat_title=None, chat_username=None):
    try:
        result = (
            supabase
            .table("groups")
            .select("*")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

        data = {
            "chat_id": chat_id,
            "chat_title": chat_title or "",
            "chat_username": chat_username or "",
            **DEFAULT_SETTINGS,
        }

        result = (
            supabase
            .table("groups")
            .insert(data)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:
        logger.exception("get_group error: %s", e)

    return {
        "chat_id": chat_id,
        "chat_title": chat_title or "",
        "chat_username": chat_username or "",
        **DEFAULT_SETTINGS,
    }


def get_settings(chat):
    chat_id = chat.id
    current = now_ts()

    cached = settings_cache.get(chat_id)

    if cached:
        timestamp, settings = cached

        if current - timestamp < SETTINGS_CACHE_SECONDS:
            return settings

    settings = get_group(
        chat_id,
        getattr(chat, "title", ""),
        getattr(chat, "username", ""),
    )

    settings_cache[chat_id] = (
        current,
        settings
    )

    return settings


def update_setting(chat_id, key, value):
    try:
        (
            supabase
            .table("groups")
            .update({
                key: value,
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
            .eq("chat_id", chat_id)
            .execute()
        )

        settings_cache.pop(chat_id, None)

        return True

    except Exception as e:
        logger.exception("update_setting error: %s", e)
        return False


def ensure_member(chat_id, user):
    if not user:
        return

    try:
        (
            supabase
            .table("members")
            .upsert(
                {
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "last_seen_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="chat_id,user_id"
            )
            .execute()
        )

    except Exception as e:
        logger.warning("ensure_member error: %s", e)


def get_member(chat_id, user_id):
    try:
        result = (
            supabase
            .table("members")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:
        logger.warning("get_member error: %s", e)

    return None


# ============================================================
# STATISTICS
# ============================================================

def increment_stats(chat_id, field, amount=1):
    try:
        today = datetime.now(timezone.utc).date().isoformat()

        result = (
            supabase
            .table("statistics")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("stat_date", today)
            .limit(1)
            .execute()
        )

        if result.data:
            row = result.data[0]

            current = int(row.get(field, 0))

            (
                supabase
                .table("statistics")
                .update({
                    field: current + amount,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                })
                .eq("id", row["id"])
                .execute()
            )

        else:
            data = {
                "chat_id": chat_id,
                "stat_date": today,
                field: amount,
            }

            (
                supabase
                .table("statistics")
                .insert(data)
                .execute()
            )

    except Exception as e:
        logger.warning("increment_stats error: %s", e)


def update_group_counter(chat_id, field, amount=1):
    try:
        result = (
            supabase
            .table("groups")
            .select(field)
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )

        if result.data:
            current = int(result.data[0].get(field, 0))

            (
                supabase
                .table("groups")
                .update({
                    field: current + amount
                })
                .eq("chat_id", chat_id)
                .execute()
            )

    except Exception as e:
        logger.warning("update_group_counter error: %s", e)


# ============================================================
# SECURITY EVENTS
# ============================================================

def log_security_event(
    chat_id,
    event_type,
    user_id=None,
    severity="medium",
    message_id=None,
    details=None,
):
    try:
        (
            supabase
            .table("security_events")
            .insert(
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "event_type": event_type,
                    "severity": severity,
                    "message_id": message_id,
                    "details": details or {},
                }
            )
            .execute()
        )

    except Exception as e:
        logger.warning("log_security_event error: %s", e)


# ============================================================
# LOG CHANNEL
# ============================================================

async def send_log(
    context,
    text,
):
    if not LOG_CHANNEL_ID:
        return

    try:
        await context.bot.send_message(
            chat_id=int(LOG_CHANNEL_ID),
            text=text,
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.warning("Log channel error: %s", e)


# ============================================================
# ADMIN CHECK
# ============================================================

async def is_admin(update, context):
    if not update.effective_chat or not update.effective_user:
        return False

    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id,
        )

        return member.status in (
            "administrator",
            "creator",
        )

    except Exception as e:
        logger.warning("is_admin error: %s", e)
        return False


async def is_user_admin(context, chat_id, user_id):
    try:
        member = await context.bot.get_chat_member(
            chat_id,
            user_id,
        )

        return member.status in (
            "administrator",
            "creator",
        )

    except Exception:
        return False


# ============================================================
# RESTRICT / UNRESTRICT
# ============================================================

async def mute_user(
    context,
    chat_id,
    user_id,
    minutes,
):
    try:
        permissions = ChatPermissions(
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
        )

        until_date = int(time.time()) + (minutes * 60)

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
        )

        return True

    except Exception as e:
        logger.warning("mute_user error: %s", e)
        return False


async def unmute_user(
    context,
    chat_id,
    user_id,
):
    try:
        permissions = ChatPermissions(
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
        )

        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
        )

        return True

    except Exception as e:
        logger.warning("unmute_user error: %s", e)
        return False


# ============================================================
# WARNINGS
# ============================================================

async def add_warning(
    context,
    chat_id,
    user_id,
    reason,
    message_id=None,
):
    try:
        member = get_member(chat_id, user_id)

        current_warnings = 0

        if member:
            current_warnings = int(member.get("warnings", 0))

        new_warnings = current_warnings + 1

        settings = get_settings(
            await context.bot.get_chat(chat_id)
        )

        max_warnings = int(
            settings.get("max_warnings", 3)
        )

        (
            supabase
            .table("members")
            .upsert(
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "warnings": new_warnings,
                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                },
                on_conflict="chat_id,user_id"
            )
            .execute()
        )

        (
            supabase
            .table("warnings")
            .insert(
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "reason": reason,
                    "message_id": message_id,
                    "action": "warning",
                }
            )
            .execute()
        )

        increment_stats(
            chat_id,
            "warnings",
        )

        update_group_counter(
            chat_id,
            "total_warnings",
        )

        if new_warnings >= max_warnings:
            mute_minutes = int(
                settings.get(
                    "warning_mute_minutes",
                    10
                )
            )

            await mute_user(
                context,
                chat_id,
                user_id,
                mute_minutes,
            )

            (
                supabase
                .table("members")
                .update(
                    {
                        "is_muted": True
                    }
                )
                .eq("chat_id", chat_id)
                .eq("user_id", user_id)
                .execute()
            )

            update_group_counter(
                chat_id,
                "total_mutes",
            )

            return new_warnings, True

        return new_warnings, False

    except Exception as e:
        logger.exception("add_warning error: %s", e)
        return 0, False


# ============================================================
# CONTENT DETECTION
# ============================================================

def contains_link(text):
    if not text:
        return False

    normalized = normalize_text(text)

    return bool(
        URL_PATTERN.search(normalized)
        or OBFUSCATED_PATTERN.search(normalized)
    )


def extract_domains(text):
    if not text:
        return []

    normalized = normalize_text(text)

    return [
        match.group(1).lower()
        for match in DOMAIN_PATTERN.finditer(normalized)
    ]


def is_whitelisted_domain(domain, whitelist):
    domain = domain.lower().strip()

    default_allowed = [
        "minepi.com",
        "pi.app",
    ]

    allowed = default_allowed + whitelist

    for item in allowed:
        item = item.lower().strip()

        if domain == item or domain.endswith("." + item):
            return True

    return False


def contains_wallet(text):
    if not text:
        return False

    return bool(
        WALLET_PATTERN.search(text)
        or (
            len(text) < 1000
            and SOLANA_PATTERN.search(text)
        )
    )


def contains_phone(text):
    if not text:
        return False

    matches = PHONE_PATTERN.findall(text)

    for match in matches:
        digits = re.sub(r"\D", "", match)

        if 8 <= len(digits) <= 15:
            return True

    return False


def contains_scam(text):
    if not text:
        return False

    normalized = normalize_text(text)

    return any(
        keyword.lower() in normalized
        for keyword in SCAM_KEYWORDS
    )


def contains_ad(text):
    if not text:
        return False

    normalized = normalize_text(text)

    return any(
        keyword.lower() in normalized
        for keyword in AD_KEYWORDS
    )


def contains_media(message):
    return any(
        [
            bool(message.photo),
            bool(message.video),
            bool(message.audio),
            bool(message.document),
            bool(message.animation),
            bool(message.voice),
            bool(message.video_note),
            bool(message.sticker),
        ]
    )


def is_forwarded(message):
    if not message:
        return False

    if getattr(message, "forward_origin", None):
        return True

    # Compatibility with older Telegram/PTB versions
    if getattr(message, "forward_date", None):
        return True

    return False


# ============================================================
# WHITELIST
# ============================================================

def get_whitelist(chat_id):
    try:
        result = (
            supabase
            .table("whitelist_domains")
            .select("domain")
            .eq("chat_id", chat_id)
            .execute()
        )

        return [
            row["domain"]
            for row in (result.data or [])
        ]

    except Exception:
        return []


# ============================================================
# SECURITY SCORE
# ============================================================

def calculate_security_score(settings):
    score = 0

    if settings.get("lock_links"):
        score += 15

    if settings.get("lock_ads"):
        score += 10

    if settings.get("lock_wallets"):
        score += 10

    if settings.get("anti_spam"):
        score += 15

    if settings.get("anti_raid"):
        score += 15

    if settings.get("lock_forward"):
        score += 10

    if settings.get("lock_media"):
        score += 5

    if settings.get("lock_phone_numbers"):
        score += 5

    if settings.get("require_terms"):
        score += 10

    if score > 100:
        score = 100

    return score


def security_level(score):
    if score >= 85:
        return "🟢 ممتاز"

    if score >= 70:
        return "🟡 جيد"

    if score >= 50:
        return "🟠 متوسط"

    return "🔴 ضعيف"


# ============================================================
# UPDATE SECURITY SCORE
# ============================================================

def save_security_score(chat_id, settings):
    score = calculate_security_score(settings)

    try:
        (
            supabase
            .table("groups")
            .update({
                "security_score": score
            })
            .eq("chat_id", chat_id)
            .execute()
        )

    except Exception:
        pass

    return score


# ============================================================
# RAID SYSTEM
# ============================================================

async def process_new_member(update, context):
    chat_member = update.chat_member

    if not chat_member:
        return

    chat = chat_member.chat

    old_status = chat_member.old_chat_member.status
    new_status = chat_member.new_chat_member.status

    # Only new joins
    joined = (
        old_status in ("left", "kicked")
        and new_status in (
            "member",
            "restricted",
        )
    )

    if not joined:
        return

    user = chat_member.new_chat_member.user

    settings = get_settings(chat)

    ensure_member(
        chat.id,
        user,
    )

    update_group_counter(
        chat.id,
        "total_joins",
    )

    increment_stats(
        chat.id,
        "joins",
    )

    # --------------------------------------------------------
    # Anti-Raid
    # --------------------------------------------------------

    if settings.get("anti_raid", True):

        current = time.time()

        tracker = raid_tracker[chat.id]

        tracker.append(current)

        window = int(
            settings.get(
                "raid_window_seconds",
                60
            )
        )

        while tracker and (
            current - tracker[0] > window
        ):
            tracker.popleft()

        limit = int(
            settings.get(
                "raid_join_limit",
                10
            )
        )

        if len(tracker) >= limit:

            update_group_counter(
                chat.id,
                "total_raid_events",
            )

            increment_stats(
                chat.id,
                "raid_events",
            )

            log_security_event(
                chat.id,
                "anti_raid_triggered",
                severity="high",
                details={
                    "join_count": len(tracker),
                    "window_seconds": window,
                },
            )

            await send_log(
                context,
                (
                    "🚨 RASKOV ANTI-RAID\n\n"
                    f"Group: {chat.title}\n"
                    f"Joins detected: {len(tracker)}\n"
                    f"Window: {window}s\n"
                    "Status: PROTECTION TRIGGERED"
                )
            )

            # Restrict the new member
            raid_minutes = int(
                settings.get(
                    "raid_lock_minutes",
                    10
                )
            )

            await mute_user(
                context,
                chat.id,
                user.id,
                raid_minutes,
            )

    # --------------------------------------------------------
    # Terms
    # --------------------------------------------------------

    if settings.get("require_terms", True):

        try:
            permissions = ChatPermissions(
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
            )

            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=permissions,
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ أوافق على الشروط",
                            callback_data=f"terms_accept:{chat.id}:{user.id}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ لا أوافق",
                            callback_data=f"terms_reject:{chat.id}:{user.id}",
                        )
                    ],
                ]
            )

            terms = settings.get(
                "terms_text",
                "📜 يرجى الموافقة على شروط المجموعة."
            )

            welcome = (
                f"👋 مرحبًا {get_user_display(user)}\n\n"
                f"{terms}\n\n"
                "👇 اختر أحد الخيارات:"
            )

            await context.bot.send_message(
                chat.id,
                welcome,
                reply_markup=keyboard,
            )

        except Exception as e:
            logger.warning(
                "Terms restriction error: %s",
                e
            )

    # --------------------------------------------------------
    # Welcome
    # --------------------------------------------------------

    elif settings.get("welcome_enabled", True):

        try:
            template = settings.get(
                "welcome_text",
                "👋 مرحبًا بك {name} في {group}!"
            )

            text = template.replace(
                "{name}",
                get_user_display(user)
            ).replace(
                "{group}",
                chat.title or "المجموعة"
            )

            await context.bot.send_message(
                chat.id,
                text,
            )

        except Exception:
            pass


# ============================================================
# TERMS CALLBACK
# ============================================================

async def terms_callback(update, context):
    query = update.callback_query

    await query.answer()

    data = query.data

    parts = data.split(":")

    if len(parts) != 3:
        return

    action = parts[0]

    try:
        chat_id = int(parts[1])
        target_user_id = int(parts[2])
    except ValueError:
        return

    user = query.from_user

    # Only the member concerned can accept
    if user.id != target_user_id:

        await query.answer(
            "❌ هذا الزر مخصص للعضو الجديد فقط.",
            show_alert=True,
        )

        return

    if action == "terms_accept":

        await unmute_user(
            context,
            chat_id,
            user.id,
        )

        try:
            (
                supabase
                .table("members")
                .upsert(
                    {
                        "chat_id": chat_id,
                        "user_id": user.id,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "terms_accepted": True,
                        "terms_accepted_at": datetime.now(
                            timezone.utc
                        ).isoformat(),
                    },
                    on_conflict="chat_id,user_id"
                )
                .execute()
            )

        except Exception as e:
            logger.warning(
                "terms_accept DB error: %s",
                e
            )

        try:
            await query.edit_message_text(
                "✅ تم قبول الشروط.\n\n"
                "🛡️ Raskov Security Bot يحمي المجموعة.\n"
                "يمكنك الآن المشاركة."
            )
        except Exception:
            pass

        await send_log(
            context,
            (
                "✅ TERMS ACCEPTED\n\n"
                f"User: {get_user_display(user)}\n"
                f"ID: {user.id}\n"
                f"Chat ID: {chat_id}"
            )
        )

    elif action == "terms_reject":

        try:
            await query.edit_message_text(
                "❌ لم يتم قبول الشروط.\n"
                "يمكنك مغادرة المجموعة إذا كنت لا توافق."
            )
        except Exception:
            pass


# ============================================================
# MESSAGE MODERATION
# ============================================================

async def moderate_message(update, context):
    message = update.message

    if not message:
        return

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    # Ignore private chats
    if chat.type not in (
        "group",
        "supergroup",
    ):
        return

    ensure_member(
        chat.id,
        user,
    )

    settings = get_settings(chat)

    # --------------------------------------------------------
    # Admin bypass
    # --------------------------------------------------------

    if await is_user_admin(
        context,
        chat.id,
        user.id,
    ):
        return

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    increment_stats(
        chat.id,
        "messages",
    )

    update_group_counter(
        chat.id,
        "total_messages",
    )

    text = message.text or message.caption or ""

    clean = clean_text(text)

    # --------------------------------------------------------
    # Anti-Flood
    # --------------------------------------------------------

    if settings.get("anti_spam", True):

        current = time.time()

        key = (
            chat.id,
            user.id,
        )

        tracker = flood_tracker[key]

        tracker.append(current)

        window = int(
            settings.get(
                "flood_window",
                4
            )
        )

        limit = int(
            settings.get(
                "flood_limit",
                5
            )
        )

        while tracker and (
            current - tracker[0] > window
        ):
            tracker.popleft()

        if len(tracker) > limit:

            mute_minutes = int(
                settings.get(
                    "flood_mute_minutes",
                    5
                )
            )

            try:
                await message.delete()
            except Exception:
                pass

            await mute_user(
                context,
                chat.id,
                user.id,
                mute_minutes,
            )

            increment_stats(
                chat.id,
                "spam_blocked",
            )

            increment_stats(
                chat.id,
                "deleted_messages",
            )

            update_group_counter(
                chat.id,
                "total_deleted_messages"
                if False else "deleted_messages"
            )

            log_security_event(
                chat.id,
                "anti_spam",
                user.id,
                severity="high",
                message_id=message.message_id,
                details={
                    "message_count": len(tracker),
                    "window": window,
                },
            )

            await send_log(
                context,
                (
                    "🌊 RASKOV ANTI-SPAM\n\n"
                    f"User: {get_user_display(user)}\n"
                    f"ID: {user.id}\n"
                    f"Action: MUTE {mute_minutes} min\n"
                    f"Messages: {len(tracker)}"
                )
            )

            tracker.clear()

            return

    # --------------------------------------------------------
    # Media Lock
    # --------------------------------------------------------

    if (
        settings.get("lock_media", False)
        and contains_media(message)
    ):

        try:
            await message.delete()
        except Exception:
            pass

        increment_stats(
            chat.id,
            "deleted_messages",
        )

        log_security_event(
            chat.id,
            "media_blocked",
            user.id,
            severity="medium",
            message_id=message.message_id,
        )

        return

    # --------------------------------------------------------
    # Forward Lock
    # --------------------------------------------------------

    if (
        settings.get("lock_forward", False)
        and is_forwarded(message)
    ):

        try:
            await message.delete()
        except Exception:
            pass

        increment_stats(
            chat.id,
            "deleted_messages",
        )

        log_security_event(
            chat.id,
            "forward_blocked",
            user.id,
            severity="medium",
            message_id=message.message_id,
        )

        await send_log(
            context,
            (
                "🔁 FORWARD BLOCKED\n\n"
                f"User: {get_user_display(user)}\n"
                f"Chat: {chat.title}"
            )
        )

        return

    # --------------------------------------------------------
    # Scam Detection
    # --------------------------------------------------------

    if contains_scam(clean):

        try:
            await message.delete()
        except Exception:
            pass

        warnings, muted = await add_warning(
            context,
            chat.id,
            user.id,
            "Scam / suspicious content",
            message.message_id,
        )

        increment_stats(
            chat.id,
            "deleted_messages",
        )

        log_security_event(
            chat.id,
            "scam_detected",
            user.id,
            severity="high",
            message_id=message.message_id,
            details={
                "warnings": warnings,
                "muted": muted,
            },
        )

        await send_log(
            context,
            (
                "🚨 RASKOV ANTI-SCAM\n\n"
                f"User: {get_user_display(user)}\n"
                f"ID: {user.id}\n"
                f"Warnings: {warnings}\n"
                f"Muted: {'YES' if muted else 'NO'}"
            )
        )

        return

    # --------------------------------------------------------
    # Wallet Detection
    # --------------------------------------------------------

    if (
        settings.get("lock_wallets", True)
        and contains_wallet(clean)
    ):

        try:
            await message.delete()
        except Exception:
            pass

        warnings, muted = await add_warning(
            context,
            chat.id,
            user.id,
            "Crypto wallet address",
            message.message_id,
        )

        increment_stats(
            chat.id,
            "wallets_blocked",
        )

        increment_stats(
            chat.id,
            "deleted_messages",
        )

        log_security_event(
            chat.id,
            "wallet_blocked",
            user.id,
            severity="high",
            message_id=message.message_id,
        )

        await send_log(
            context,
            (
                "💰 CRYPTO WALLET BLOCKED\n\n"
                f"User: {get_user_display(user)}\n"
                f"Warnings: {warnings}"
            )
        )

        return

    # --------------------------------------------------------
    # Phone Detection
    # --------------------------------------------------------

    if (
        settings.get("lock_phone_numbers", False)
        and contains_phone(clean)
    ):

        try:
            await message.delete()
        except Exception:
            pass

        warnings, muted = await add_warning(
            context,
            chat.id,
            user.id,
            "Phone number",
            message.message_id,
        )

        increment_stats(
            chat.id,
            "phone_numbers_blocked",
        )

        increment_stats(
            chat.id,
            "deleted_messages",
        )

        log_security_event(
            chat.id,
            "phone_blocked",
            user.id,
            severity="medium",
            message_id=message.message_id,
        )

        return

    # --------------------------------------------------------
    # Advertisement Detection
    # --------------------------------------------------------

    if (
        settings.get("lock_ads", True)
        and contains_ad(clean)
    ):

        try:
            await message.delete()
        except Exception:
            pass

        warnings, muted = await add_warning(
            context,
            chat.id,
            user.id,
            "Advertisement",
            message.message_id,
        )

        increment_stats(
            chat.id,
            "ads_blocked",
        )

        increment_stats(
            chat.id,
            "deleted_messages",
        )

        log_security_event(
            chat.id,
            "advertisement_blocked",
            user.id,
            severity="medium",
            message_id=message.message_id,
        )

        await send_log(
            context,
            (
                "📢 ADVERTISEMENT BLOCKED\n\n"
                f"User: {get_user_display(user)}\n"
                f"Warnings: {warnings}"
            )
        )

        return

    # --------------------------------------------------------
    # Link Protection
    # --------------------------------------------------------

    if (
        settings.get("lock_links", True)
        and contains_link(clean)
    ):

        whitelist = get_whitelist(
            chat.id
        )

        domains = extract_domains(clean)

        allowed = False

        if domains:
            allowed = all(
                is_whitelisted_domain(
                    domain,
                    whitelist
                )
                for domain in domains
            )

        if not allowed:

            try:
                await message.delete()
            except Exception:
                pass

            warnings, muted = await add_warning(
                context,
                chat.id,
                user.id,
                "Unauthorized link",
                message.message_id,
            )

            increment_stats(
                chat.id,
                "links_blocked",
            )

            increment_stats(
                chat.id,
                "deleted_messages",
            )

            log_security_event(
                chat.id,
                "link_blocked",
                user.id,
                severity="medium",
                message_id=message.message_id,
                details={
                    "domains": domains
                },
            )

            await send_log(
                context,
                (
                    "🔗 LINK BLOCKED\n\n"
                    f"User: {get_user_display(user)}\n"
                    f"Domains: {', '.join(domains) or 'hidden'}\n"
                    f"Warnings: {warnings}"
                )
            )

            return


# ============================================================
# PANEL
# ============================================================

def panel_keyboard(settings):
    def status(value):
        return "🟢 ON" if value else "🔴 OFF"

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🔗 الروابط {status(settings.get('lock_links'))}",
                    callback_data="toggle:links",
                ),
                InlineKeyboardButton(
                    f"📢 الإعلانات {status(settings.get('lock_ads'))}",
                    callback_data="toggle:ads",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🌊 Anti-Spam {status(settings.get('anti_spam'))}",
                    callback_data="toggle:spam",
                ),
                InlineKeyboardButton(
                    f"⚔️ Anti-Raid {status(settings.get('anti_raid'))}",
                    callback_data="toggle:raid",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"💰 Wallet {status(settings.get('lock_wallets'))}",
                    callback_data="toggle:wallet",
                ),
                InlineKeyboardButton(
                    f"📱 Phone {status(settings.get('lock_phone_numbers'))}",
                    callback_data="toggle:phone",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🔁 Forward {status(settings.get('lock_forward'))}",
                    callback_data="toggle:forward",
                ),
                InlineKeyboardButton(
                    f"🖼️ Media {status(settings.get('lock_media'))}",
                    callback_data="toggle:media",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"📜 الشروط {status(settings.get('require_terms'))}",
                    callback_data="toggle:terms",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📊 الإحصائيات",
                    callback_data="stats",
                ),
                InlineKeyboardButton(
                    "🛡️ Security Score",
                    callback_data="score",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔄 تحديث",
                    callback_data="refresh",
                ),
                InlineKeyboardButton(
                    "❌ إغلاق",
                    callback_data="close",
                ),
            ],
        ]
    )


def panel_text(chat, settings):
    score = calculate_security_score(settings)

    return (
        "🛡️ RASKOV SECURITY PANEL V6.0\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏠 المجموعة: {chat.title}\n"
        f"🆔 Chat ID: {chat.id}\n\n"
        f"🔐 مستوى الأمان: {security_level(score)}\n"
        f"🎯 Security Score: {score}/100\n\n"
        "اختر نظام الحماية الذي تريد التحكم فيه:"
    )


async def panel_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ هذا الأمر مخصص للمشرفين فقط."
        )
        return

    chat = update.effective_chat

    settings = get_settings(chat)

    save_security_score(
        chat.id,
        settings,
    )

    await update.message.reply_text(
        panel_text(
            chat,
            settings,
        ),
        reply_markup=panel_keyboard(
            settings
        ),
    )


# ============================================================
# PANEL CALLBACK
# ============================================================

async def panel_callback(update, context):
    query = update.callback_query

    await query.answer()

    chat_id = query.message.chat.id

    # Check admin
    if not await is_user_admin(
        context,
        chat_id,
        query.from_user.id,
    ):
        await query.answer(
            "⛔ للمشرفين فقط.",
            show_alert=True,
        )
        return

    chat = query.message.chat

    settings = get_settings(chat)

    data = query.data

    # --------------------------------------------------------
    # Close
    # --------------------------------------------------------

    if data == "close":

        try:
            await query.edit_message_text(
                "🛡️ تم إغلاق لوحة Raskov."
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # Refresh
    # --------------------------------------------------------

    if data == "refresh":

        settings = get_settings(chat)

        try:
            await query.edit_message_text(
                panel_text(chat, settings),
                reply_markup=panel_keyboard(settings),
            )
        except Exception:
            pass

        return

    # --------------------------------------------------------
    # Security Score
    # --------------------------------------------------------

    if data == "score":

        score = calculate_security_score(
            settings
        )

        text = (
            "🛡️ RASKOV SECURITY SCORE\n\n"
            f"🎯 Score: {score}/100\n"
            f"📊 Level: {security_level(score)}\n\n"
            "كلما زادت أنظمة الحماية المفعلة، "
            "ارتفع مستوى الأمان."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 العودة",
                        callback_data="refresh",
                    )
                ]
            ]
        )

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
        )

        return

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    if data == "stats":

        try:
            today = datetime.now(
                timezone.utc
            ).date().isoformat()

            result = (
                supabase
                .table("statistics")
                .select("*")
                .eq("chat_id", chat_id)
                .eq("stat_date", today)
                .limit(1)
                .execute()
            )

            stats = (
                result.data[0]
                if result.data
                else {}
            )

            text = (
                "📊 RASKOV STATISTICS\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💬 Messages: {stats.get('messages', 0)}\n"
                f"🗑️ Deleted: {stats.get('deleted_messages', 0)}\n"
                f"⚠️ Warnings: {stats.get('warnings', 0)}\n"
                f"🚫 Bans: {stats.get('bans', 0)}\n"
                f"🔇 Mutes: {stats.get('mutes', 0)}\n"
                f"👥 Joins: {stats.get('joins', 0)}\n"
                f"🔗 Links blocked: {stats.get('links_blocked', 0)}\n"
                f"📢 Ads blocked: {stats.get('ads_blocked', 0)}\n"
                f"🌊 Spam blocked: {stats.get('spam_blocked', 0)}\n"
                f"💰 Wallets blocked: {stats.get('wallets_blocked', 0)}\n"
                f"📱 Phones blocked: {stats.get('phone_numbers_blocked', 0)}\n"
                f"⚔️ Raid events: {stats.get('raid_events', 0)}"
            )

        except Exception:
            text = (
                "📊 لا توجد إحصائيات متاحة حاليًا."
            )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 العودة",
                        callback_data="refresh",
                    )
                ]
            ]
        )

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
        )

        return

    # --------------------------------------------------------
    # Toggles
    # --------------------------------------------------------

    toggle_map = {
        "toggle:links": "lock_links",
        "toggle:ads": "lock_ads",
        "toggle:spam": "anti_spam",
        "toggle:raid": "anti_raid",
        "toggle:wallet": "lock_wallets",
        "toggle:phone": "lock_phone_numbers",
        "toggle:forward": "lock_forward",
        "toggle:media": "lock_media",
        "toggle:terms": "require_terms",
    }

    if data in toggle_map:

        key = toggle_map[data]

        current = bool(
            settings.get(
                key,
                False
            )
        )

        new_value = not current

        if update_setting(
            chat_id,
            key,
            new_value,
        ):

            settings_cache.pop(
                chat_id,
                None
            )

            settings = get_settings(
                chat
            )

            score = calculate_security_score(
                settings
            )

            try:
                await query.edit_message_text(
                    panel_text(
                        chat,
                        settings,
                    ),
                    reply_markup=panel_keyboard(
                        settings
                    ),
                )
            except Exception:
                pass

            log_security_event(
                chat_id,
                "setting_changed",
                query.from_user.id,
                severity="low",
                details={
                    "setting": key,
                    "value": new_value,
                    "security_score": score,
                },
            )

        return


# ============================================================
# /START
# ============================================================

async def start_command(update, context):
    text = (
        "🛡️ RASKOV SECURITY BOT V6.0\n\n"
        "نظام حماية متقدم لمجموعات Telegram.\n\n"
        "🔗 Anti-Link\n"
        "🌊 Anti-Spam\n"
        "⚔️ Anti-Raid\n"
        "📢 Anti-Advertisement\n"
        "💰 Wallet Protection\n"
        "📱 Phone Protection\n"
        "🔁 Anti-Forward\n"
        "🖼️ Anti-Media\n"
        "⚠️ Warning System\n"
        "📜 Terms Protection\n"
        "📊 Analytics\n"
        "🎯 Security Score\n\n"
        "👮 للمشرفين:\n"
        "/panel"
    )

    await update.message.reply_text(
        text
    )


# ============================================================
# /WARNINGS
# ============================================================

async def warnings_command(update, context):
    chat = update.effective_chat
    user = update.effective_user

    member = get_member(
        chat.id,
        user.id,
    )

    warnings = (
        int(member.get("warnings", 0))
        if member
        else 0
    )

    await update.message.reply_text(
        f"⚠️ تحذيراتك الحالية: {warnings}"
    )


# ============================================================
# /TESTLOG
# ============================================================

async def testlog_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    await send_log(
        context,
        "🧪 Raskov V6.0 Log Test\n\n"
        "✅ Supabase\n"
        "✅ Webhook\n"
        "✅ Logging"
    )

    await update.message.reply_text(
        "🧪 تم إرسال اختبار السجل."
    )


# ============================================================
# /LOCKLINKS
# ============================================================

async def locklinks_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    chat_id = update.effective_chat.id

    update_setting(
        chat_id,
        "lock_links",
        True,
    )

    await update.message.reply_text(
        "🔗 تم تفعيل Anti-Link."
    )


# ============================================================
# /LOCKMEDIA
# ============================================================

async def lockmedia_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    chat_id = update.effective_chat.id

    update_setting(
        chat_id,
        "lock_media",
        True,
    )

    await update.message.reply_text(
        "🖼️ تم تفعيل Media Lock."
    )


# ============================================================
# /LOCKFORWARD
# ============================================================

async def lockforward_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    chat_id = update.effective_chat.id

    update_setting(
        chat_id,
        "lock_forward",
        True,
    )

    await update.message.reply_text(
        "🔁 تم تفعيل Anti-Forward."
    )


# ============================================================
# /BAN
# ============================================================

async def ban_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "استخدم الأمر بالرد على رسالة العضو."
        )
        return

    target = update.message.reply_to_message.from_user

    try:
        await context.bot.ban_chat_member(
            update.effective_chat.id,
            target.id,
        )

        (
            supabase
            .table("blocked_users")
            .upsert(
                {
                    "chat_id": update.effective_chat.id,
                    "user_id": target.id,
                    "reason": "Manual ban",
                    "blocked_by": update.effective_user.id,
                },
                on_conflict="chat_id,user_id"
            )
            .execute()
        )

        increment_stats(
            update.effective_chat.id,
            "bans",
        )

        update_group_counter(
            update.effective_chat.id,
            "total_bans",
        )

        log_security_event(
            update.effective_chat.id,
            "manual_ban",
            target.id,
            severity="high",
        )

        await update.message.reply_text(
            f"🚫 تم حظر {get_user_display(target)}."
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ فشل الحظر: {e}"
        )


# ============================================================
# /UNBAN
# ============================================================

async def unban_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "الاستخدام:\n/unban USER_ID"
        )
        return

    try:
        user_id = int(
            context.args[0]
        )

        await context.bot.unban_chat_member(
            update.effective_chat.id,
            user_id,
        )

        (
            supabase
            .table("blocked_users")
            .delete()
            .eq(
                "chat_id",
                update.effective_chat.id
            )
            .eq(
                "user_id",
                user_id
            )
            .execute()
        )

        await update.message.reply_text(
            f"✅ تم إلغاء حظر المستخدم {user_id}."
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ خطأ: {e}"
        )


# ============================================================
# /RESETWARNINGS
# ============================================================

async def resetwarnings_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "استخدم الأمر بالرد على رسالة العضو."
        )
        return

    target = (
        update.message.reply_to_message
        .from_user
    )

    try:
        (
            supabase
            .table("members")
            .update(
                {
                    "warnings": 0
                }
            )
            .eq(
                "chat_id",
                update.effective_chat.id
            )
            .eq(
                "user_id",
                target.id
            )
            .execute()
        )

        await update.message.reply_text(
            f"✅ تم تصفير تحذيرات {get_user_display(target)}."
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ خطأ: {e}"
        )


# ============================================================
# /UNMUTE
# ============================================================

async def unmute_command(update, context):
    if not await is_admin(update, context):
        await update.message.reply_text(
            "⛔ للمشرفين فقط."
        )
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "استخدم الأمر بالرد على رسالة العضو."
        )
        return

    target = (
        update.message.reply_to_message
        .from_user
    )

    try:
        await unmute_user(
            context,
            update.effective_chat.id,
            target.id,
        )

        (
            supabase
            .table("members")
            .update(
                {
                    "is_muted": False
                }
            )
            .eq(
                "chat_id",
                update.effective_chat.id
            )
            .eq(
                "user_id",
                target.id
            )
            .execute()
        )

        await update.message.reply_text(
            f"🔊 تم فك تقييد {get_user_display(target)}."
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ خطأ: {e}"
        )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    logger.exception(
        "Unhandled exception: %s",
        context.error,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "Starting Raskov Security Bot V6.0..."
    )

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # Commands
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "panel",
            panel_command
        )
    )

    application.add_handler(
        CommandHandler(
            "warnings",
            warnings_command
        )
    )

    application.add_handler(
        CommandHandler(
            "testlog",
            testlog_command
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban_command
        )
    )

    application.add_handler(
        CommandHandler(
            "resetwarnings",
            resetwarnings_command
        )
    )

    application.add_handler(
        CommandHandler(
            "unmute",
            unmute_command
        )
    )

    application.add_handler(
        CommandHandler(
            "locklinks",
            locklinks_command
        )
    )

    application.add_handler(
        CommandHandler(
            "lockmedia",
            lockmedia_command
        )
    )

    application.add_handler(
        CommandHandler(
            "lockforward",
            lockforward_command
        )
    )

    # --------------------------------------------------------
    # New members
    # --------------------------------------------------------

    application.add_handler(
        ChatMemberHandler(
            process_new_member,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    # --------------------------------------------------------
    # Terms
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            terms_callback,
            pattern=r"^terms_(accept|reject):",
        )
    )

    # --------------------------------------------------------
    # Admin Panel
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^(toggle:|stats$|score$|refresh$|close$)",
        )
    )

    # --------------------------------------------------------
    # Moderation
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            moderate_message,
        )
    )

    # --------------------------------------------------------
    # Errors
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # Webhook
    # --------------------------------------------------------

    webhook_url = (
        f"{RENDER_URL.rstrip('/')}/"
        f"{WEBHOOK_PATH}"
    )

    logger.info(
        "Webhook URL: %s",
        webhook_url
    )

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
