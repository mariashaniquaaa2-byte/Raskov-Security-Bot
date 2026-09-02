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
# RASKOV SECURITY BOT V6.1
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("RASKOV")


# ============================================================
# ENVIRONMENT
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

RENDER_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    "https://raskov-security-bot.onrender.com",
)

PORT = int(os.getenv("PORT", "10000"))

WEBHOOK_PATH = (
    f"telegram/{TOKEN}"
    if TOKEN
    else "telegram/webhook"
)


# ============================================================
# SUPABASE
# ============================================================

supabase: Client | None = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(
            SUPABASE_URL,
            SUPABASE_KEY,
        )
        logger.info("Supabase initialized successfully.")
    except Exception as e:
        logger.error("Supabase initialization failed: %s", e)
else:
    logger.warning(
        "SUPABASE_URL or SUPABASE_KEY is missing. "
        "Bot will use fallback settings."
    )


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
# CACHE / MEMORY
# ============================================================

settings_cache = {}

message_tracker = defaultdict(deque)
join_tracker = defaultdict(deque)

CACHE_SECONDS = 30


# ============================================================
# PATTERNS
# ============================================================

URL_PATTERN = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s]+"
    r"|\b(?:t\.me|telegram\.me|discord\.gg|discord\.com/invite)/[^\s]+"
)

DOMAIN_PATTERN = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?"
    r"([a-z0-9.-]+\.[a-z]{2,})"
    r"(?:/[^\s]*)?"
)

WALLET_PATTERN = re.compile(
    r"\b0x[a-fA-F0-9]{40}\b"
)

PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)"
)


# ============================================================
# WHITELIST
# ============================================================

DEFAULT_WHITELIST = {
    "minepi.com",
    "pi.app",
}


# ============================================================
# UTILITY
# ============================================================

def now_ts():
    return datetime.now(timezone.utc).isoformat()


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return text.strip()


def normalize_text(text: str | None) -> str:
    text = clean_text(text)
    return text.lower()


def get_user_display(user) -> str:
    if not user:
        return "Unknown"

    if getattr(user, "username", None):
        return f"@{user.username}"

    name = getattr(user, "full_name", None)

    if name:
        return name

    return str(user.id)


# ============================================================
# SUPABASE GROUP
# ============================================================

def get_group(
    chat_id: int,
    chat_title: str | None = None,
    chat_username: str | None = None,
):
    if not supabase:
        result = DEFAULT_SETTINGS.copy()
        result["chat_id"] = chat_id
        return result

    try:
        response = (
            supabase
            .table("groups")
            .select("*")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]

        payload = {
            "chat_id": chat_id,
            "chat_title": chat_title or "",
            "chat_username": chat_username or "",

            **DEFAULT_SETTINGS,

            "terms_text": (
                "📜 يرجى قراءة شروط المجموعة والموافقة عليها "
                "قبل المشاركة."
            ),

            "welcome_text": (
                "👋 مرحبًا بك {name} في {group}!"
            ),
        }

        inserted = (
            supabase
            .table("groups")
            .insert(payload)
            .execute()
        )

        if inserted.data:
            return inserted.data[0]

    except Exception as e:
        logger.warning(
            "get_group error for %s: %s",
            chat_id,
            e,
        )

    result = DEFAULT_SETTINGS.copy()
    result["chat_id"] = chat_id
    return result


def get_settings(chat):
    chat_id = chat.id

    cached = settings_cache.get(chat_id)

    if cached:
        timestamp, settings = cached

        if time.time() - timestamp < CACHE_SECONDS:
            return settings

    settings = get_group(
        chat_id,
        getattr(chat, "title", ""),
        getattr(chat, "username", ""),
    )

    merged = DEFAULT_SETTINGS.copy()
    merged.update(settings or {})

    settings_cache[chat_id] = (
        time.time(),
        merged,
    )

    return merged


def update_setting(
    chat_id: int,
    key: str,
    value,
):
    if not supabase:
        return False

    try:
        (
            supabase
            .table("groups")
            .update({
                key: value,
                "updated_at": now_ts(),
            })
            .eq("chat_id", chat_id)
            .execute()
        )

        settings_cache.pop(chat_id, None)

        return True

    except Exception as e:
        logger.warning(
            "update_setting error: %s",
            e,
        )

        return False


# ============================================================
# MEMBER DATABASE
# ============================================================

def ensure_member(chat_id, user):
    if not supabase or not user:
        return

    try:
        (
            supabase
            .table("members")
            .upsert(
                {
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "username": getattr(
                        user,
                        "username",
                        None,
                    ),
                    "first_name": getattr(
                        user,
                        "first_name",
                        None,
                    ),
                    "last_name": getattr(
                        user,
                        "last_name",
                        None,
                    ),
                    "last_seen_at": now_ts(),
                    "updated_at": now_ts(),
                },
                on_conflict="chat_id,user_id",
            )
            .execute()
        )

    except Exception as e:
        logger.warning(
            "ensure_member error: %s",
            e,
        )


def get_member(chat_id, user_id):
    if not supabase:
        return None

    try:
        response = (
            supabase
            .table("members")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]

    except Exception as e:
        logger.warning(
            "get_member error: %s",
            e,
        )

    return None


# ============================================================
# STATISTICS
# ============================================================

def increment_stats(
    chat_id: int,
    field: str,
    amount: int = 1,
):
    if not supabase:
        return

    try:
        today = datetime.now(
            timezone.utc
        ).date().isoformat()

        response = (
            supabase
            .table("statistics")
            .select("*")
            .eq("chat_id", chat_id)
            .eq("stat_date", today)
            .limit(1)
            .execute()
        )

        if response.data:
            row = response.data[0]

            current = int(
                row.get(field, 0) or 0
            )

            (
                supabase
                .table("statistics")
                .update({
                    field: current + amount,
                    "updated_at": now_ts(),
                })
                .eq("id", row["id"])
                .execute()
            )

        else:
            payload = {
                "chat_id": chat_id,
                "stat_date": today,
                field: amount,
                "updated_at": now_ts(),
            }

            (
                supabase
                .table("statistics")
                .insert(payload)
                .execute()
            )

    except Exception as e:
        logger.warning(
            "increment_stats error: %s",
            e,
        )


def update_group_counter(
    chat_id: int,
    field: str,
    amount: int = 1,
):
    if not supabase:
        return

    try:
        response = (
            supabase
            .table("groups")
            .select(field)
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )

        current = 0

        if response.data:
            current = int(
                response.data[0].get(
                    field,
                    0,
                )
                or 0
            )

        (
            supabase
            .table("groups")
            .update({
                field: current + amount,
                "updated_at": now_ts(),
            })
            .eq("chat_id", chat_id)
            .execute()
        )

    except Exception as e:
        logger.warning(
            "update_group_counter error: %s",
            e,
        )


# ============================================================
# SECURITY LOG
# ============================================================

def log_security_event(
    chat_id,
    event_type,
    severity="medium",
    user_id=None,
    message_id=None,
    details=None,
):
    if not supabase:
        return

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
                    "created_at": now_ts(),
                }
            )
            .execute()
        )

    except Exception as e:
        logger.warning(
            "log_security_event error: %s",
            e,
        )


async def send_log(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
):
    if not LOG_CHANNEL_ID:
        return

    try:
        await context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=text,
        )

    except Exception as e:
        logger.warning(
            "send_log error: %s",
            e,
        )


# ============================================================
# ADMIN CHECK
# ============================================================

async def is_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return False

    try:
        member = await context.bot.get_chat_member(
            chat.id,
            user.id,
        )

        return member.status in (
            "administrator",
            "creator",
        )

    except Exception as e:
        logger.warning(
            "is_admin error: %s",
            e,
        )

        return False


async def is_user_admin(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
):
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


async def bot_can_restrict(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
):
    try:
        me = await context.bot.get_me()

        member = await context.bot.get_chat_member(
            chat_id,
            me.id,
        )

        if member.status == "creator":
            return True

        if member.status != "administrator":
            return False

        return bool(
            getattr(
                member,
                "can_restrict_members",
                False,
            )
        )

    except Exception as e:
        logger.warning(
            "bot_can_restrict error: %s",
            e,
        )

        return False


# ============================================================
# MUTE / UNMUTE
# ============================================================

async def mute_user(
    context,
    chat_id: int,
    user_id: int,
    minutes: int,
):
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

    until_date = (
        int(time.time())
        + minutes * 60
    )

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
        )

        return True

    except Exception as e:
        logger.warning(
            "mute_user error: %s",
            e,
        )

        return False


async def unmute_user(
    context,
    chat_id: int,
    user_id: int,
):
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

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
        )

        return True

    except Exception as e:
        logger.warning(
            "unmute_user error: %s",
            e,
        )

        return False


# ============================================================
# WARNING MESSAGE
# ============================================================

async def send_group_warning(
    context,
    chat_id: int,
    user,
    reason: str,
    warnings: int,
    max_warnings: int,
    muted: bool = False,
    mute_minutes: int = 0,
):
    display = get_user_display(user)

    if muted:
        text = (
            "⚠️ تحذير أمني\n\n"
            f"👤 المستخدم: {display}\n"
            f"🚫 السبب: {reason}\n"
            f"⚠️ التحذيرات: {warnings}/{max_warnings}\n\n"
            f"🔇 تم تقييد المستخدم لمدة "
            f"{mute_minutes} دقيقة.\n\n"
            "يرجى الالتزام بقوانين المجموعة."
        )
    else:
        text = (
            "⚠️ تحذير أمني\n\n"
            f"👤 المستخدم: {display}\n"
            f"🚫 السبب: {reason}\n"
            f"⚠️ التحذيرات: {warnings}/{max_warnings}\n\n"
            "يرجى الالتزام بقوانين المجموعة."
        )

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
        )

    except Exception as e:
        logger.warning(
            "Could not send warning to group %s: %s",
            chat_id,
            e,
        )


# ============================================================
# ADD WARNING
# ============================================================

async def add_warning(
    context,
    chat_id: int,
    user,
    reason: str,
    message_id: int | None = None,
):
    settings = get_settings(
        await context.bot.get_chat(chat_id)
    )

    max_warnings = max(
        1,
        int(
            settings.get(
                "max_warnings",
                3,
            )
            or 3
        ),
    )

    mute_minutes = max(
        1,
        int(
            settings.get(
                "warning_mute_minutes",
                10,
            )
            or 10
        ),
    )

    current_warnings = 0

    member = get_member(
        chat_id,
        user.id,
    )

    if member:
        current_warnings = int(
            member.get(
                "warnings",
                0,
            )
            or 0
        )

    new_warnings = current_warnings + 1

    # ----------------------------
    # Database
    # ----------------------------

    if supabase:
        try:
            (
                supabase
                .table("members")
                .upsert(
                    {
                        "chat_id": chat_id,
                        "user_id": user.id,
                        "username": getattr(
                            user,
                            "username",
                            None,
                        ),
                        "first_name": getattr(
                            user,
                            "first_name",
                            None,
                        ),
                        "last_name": getattr(
                            user,
                            "last_name",
                            None,
                        ),
                        "warnings": new_warnings,
                        "updated_at": now_ts(),
                    },
                    on_conflict="chat_id,user_id",
                )
                .execute()
            )

        except Exception as e:
            logger.warning(
                "Updating member warning failed: %s",
                e,
            )

        try:
            (
                supabase
                .table("warnings")
                .insert(
                    {
                        "chat_id": chat_id,
                        "user_id": user.id,
                        "reason": reason,
                        "message_id": message_id,
                        "action": "warning",
                        "created_at": now_ts(),
                    }
                )
                .execute()
            )

        except Exception as e:
            logger.warning(
                "Inserting warning failed: %s",
                e,
            )

    # ----------------------------
    # Statistics
    # ----------------------------

    increment_stats(
        chat_id,
        "warnings",
    )

    update_group_counter(
        chat_id,
        "total_warnings",
    )

    # ----------------------------
    # Maximum warnings
    # ----------------------------

    muted = False

    if new_warnings >= max_warnings:
        muted = await mute_user(
            context,
            chat_id,
            user.id,
            mute_minutes,
        )

        if muted:
            if supabase:
                try:
                    (
                        supabase
                        .table("members")
                        .update(
                            {
                                "is_muted": True,
                                "updated_at": now_ts(),
                            }
                        )
                        .eq(
                            "chat_id",
                            chat_id,
                        )
                        .eq(
                            "user_id",
                            user.id,
                        )
                        .execute()
                    )

                except Exception as e:
                    logger.warning(
                        "Updating mute state failed: %s",
                        e,
                    )

            increment_stats(
                chat_id,
                "mutes",
            )

            update_group_counter(
                chat_id,
                "total_mutes",
            )

    # ----------------------------
    # IMPORTANT:
    # Always send warning to group
    # ----------------------------

    await send_group_warning(
        context,
        chat_id,
        user,
        reason,
        new_warnings,
        max_warnings,
        muted,
        mute_minutes,
    )

    await send_log(
        context,
        (
            "⚠️ WARNING\n"
            f"Chat: {chat_id}\n"
            f"User: {get_user_display(user)}\n"
            f"Reason: {reason}\n"
            f"Warnings: {new_warnings}/{max_warnings}\n"
            f"Muted: {muted}"
        ),
    )

    return new_warnings, muted


# ============================================================
# CONTENT DETECTION
# ============================================================

def contains_link(text):
    return bool(
        URL_PATTERN.search(
            text or ""
        )
    )


def extract_domains(text):
    if not text:
        return []

    return [
        match.group(1).lower()
        for match in DOMAIN_PATTERN.finditer(
            text
        )
    ]


def get_whitelist(chat_id):
    whitelist = set(
        DEFAULT_WHITELIST
    )

    if not supabase:
        return whitelist

    try:
        response = (
            supabase
            .table("whitelist_domains")
            .select("domain")
            .eq("chat_id", chat_id)
            .execute()
        )

        for row in response.data or []:
            domain = row.get("domain")

            if domain:
                whitelist.add(
                    domain.lower().strip()
                )

    except Exception as e:
        logger.warning(
            "get_whitelist error: %s",
            e,
        )

    return whitelist


def is_whitelisted_domain(
    chat_id,
    domain,
):
    domain = domain.lower()

    whitelist = get_whitelist(
        chat_id
    )

    for allowed in whitelist:
        if (
            domain == allowed
            or domain.endswith(
                "." + allowed
            )
        ):
            return True

    return False


def contains_wallet(text):
    return bool(
        WALLET_PATTERN.search(
            text or ""
        )
    )


def contains_phone(text):
    return bool(
        PHONE_PATTERN.search(
            text or ""
        )
    )


def contains_scam(text):
    if not text:
        return False

    text = normalize_text(text)

    scam_words = [
        "double your pi",
        "double pi",
        "send pi",
        "send us your pi",
        "free pi",
        "claim pi",
        "giveaway pi",
        "investment guarantee",
        "guaranteed profit",
        "recover your wallet",
        "wallet recovery",
        "seed phrase",
        "recovery phrase",
        "private key",
        "verification code",
        "otp",
    ]

    return any(
        word in text
        for word in scam_words
    )


def contains_ad(text):
    if not text:
        return False

    text = normalize_text(text)

    ad_words = [
        "buy now",
        "sale",
        "discount",
        "promo",
        "promotion",
        "offer",
        "advertisement",
        "sponsor",
        "paid",
        "subscribe",
        "join my channel",
        "join our channel",
        "contact me",
        "earn money",
        "make money",
    ]

    return any(
        word in text
        for word in ad_words
    )


def contains_media(message):
    return any(
        [
            message.photo,
            message.video,
            message.document,
            message.audio,
            message.voice,
            message.video_note,
            message.animation,
            message.sticker,
        ]
    )


def is_forwarded(message):
    return bool(
        getattr(
            message,
            "forward_origin",
            None,
        )
    )


# ============================================================
# SECURITY SCORE
# ============================================================

def calculate_security_score(
    settings,
):
    score = 0

    if settings.get("lock_links"):
        score += 15

    if settings.get("lock_ads"):
        score += 10

    if settings.get("lock_wallets"):
        score += 15

    if settings.get("anti_spam"):
        score += 15

    if settings.get("anti_raid"):
        score += 15

    if settings.get("lock_forward"):
        score += 5

    if settings.get("lock_media"):
        score += 5

    if settings.get("lock_phone_numbers"):
        score += 5

    if settings.get("require_terms"):
        score += 15

    return min(
        100,
        score,
    )


def security_level(score):
    if score >= 90:
        return "🟢 ممتاز"

    if score >= 70:
        return "🟡 جيد"

    if score >= 50:
        return "🟠 متوسط"

    return "🔴 ضعيف"


def save_security_score(
    chat_id,
    score,
):
    update_setting(
        chat_id,
        "security_score",
        score,
    )


# ============================================================
# NEW MEMBER
# ============================================================

async def process_new_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_member = update.chat_member

    if not chat_member:
        return

    chat = chat_member.chat

    old_member = (
        chat_member.old_chat_member
    )

    new_member = (
        chat_member.new_chat_member
    )

    old_status = old_member.status
    new_status = new_member.status

    old_is_member = bool(
        getattr(
            old_member,
            "is_member",
            False,
        )
    )

    new_is_member = bool(
        getattr(
            new_member,
            "is_member",
            False,
        )
    )

    joined = (
        new_status in (
            "member",
            "restricted",
        )
        and new_is_member
        and (
            old_status in (
                "left",
                "kicked",
            )
            or not old_is_member
        )
    )

    if not joined:
        return

    user = new_member.user

    if not user:
        return

    # Don't process bots as normal new members
    if getattr(
        user,
        "is_bot",
        False,
    ):
        return

    logger.info(
        "NEW MEMBER EVENT | chat=%s | user=%s | old=%s | new=%s",
        chat.id,
        get_user_display(user),
        old_status,
        new_status,
    )

    await send_log(
        context,
        (
            "👤 NEW MEMBER\n"
            f"Chat: {chat.id}\n"
            f"User: {get_user_display(user)}\n"
            f"Old status: {old_status}\n"
            f"New status: {new_status}"
        ),
    )

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

    # ========================================================
    # ANTI RAID
    # ========================================================

    if settings.get(
        "anti_raid",
        True,
    ):
        current_time = time.time()

        tracker = join_tracker[
            chat.id
        ]

        tracker.append(
            current_time
        )

        window = int(
            settings.get(
                "raid_window_seconds",
                60,
            )
            or 60
        )

        while (
            tracker
            and current_time - tracker[0]
            > window
        ):
            tracker.popleft()

        limit = int(
            settings.get(
                "raid_join_limit",
                10,
            )
            or 10
        )

        if len(tracker) >= limit:
            raid_minutes = int(
                settings.get(
                    "raid_lock_minutes",
                    10,
                )
                or 10
            )

            muted = await mute_user(
                context,
                chat.id,
                user.id,
                raid_minutes,
            )

            increment_stats(
                chat.id,
                "raid_events",
            )

            update_group_counter(
                chat.id,
                "total_raid_events",
            )

            log_security_event(
                chat.id,
                "anti_raid",
                "high",
                user.id,
                None,
                {
                    "joins": len(tracker),
                    "window": window,
                },
            )

            await send_log(
                context,
                (
                    "🚨 ANTI-RAID\n"
                    f"Chat: {chat.id}\n"
                    f"User: {get_user_display(user)}\n"
                    f"Joins: {len(tracker)}\n"
                    f"Muted: {muted}"
                ),
            )

    # ========================================================
    # TERMS
    # ========================================================

    if settings.get(
        "require_terms",
        True,
    ):

        # ----------------------------------------------------
        # First try to restrict
        # ----------------------------------------------------

        restricted = False

        can_restrict = await bot_can_restrict(
            context,
            chat.id,
        )

        if can_restrict:
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

            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions=permissions,
                )

                restricted = True

            except Exception as e:
                logger.warning(
                    "New member restriction failed: %s",
                    e,
                )

                await send_log(
                    context,
                    (
                        "⚠️ TERMS RESTRICTION FAILED\n"
                        f"Chat: {chat.id}\n"
                        f"User: {get_user_display(user)}\n"
                        f"Error: {e}"
                    ),
                )

        else:
            logger.warning(
                "Bot cannot restrict members in chat %s",
                chat.id,
            )

            await send_log(
                context,
                (
                    "⚠️ BOT PERMISSION WARNING\n"
                    f"Chat: {chat.id}\n"
                    "Bot does not have Restrict Members permission."
                ),
            )

        # ----------------------------------------------------
        # IMPORTANT:
        # Send terms even if restriction failed
        # ----------------------------------------------------

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ أوافق على الشروط",
                        callback_data=(
                            f"terms_accept:"
                            f"{chat.id}:"
                            f"{user.id}"
                        ),
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ لا أوافق",
                        callback_data=(
                            f"terms_reject:"
                            f"{chat.id}:"
                            f"{user.id}"
                        ),
                    )
                ],
            ]
        )

        terms = settings.get(
            "terms_text",
            "📜 يرجى الموافقة على شروط المجموعة.",
        )

        welcome = (
            f"👋 مرحبًا {get_user_display(user)}!\n\n"
            f"{terms}\n\n"
            "🔒 يجب الموافقة على الشروط قبل "
            "المشاركة في المجموعة.\n\n"
            "👇 اختر أحد الخيارات:"
        )

        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome,
                reply_markup=keyboard,
            )

            logger.info(
                "Terms message sent successfully | chat=%s | user=%s",
                chat.id,
                user.id,
            )

        except Exception as e:
            logger.error(
                "Could not send terms message: %s",
                e,
            )

            await send_log(
                context,
                (
                    "❌ TERMS MESSAGE FAILED\n"
                    f"Chat: {chat.id}\n"
                    f"User: {get_user_display(user)}\n"
                    f"Error: {e}"
                ),
            )

    elif settings.get(
        "welcome_enabled",
        True,
    ):

        welcome_text = settings.get(
            "welcome_text",
            "👋 مرحبًا بك {name}!",
        )

        welcome_text = welcome_text.replace(
            "{name}",
            get_user_display(user),
        )

        welcome_text = welcome_text.replace(
            "{group}",
            chat.title or "",
        )

        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=welcome_text,
            )

        except Exception as e:
            logger.warning(
                "Welcome message failed: %s",
                e,
            )


# ============================================================
# TERMS CALLBACK
# ============================================================

async def terms_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    parts = data.split(":")

    if len(parts) != 3:
        await query.answer(
            "بيانات غير صحيحة.",
            show_alert=True,
        )
        return

    action = parts[0]

    try:
        chat_id = int(parts[1])
        user_id = int(parts[2])

    except ValueError:
        await query.answer(
            "بيانات غير صحيحة.",
            show_alert=True,
        )
        return

    current_user = query.from_user

    # Only the target user can accept/reject
    if current_user.id != user_id:

        await query.answer(
            "❌ هذا الزر مخصص للعضو الجديد فقط.",
            show_alert=True,
        )

        return

    # ========================================================
    # ACCEPT
    # ========================================================

    if action == "terms_accept":

        success = await unmute_user(
            context,
            chat_id,
            user_id,
        )

        if not success:
            await query.answer(
                "❌ تعذر فك التقييد. تأكد من صلاحيات البوت.",
                show_alert=True,
            )

            await send_log(
                context,
                (
                    "❌ TERMS ACCEPT FAILED\n"
                    f"Chat: {chat_id}\n"
                    f"User: {get_user_display(current_user)}"
                ),
            )

            return

        if supabase:
            try:
                (
                    supabase
                    .table("members")
                    .upsert(
                        {
                            "chat_id": chat_id,
                            "user_id": user_id,
                            "username": getattr(
                                current_user,
                                "username",
                                None,
                            ),
                            "first_name": getattr(
                                current_user,
                                "first_name",
                                None,
                            ),
                            "last_name": getattr(
                                current_user,
                                "last_name",
                                None,
                            ),
                            "terms_accepted": True,
                            "terms_accepted_at": now_ts(),
                            "is_muted": False,
                            "updated_at": now_ts(),
                        },
                        on_conflict="chat_id,user_id",
                    )
                    .execute()
                )

            except Exception as e:
                logger.warning(
                    "Saving terms acceptance failed: %s",
                    e,
                )

        await query.answer(
            "✅ تم قبول الشروط.",
            show_alert=False,
        )

        try:
            await query.edit_message_text(
                "✅ تم قبول الشروط.\n\n"
                "🎉 مرحبًا بك في المجموعة!\n"
                "يمكنك الآن المشاركة.",
            )

        except Exception as e:
            logger.warning(
                "Edit accepted terms message failed: %s",
                e,
            )

        await send_log(
            context,
            (
                "✅ TERMS ACCEPTED\n"
                f"Chat: {chat_id}\n"
                f"User: {get_user_display(current_user)}"
            ),
        )

        return

    # ========================================================
    # REJECT
    # ========================================================

    if action == "terms_reject":

        await query.answer(
            "❌ لم تتم الموافقة على الشروط.",
            show_alert=False,
        )

        try:
            await query.edit_message_text(
                "❌ لم تتم الموافقة على الشروط.\n\n"
                "🔒 ستبقى صلاحياتك مقيدة حتى الموافقة.",
            )

        except Exception as e:
            logger.warning(
                "Edit rejected terms message failed: %s",
                e,
            )

        await send_log(
            context,
            (
                "❌ TERMS REJECTED\n"
                f"Chat: {chat_id}\n"
                f"User: {get_user_display(current_user)}"
            ),
        )


# ============================================================
# MODERATION
# ============================================================

async def moderate_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.message

    if not message:
        return

    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    # Private messages are ignored
    if chat.type == "private":
        return

    # Ignore bots
    if getattr(
        user,
        "is_bot",
        False,
    ):
        return

    ensure_member(
        chat.id,
        user,
    )

    settings = get_settings(chat)

    # Admin bypass
    if await is_user_admin(
        context,
        chat.id,
        user.id,
    ):
        return

    update_group_counter(
        chat.id,
        "total_messages",
    )

    increment_stats(
        chat.id,
        "messages",
    )

    # ========================================================
    # ANTI SPAM / FLOOD
    # ========================================================

    if settings.get(
        "anti_spam",
        True,
    ):

        current_time = time.time()

        tracker = message_tracker[
            (chat.id, user.id)
        ]

        tracker.append(
            current_time
        )

        limit = max(
            1,
            int(
                settings.get(
                    "flood_limit",
                    5,
                )
                or 5
            ),
        )

        window = max(
            1,
            int(
                settings.get(
                    "flood_window",
                    4,
                )
                or 4
            ),
        )

        while (
            tracker
            and current_time - tracker[0]
            > window
        ):
            tracker.popleft()

        # Fixed: >= instead of >
        if len(tracker) >= limit:

            mute_minutes = max(
                1,
                int(
                    settings.get(
                        "flood_mute_minutes",
                        5,
                    )
                    or 5
                ),
            )

            try:
                await message.delete()

                increment_stats(
                    chat.id,
                    "spam_blocked",
                )

                update_group_counter(
                    chat.id,
                    "deleted_messages",
                )

            except Exception as e:
                logger.warning(
                    "Spam message delete failed: %s",
                    e,
                )

            muted = await mute_user(
                context,
                chat.id,
                user.id,
                mute_minutes,
            )

            await add_warning(
                context,
                chat.id,
                user,
                "Flood / Spam",
                message.message_id,
            )

            log_security_event(
                chat.id,
                "anti_spam",
                "high",
                user.id,
                message.message_id,
                {
                    "messages": len(tracker),
                    "window": window,
                },
            )

            return

    # ========================================================
    # MESSAGE TEXT
    # ========================================================

    text = ""

    if message.text:
        text = message.text

    elif message.caption:
        text = message.caption

    text = clean_text(text)

    # ========================================================
    # MEDIA LOCK
    # ========================================================

    if (
        settings.get("lock_media", False)
        and contains_media(message)
    ):

        try:
            await message.delete()

            increment_stats(
                chat.id,
                "deleted_messages",
            )

            update_group_counter(
                chat.id,
                "deleted_messages",
            )

        except Exception as e:
            logger.warning(
                "Media delete failed: %s",
                e,
            )

        return

    # ========================================================
    # FORWARD LOCK
    # ========================================================

    if (
        settings.get("lock_forward", False)
        and is_forwarded(message)
    ):

        try:
            await message.delete()

            increment_stats(
                chat.id,
                "deleted_messages",
            )

            update_group_counter(
                chat.id,
                "deleted_messages",
            )

        except Exception as e:
            logger.warning(
                "Forward delete failed: %s",
                e,
            )

        return

    # ========================================================
    # WALLET
    # ========================================================

    if (
        settings.get(
            "lock_wallets",
            True,
        )
        and contains_wallet(text)
    ):

        try:
            await message.delete()

            increment_stats(
                chat.id,
                "wallets_blocked",
            )

            update_group_counter(
                chat.id,
                "deleted_messages",
            )

        except Exception as e:
            logger.warning(
                "Wallet delete failed: %s",
                e,
            )

        await add_warning(
            context,
            chat.id,
            user,
            "Crypto wallet / suspicious address",
            message.message_id,
        )

        return

    # ========================================================
    # PHONE
    # ========================================================

    if (
        settings.get(
            "lock_phone_numbers",
            False,
        )
        and contains_phone(text)
    ):

        try:
            await message.delete()

            increment_stats(
                chat.id,
                "phone_numbers_blocked",
            )

            update_group_counter(
                chat.id,
                "deleted_messages",
            )

        except Exception as e:
            logger.warning(
                "Phone delete failed: %s",
                e,
            )

        await add_warning(
            context,
            chat.id,
            user,
            "Phone number",
            message.message_id,
        )

        return

    # ========================================================
    # SCAM
    # ========================================================

    if contains_scam(text):

        try:
            await message.delete()

            increment_stats(
                chat.id,
                "deleted_messages",
            )

            update_group_counter(
                chat.id,
                "deleted_messages",
            )

        except Exception as e:
            logger.warning(
                "Scam delete failed: %s",
                e,
            )

        await add_warning(
            context,
            chat.id,
            user,
            "Possible Scam / Phishing",
            message.message_id,
        )

        log_security_event(
            chat.id,
            "scam",
            "critical",
            user.id,
            message.message_id,
            {"text": text[:500]},
        )

        return

    # ========================================================
    # ADVERTISEMENT
    # ========================================================

    if (
        settings.get(
            "lock_ads",
            True,
        )
        and contains_ad(text)
    ):

        try:
            await message.delete()

            increment_stats(
                chat.id,
                "ads_blocked",
            )

            update_group_counter(
                chat.id,
                "deleted_messages",
            )

        except Exception as e:
            logger.warning(
                "Advertisement delete failed: %s",
                e,
            )

        await add_warning(
            context,
            chat.id,
            user,
            "Advertisement / Promotion",
            message.message_id,
        )

        return

    # ========================================================
    # LINKS
    # ========================================================

    if (
        settings.get(
            "lock_links",
            True,
        )
        and contains_link(text)
    ):

        domains = extract_domains(text)

        allowed = False

        if domains:
            allowed = all(
                is_whitelisted_domain(
                    chat.id,
                    domain,
                )
                for domain in domains
            )

        if not allowed:

            try:
                await message.delete()

                increment_stats(
                    chat.id,
                    "links_blocked",
                )

                update_group_counter(
                    chat.id,
                    "deleted_messages",
                )

            except Exception as e:
                logger.warning(
                    "Link delete failed: %s",
                    e,
                )

            await add_warning(
                context,
                chat.id,
                user,
                "Blocked Link",
                message.message_id,
            )

            return


# ============================================================
# START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "🛡️ Raskov Security Bot V6.1\n\n"
        "أنا نظام حماية وأمان للمجموعات.\n\n"
        "الأمن:\n"
        "✅ Anti-Scam\n"
        "✅ Anti-Spam\n"
        "✅ Anti-Advertisement\n"
        "✅ Link Protection\n"
        "✅ Wallet Protection\n"
        "✅ Anti-Raid\n"
        "✅ Terms Verification\n"
        "✅ Warning System\n"
        "✅ Supabase Database\n\n"
        "استخدم /panel داخل مجموعتك "
        "لفتح لوحة الإدارة."
    )


# ============================================================
# PANEL
# ============================================================

def panel_keyboard(
    settings,
):
    def icon(key):
        return (
            "🟢"
            if settings.get(key)
            else "🔴"
        )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{icon('lock_links')} الروابط",
                    callback_data="toggle:lock_links",
                ),
                InlineKeyboardButton(
                    f"{icon('lock_ads')} الإعلانات",
                    callback_data="toggle:lock_ads",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{icon('anti_spam')} Anti-Spam",
                    callback_data="toggle:anti_spam",
                ),
                InlineKeyboardButton(
                    f"{icon('anti_raid')} Anti-Raid",
                    callback_data="toggle:anti_raid",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{icon('lock_wallets')} المحافظ",
                    callback_data="toggle:lock_wallets",
                ),
                InlineKeyboardButton(
                    f"{icon('lock_phone_numbers')} الأرقام",
                    callback_data="toggle:lock_phone_numbers",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{icon('lock_media')} Media",
                    callback_data="toggle:lock_media",
                ),
                InlineKeyboardButton(
                    f"{icon('lock_forward')} Forward",
                    callback_data="toggle:lock_forward",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{icon('require_terms')} الشروط",
                    callback_data="toggle:terms",
                ),
                InlineKeyboardButton(
                    "📊 الإحصائيات",
                    callback_data="stats",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🛡️ Security Score",
                    callback_data="score",
                ),
                InlineKeyboardButton(
                    "🔄 تحديث",
                    callback_data="refresh",
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ إغلاق",
                    callback_data="close",
                ),
            ],
        ]
    )


async def panel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ هذا الأمر للمشرفين فقط."
        )
        return

    chat = update.effective_chat

    settings = get_settings(chat)

    score = calculate_security_score(
        settings
    )

    save_security_score(
        chat.id,
        score,
    )

    text = (
        "🛡️ RASKOV SECURITY PANEL V6.1\n\n"
        f"🔐 Security Score: {score}/100\n"
        f"📈 المستوى: {security_level(score)}\n\n"
        "اختر النظام الذي تريد التحكم به:"
    )

    await update.message.reply_text(
        text,
        reply_markup=panel_keyboard(
            settings
        ),
    )


# ============================================================
# PANEL CALLBACK
# ============================================================

async def panel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    chat = query.message.chat

    fake_update = update

    if not await is_admin(
        fake_update,
        context,
    ):
        await query.answer(
            "❌ للمشرفين فقط.",
            show_alert=True,
        )
        return

    data = query.data or ""

    # ========================================================
    # CLOSE
    # ========================================================

    if data == "close":
        await query.answer()

        try:
            await query.edit_message_text(
                "✅ تم إغلاق لوحة التحكم."
            )
        except Exception:
            pass

        return

    # ========================================================
    # REFRESH
    # ========================================================

    if data == "refresh":

        settings = get_settings(chat)

        score = calculate_security_score(
            settings
        )

        save_security_score(
            chat.id,
            score,
        )

        await query.answer(
            "🔄 تم التحديث."
        )

        await query.edit_message_reply_markup(
            reply_markup=panel_keyboard(
                settings
            )
        )

        return

    # ========================================================
    # TOGGLE
    # ========================================================

    if data.startswith("toggle:"):

        key = data.split(
            ":",
            1,
        )[1]

        if key == "terms":
            key = "require_terms"

        settings = get_settings(chat)

        current = bool(
            settings.get(
                key,
                False,
            )
        )

        new_value = not current

        success = update_setting(
            chat.id,
            key,
            new_value,
        )

        if not success:
            await query.answer(
                "❌ تعذر حفظ الإعداد.",
                show_alert=True,
            )
            return

        settings[key] = new_value

        score = calculate_security_score(
            settings
        )

        save_security_score(
            chat.id,
            score,
        )

        await query.answer(
            "🟢 تم التفعيل."
            if new_value
            else "🔴 تم التعطيل."
        )

        await query.edit_message_reply_markup(
            reply_markup=panel_keyboard(
                settings
            )
        )

        return

    # ========================================================
    # STATS
    # ========================================================

    if data == "stats":

        if not supabase:
            await query.answer(
                "قاعدة البيانات غير متاحة.",
                show_alert=True,
            )
            return

        try:
            today = datetime.now(
                timezone.utc
            ).date().isoformat()

            response = (
                supabase
                .table("statistics")
                .select("*")
                .eq("chat_id", chat.id)
                .eq("stat_date", today)
                .limit(1)
                .execute()
            )

            if response.data:
                row = response.data[0]

                text = (
                    "📊 إحصائيات اليوم\n\n"
                    f"💬 الرسائل: {row.get('messages', 0)}\n"
                    f"🗑️ المحذوف: {row.get('deleted_messages', 0)}\n"
                    f"⚠️ التحذيرات: {row.get('warnings', 0)}\n"
                    f"🔇 الكتم: {row.get('mutes', 0)}\n"
                    f"🚫 الحظر: {row.get('bans', 0)}\n"
                    f"👤 الانضمامات: {row.get('joins', 0)}\n"
                    f"🔗 الروابط: {row.get('links_blocked', 0)}\n"
                    f"📢 الإعلانات: {row.get('ads_blocked', 0)}\n"
                    f"💰 المحافظ: {row.get('wallets_blocked', 0)}\n"
                    f"📱 الأرقام: {row.get('phone_numbers_blocked', 0)}\n"
                    f"🚨 Raid: {row.get('raid_events', 0)}"
                )

            else:
                text = (
                    "📊 لا توجد إحصائيات مسجلة اليوم."
                )

            await query.answer()

            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔙 لوحة التحكم",
                                callback_data="refresh",
                            )
                        ]
                    ]
                ),
            )

        except Exception as e:
            logger.warning(
                "Stats error: %s",
                e,
            )

            await query.answer(
                "❌ تعذر جلب الإحصائيات.",
                show_alert=True,
            )

        return

    # ========================================================
    # SCORE
    # ========================================================

    if data == "score":

        settings = get_settings(chat)

        score = calculate_security_score(
            settings
        )

        save_security_score(
            chat.id,
            score,
        )

        text = (
            "🛡️ SECURITY SCORE\n\n"
            f"Score: {score}/100\n"
            f"Level: {security_level(score)}\n\n"
            "يتم احتساب النقاط حسب أنظمة الحماية "
            "المفعلة في المجموعة."
        )

        await query.answer()

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 لوحة التحكم",
                            callback_data="refresh",
                        )
                    ]
                ]
            ),
        )

        return


# ============================================================
# WARNINGS COMMAND
# ============================================================

async def warnings_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    chat = update.effective_chat

    member = get_member(
        chat.id,
        user.id,
    )

    warnings = 0

    if member:
        warnings = int(
            member.get(
                "warnings",
                0,
            )
            or 0
        )

    settings = get_settings(chat)

    max_warnings = settings.get(
        "max_warnings",
        3,
    )

    await update.message.reply_text(
        "⚠️ نظام التحذيرات\n\n"
        f"👤 {get_user_display(user)}\n"
        f"⚠️ تحذيراتك: {warnings}/{max_warnings}"
    )


# ============================================================
# ENABLE / DISABLE TERMS
# ============================================================

async def enableterms_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    chat = update.effective_chat

    success = update_setting(
        chat.id,
        "require_terms",
        True,
    )

    if success:
        await update.message.reply_text(
            "✅ تم تفعيل نظام الموافقة على الشروط.\n\n"
            "👤 كل عضو جديد سيحتاج إلى الضغط على "
            "«أوافق على الشروط» قبل المشاركة."
        )

    else:
        await update.message.reply_text(
            "❌ تعذر حفظ الإعداد في قاعدة البيانات."
        )


async def disableterms_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    chat = update.effective_chat

    success = update_setting(
        chat.id,
        "require_terms",
        False,
    )

    if success:
        await update.message.reply_text(
            "🔴 تم تعطيل نظام الموافقة على الشروط."
        )

    else:
        await update.message.reply_text(
            "❌ تعذر حفظ الإعداد."
        )


# ============================================================
# BAN
# ============================================================

async def ban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    message = update.message

    if not message.reply_to_message:
        await message.reply_text(
            "⚠️ استخدم /ban بالرد على رسالة العضو."
        )
        return

    target = (
        message.reply_to_message.from_user
    )

    try:
        await context.bot.ban_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
        )

        if supabase:
            try:
                (
                    supabase
                    .table("blocked_users")
                    .upsert(
                        {
                            "chat_id": message.chat.id,
                            "user_id": target.id,
                            "reason": "Manual ban",
                            "blocked_by": update.effective_user.id,
                            "created_at": now_ts(),
                        },
                        on_conflict="chat_id,user_id",
                    )
                    .execute()
                )

                (
                    supabase
                    .table("members")
                    .upsert(
                        {
                            "chat_id": message.chat.id,
                            "user_id": target.id,
                            "is_banned": True,
                            "updated_at": now_ts(),
                        },
                        on_conflict="chat_id,user_id",
                    )
                    .execute()
                )

            except Exception as e:
                logger.warning(
                    "Ban DB update failed: %s",
                    e,
                )

        increment_stats(
            message.chat.id,
            "bans",
        )

        update_group_counter(
            message.chat.id,
            "total_bans",
        )

        await message.reply_text(
            f"🚫 تم حظر {get_user_display(target)}."
        )

        await send_log(
            context,
            (
                "🚫 BAN\n"
                f"Chat: {message.chat.id}\n"
                f"User: {get_user_display(target)}\n"
                f"By: {get_user_display(update.effective_user)}"
            ),
        )

    except Exception as e:
        await message.reply_text(
            f"❌ فشل الحظر: {e}"
        )


# ============================================================
# UNBAN
# ============================================================

async def unban_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "استخدم:\n/unban USER_ID"
        )
        return

    try:
        user_id = int(
            context.args[0]
        )

    except ValueError:
        await update.message.reply_text(
            "❌ USER_ID غير صحيح."
        )
        return

    chat_id = update.effective_chat.id

    try:
        await context.bot.unban_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            only_if_banned=True,
        )

        if supabase:
            try:
                (
                    supabase
                    .table("blocked_users")
                    .delete()
                    .eq(
                        "chat_id",
                        chat_id,
                    )
                    .eq(
                        "user_id",
                        user_id,
                    )
                    .execute()
                )

                (
                    supabase
                    .table("members")
                    .update(
                        {
                            "is_banned": False,
                            "updated_at": now_ts(),
                        }
                    )
                    .eq(
                        "chat_id",
                        chat_id,
                    )
                    .eq(
                        "user_id",
                        user_id,
                    )
                    .execute()
                )

            except Exception as e:
                logger.warning(
                    "Unban DB error: %s",
                    e,
                )

        await update.message.reply_text(
            f"✅ تم إلغاء حظر المستخدم {user_id}."
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ فشل إلغاء الحظر: {e}"
        )


# ============================================================
# RESET WARNINGS
# ============================================================

async def resetwarnings_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ استخدم الأمر بالرد على رسالة العضو."
        )
        return

    target = (
        update.message.reply_to_message.from_user
    )

    if supabase:
        try:
            (
                supabase
                .table("members")
                .update(
                    {
                        "warnings": 0,
                        "updated_at": now_ts(),
                    }
                )
                .eq(
                    "chat_id",
                    update.effective_chat.id,
                )
                .eq(
                    "user_id",
                    target.id,
                )
                .execute()
            )

        except Exception as e:
            logger.warning(
                "Reset warnings error: %s",
                e,
            )

    await update.message.reply_text(
        f"✅ تم تصفير تحذيرات {get_user_display(target)}."
    )


# ============================================================
# UNMUTE COMMAND
# ============================================================

async def unmute_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ استخدم /unmute بالرد على رسالة العضو."
        )
        return

    target = (
        update.message.reply_to_message.from_user
    )

    success = await unmute_user(
        context,
        update.effective_chat.id,
        target.id,
    )

    if success:

        if supabase:
            try:
                (
                    supabase
                    .table("members")
                    .update(
                        {
                            "is_muted": False,
                            "updated_at": now_ts(),
                        }
                    )
                    .eq(
                        "chat_id",
                        update.effective_chat.id,
                    )
                    .eq(
                        "user_id",
                        target.id,
                    )
                    .execute()
                )

            except Exception as e:
                logger.warning(
                    "Unmute DB error: %s",
                    e,
                )

        await update.message.reply_text(
            f"🔊 تم فك التقييد عن {get_user_display(target)}."
        )

    else:
        await update.message.reply_text(
            "❌ تعذر فك التقييد. "
            "تأكد من صلاحيات البوت."
        )


# ============================================================
# LOCK COMMANDS
# ============================================================

async def locklinks_command(
    update,
    context,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    update_setting(
        update.effective_chat.id,
        "lock_links",
        True,
    )

    await update.message.reply_text(
        "🔗🟢 تم تفعيل حماية الروابط."
    )


async def lockmedia_command(
    update,
    context,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    update_setting(
        update.effective_chat.id,
        "lock_media",
        True,
    )

    await update.message.reply_text(
        "📷🟢 تم تفعيل قفل الوسائط."
    )


async def lockforward_command(
    update,
    context,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    update_setting(
        update.effective_chat.id,
        "lock_forward",
        True,
    )

    await update.message.reply_text(
        "↪️🟢 تم تفعيل قفل الرسائل المعاد توجيهها."
    )


# ============================================================
# TEST LOG
# ============================================================

async def testlog_command(
    update,
    context,
):
    if not await is_admin(
        update,
        context,
    ):
        await update.message.reply_text(
            "❌ للمشرفين فقط."
        )
        return

    await send_log(
        context,
        "🧪 رسالة اختبار - الإعدادات صحيحة ✅",
    )

    await update.message.reply_text(
        "✅ تم إرسال رسالة الاختبار إلى قناة السجل."
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Unhandled exception: %s",
        context.error,
        exc_info=True,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing."
        )

    logger.info(
        "Starting Raskov Security Bot V6.1..."
    )

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    # ========================================================
    # COMMANDS
    # ========================================================

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "panel",
            panel_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "warnings",
            warnings_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "enableterms",
            enableterms_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "disableterms",
            disableterms_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            ban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            unban_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "resetwarnings",
            resetwarnings_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "unmute",
            unmute_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "locklinks",
            locklinks_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "lockmedia",
            lockmedia_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "lockforward",
            lockforward_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "testlog",
            testlog_command,
        )
    )

    # ========================================================
    # NEW MEMBERS
    # ========================================================

    application.add_handler(
        ChatMemberHandler(
            process_new_member,
            ChatMemberHandler.CHAT_MEMBER,
        )
    )

    # ========================================================
    # TERMS
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            terms_callback,
            pattern=r"^terms_(accept|reject):",
        )
    )

    # ========================================================
    # PANEL
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^(toggle:|stats$|score$|refresh$|close$)",
        )
    )

    # ========================================================
    # MODERATION
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            moderate_message,
        )
    )

    # ========================================================
    # ERROR
    # ========================================================

    application.add_error_handler(
        error_handler
    )

    # ========================================================
    # WEBHOOK
    # ========================================================

    webhook_url = (
        f"{RENDER_URL.rstrip('/')}/"
        f"{WEBHOOK_PATH}"
    )

    logger.info(
        "Webhook URL: %s",
        webhook_url,
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
