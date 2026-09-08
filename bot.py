#!/usr/bin/env python3
"""Prank Call Telegram Bot — bottom reply keyboard, force-join, points."""

from __future__ import annotations

import json
import logging
import re
from io import BytesIO
from typing import Optional

import aiohttp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from database import (
    add_points,
    claim_bonus,
    ensure_user,
    get_user,
    init_db,
    is_banned,
    save_call,
    set_banned,
    user_count,
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("prankbot")

WAIT_NUMBER, WAIT_UID, ADMIN_TARGET = range(3)

JOINED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
    ChatMemberStatus.RESTRICTED,
}

BTN_SEND = "SEND CALL"
BTN_BONUS = "BONUS"
BTN_REFER = "REFER"
BTN_BAL = "BALANCE"
BTN_REC = "CALL RECORD"


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def main_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📞 SEND CALL")],
            [
                KeyboardButton("🎁 BONUS"),
                KeyboardButton("👥 REFER"),
            ],
            [
                KeyboardButton("💰 BALANCE"),
                KeyboardButton("🎧 CALL RECORD"),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def text_is(msg: str, name: str) -> bool:
    t = (msg or "").strip().upper()
    t = t.replace("📞", "").replace("🎁", "").replace("👥", "")
    t = t.replace("💰", "").replace("🎧", "").strip()
    return t == name.upper()


def join_kb(missing: list[dict] | None = None) -> InlineKeyboardMarkup:
    channels = missing if missing is not None else config.CHANNELS
    rows = [[InlineKeyboardButton(ch["name"], url=ch["link"])] for ch in channels]
    rows.append([InlineKeyboardButton("✅ আমি জয়েন করেছি", callback_data="verify_join")])
    return InlineKeyboardMarkup(rows)


def prank_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(p["title"], callback_data=f"prank_{p['id']}")] for p in config.PRANKS]
    )


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Coin", callback_data="adm_add"),
                InlineKeyboardButton("➖ Remove Coin", callback_data="adm_rem"),
            ],
            [
                InlineKeyboardButton("🚫 Ban", callback_data="adm_ban"),
                InlineKeyboardButton("✅ Unban", callback_data="adm_unban"),
            ],
        ]
    )


JOIN_TEXT = (
    "👋 <b>Welcome to Prank Call Bot!</b>\n\n"
    "বট ব্যবহার করতে নিচের <b>সব চ্যানেলে</b> জয়েন থাকতে হবে।\n"
    "কোনো একটা থেকে লিভ নিলে সেইটা আবার জয়েন করতে হবে।\n\n"
    "জয়েন করে ✅ চাপুন।"
)


def home_html() -> str:
    return (
        "👋 <b>Welcome to Prank Call Bot!</b>\n\n"
        "নিচের মেনু থেকে সার্ভিস বেছে নিন।\n\n"
        f"💵 প্রতি কল: <b>{config.CALL_COST} পয়েন্ট</b>\n"
        f"🎁 BONUS ক্লিক করলে দৈনিক <b>{config.DAILY_BONUS}</b> পয়েন্ট"
    )


async def check_channels(bot, user_id: int) -> list[dict]:
    missing = []
    for ch in config.CHANNELS:
        try:
            member = await bot.get_chat_member(ch["id"], user_id)
            if member.status not in JOINED_STATUSES:
                missing.append(ch)
        except TelegramError as e:
            log.warning("Membership check failed %s: %s", ch["id"], e)
            missing.append(ch)
    return missing


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if is_banned(user.id):
        msg = "🚫 আপনার অ্যাকাউন্ট ব্যান করা আছে।"
        if update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(msg)
        return False
    missing = await check_channels(context.bot, user.id)
    if missing:
        if len(missing) < len(config.CHANNELS):
            names = "\n".join(f"• {c['name']}" for c in missing)
            text = f"⚠️ <b>লিভ নেওয়া চ্যানেল আবার জয়েন করুন:</b>\n\n{names}\n\nজয়েন করে ✅ চাপুন।"
        else:
            text = JOIN_TEXT
        kb = join_kb(missing)
        if update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.edit_message_text(
                    text, reply_markup=kb, parse_mode=ParseMode.HTML
                )
            except TelegramError:
                await update.effective_chat.send_message(
                    text, reply_markup=kb, parse_mode=ParseMode.HTML
                )
        elif update.message:
            await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                rid = int(arg.replace("ref_", ""))
                if rid != user.id:
                    ref = rid
            except ValueError:
                pass

    created = ensure_user(user.id, user.username, user.full_name, ref)
    if created and ref:
        parent = get_user(ref)
        if parent and not parent["banned"]:
            add_points(ref, config.REFERRAL_REWARD)
            try:
                await context.bot.send_message(
                    ref,
                    f"🎉 নতুন রেফার! +{config.REFERRAL_REWARD} পয়েন্ট\n👤 {user.full_name}",
                )
            except TelegramError:
                pass

    if not await gate(update, context):
        return ConversationHandler.END

    await update.message.reply_text(
        home_html(),
        reply_markup=main_kb(),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    ensure_user(user.id, user.username, user.full_name)
    if is_banned(user.id):
        await q.answer("🚫 ব্যান করা আছে।", show_alert=True)
        return
    missing = await check_channels(context.bot, user.id)
    if missing:
        await q.answer("এখনো সব চ্যানেলে জয়েন করেননি", show_alert=True)
        try:
            await q.edit_message_text(
                "⚠️ সব চ্যানেলে জয়েন করে আবার ✅ চাপুন।",
                reply_markup=join_kb(missing),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return
    await q.answer("✅ ভেরিফাইড!")
    try:
        await q.edit_message_text("✅ চ্যানেল ভেরিফাইড।")
    except TelegramError:
        pass
    await context.bot.send_message(
        user.id,
        home_html(),
        reply_markup=main_kb(),
        parse_mode=ParseMode.HTML,
    )


async def menu_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return ConversationHandler.END
    u = get_user(update.effective_user.id)
    pts = u["points"] if u else 0
    if pts < config.CALL_COST:
        await update.message.reply_text(
            "❌ পয়েন্ট কম। নিচের 🎁 BONUS চাপুন।",
            reply_markup=main_kb(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "🎭 <b>একটি প্র্যাঙ্ক টপিক নির্বাচন করুন:</b>",
        reply_markup=prank_kb(),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def pick_prank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return ConversationHandler.END
    prank_id = q.data.split("_", 1)[1]
    context.user_data["prank_id"] = prank_id
    title = config.PRANK_MAP.get(prank_id, prank_id)
    await q.answer()
    await q.edit_message_text(
        f"🎭 সিলেক্টেড: <b>{title}</b>\n🆔 Joke ID: <code>{prank_id}</code>\n\n"
        "📱 যাকে কল পাঠাবেন তার <b>১১ ডিজিট নাম্বার</b> লিখুন।\n"
        "উদাহরণ: <code>017XXXXXXXX</code>\n\n❌ বাতিল: /cancel",
        parse_mode=ParseMode.HTML,
    )
    return WAIT_NUMBER


def normalize_number(raw: str) -> Optional[str]:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("880") and len(digits) == 13:
        digits = "0" + digits[3:]
    if len(digits) == 11 and digits.startswith("01"):
        return digits
    if len(digits) == 10 and digits.startswith("1"):
        return "0" + digits
    return None


def extract_uid(payload) -> Optional[str]:
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(data, dict):
            for key in ("device_id", "uid", "UID", "generated_uid", "joke_uid"):
                val = data.get(key)
                if val:
                    return str(val)
            for v in data.values():
                if isinstance(v, str) and "@jokesphone" in v.lower():
                    return v
        raw = json.dumps(payload)
        m = re.search(r"([0-9a-f]{8,32}@[A-Za-z0-9_.-]+)", raw, re.I)
        if m:
            return m.group(1)
    if isinstance(payload, str):
        m = re.search(r"([0-9a-f]{8,32}@[A-Za-z0-9_.-]+)", payload, re.I)
        if m:
            return m.group(1)
    return None


async def send_prank_api(number: str, prank_id: str) -> dict:
    url = f"{config.PRANK_API}?number={number}&prank={prank_id}"
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            text = await resp.text()
    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    uid = extract_uid(parsed) or extract_uid(text)
    task_id = None
    if isinstance(parsed, dict):
        data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
        if isinstance(data, dict):
            task_id = data.get("task_id")
    return {"ok": True, "uid": uid, "task_id": task_id, "raw": text, "json": parsed}


def is_menu_text(text: str) -> bool:
    return any(
        text_is(text, n)
        for n in (BTN_SEND, BTN_BONUS, BTN_REFER, BTN_BAL, BTN_REC)
    )


async def receive_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if is_menu_text(text):
        return await route_menu(update, context)

    if not await gate(update, context):
        return ConversationHandler.END
    user = update.effective_user
    u = get_user(user.id)
    if not u or u["points"] < config.CALL_COST:
        await update.message.reply_text("❌ পর্যাপ্ত পয়েন্ট নেই।", reply_markup=main_kb())
        return ConversationHandler.END

    number = normalize_number(text)
    if not number:
        await update.message.reply_text(
            "⚠️ সঠিক <b>১১ ডিজিট</b> নাম্বার দিন। যেমন: <code>01712345678</code>",
            parse_mode=ParseMode.HTML,
        )
        return WAIT_NUMBER

    prank_id = context.user_data.get("prank_id")
    if not prank_id:
        await update.message.reply_text("আবার SEND CALL চাপুন।", reply_markup=main_kb())
        return ConversationHandler.END

    wait = await update.message.reply_text("⏳ কল পাঠানো হচ্ছে...")
    try:
        result = await send_prank_api(number, prank_id)
    except Exception as e:
        log.exception("API error")
        await wait.edit_text(f"❌ API এরর: {e}")
        return ConversationHandler.END

    uid = result.get("uid") or "N/A"
    add_points(user.id, -config.CALL_COST)
    save_call(user.id, number, prank_id, str(uid))
    left = (get_user(user.id) or {}).get("points", 0)
    title = config.PRANK_MAP.get(prank_id, prank_id)

    await wait.edit_text(
        "✅ <b>Prank Call Sent Successfully!</b>\n\n"
        f"🎯 Target: <code>{number}</code>\n"
        f"🆔 Joke ID: <code>{prank_id}</code>\n"
        f"📝 {title}\n"
        f"🔑 Generated UID: <code>{uid}</code>\n\n"
        "💡 রেকর্ড শুনতে নিচের CALL RECORD চাপুন, তারপর UID পেস্ট করুন।\n"
        f"💰 অবশিষ্ট পয়েন্ট: <b>{left}</b>",
        parse_mode=ParseMode.HTML,
    )
    context.user_data.pop("prank_id", None)
    return ConversationHandler.END


async def menu_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return ConversationHandler.END
    uid = update.effective_user.id
    ok = claim_bonus(uid, config.DAILY_BONUS)
    u = get_user(uid)
    pts = u["points"] if u else 0
    if ok:
        await update.message.reply_text(
            f"🎁 <b>বোনাস ক্লেইম হয়েছে!</b>\n\n+{config.DAILY_BONUS} পয়েন্ট\n"
            f"💰 ব্যালেন্স: <b>{pts}</b>\n\nআজ আর ক্লেইম করা যাবে না।",
            parse_mode=ParseMode.HTML,
            reply_markup=main_kb(),
        )
    else:
        await update.message.reply_text(
            f"⚠️ আজকের বোনাস ইতিমধ্যে নিয়েছেন।\n💰 ব্যালেন্স: <b>{pts}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_kb(),
        )
    return ConversationHandler.END


async def menu_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return ConversationHandler.END
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{update.effective_user.id}"
    await update.message.reply_text(
        "👥 <b>রেফার সিস্টেম</b>\n\n"
        f"প্রতি সফল রেফারে <b>{config.REFERRAL_REWARD} পয়েন্ট</b>।\n\n"
        f"🔗 <code>{link}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb(),
    )
    return ConversationHandler.END


async def menu_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return ConversationHandler.END
    u = get_user(update.effective_user.id)
    pts = u["points"] if u else 0
    await update.message.reply_text(
        "💰 <b>আপনার ব্যালেন্স</b>\n━━━━━━━━━━━━\n"
        f"🆔 <code>{update.effective_user.id}</code>\n"
        f"💎 পয়েন্ট: <b>{pts}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb(),
    )
    return ConversationHandler.END


async def menu_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return ConversationHandler.END
    await update.message.reply_text(
        "🎧 <b>CALL RECORD</b>\n\nকল পাঠানোর পর যে UID পেয়েছেন সেটা পাঠান।\n"
        "যেমন: <code>97d91c87981bdc4b@jokesphone</code>\n\n❌ /cancel",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb(),
    )
    return WAIT_UID


def pick_audio_url(obj) -> Optional[str]:
    if not isinstance(obj, dict):
        return None
    for key in ("audio", "audio_url", "url", "record", "file", "voice", "mp3"):
        val = obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
        if isinstance(val, dict):
            u = pick_audio_url(val)
            if u:
                return u
    data = obj.get("data")
    if isinstance(data, dict):
        return pick_audio_url(data)
    if isinstance(data, str) and data.startswith("http"):
        return data
    return None


async def fetch_history(uid: str) -> dict:
    url = f"{config.HISTORY_API}?uid={uid}"
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            body = await resp.text()
            raw = await resp.read()
            ctype = resp.headers.get("Content-Type", "")
    parsed = None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    audio_url = pick_audio_url(parsed) if parsed else None
    if not audio_url:
        m = re.search(
            r"https?://[^\s\"'<>]+\.(?:mp3|ogg|wav|m4a|aac)[^\s\"'<>]*",
            body,
            re.I,
        )
        if m:
            audio_url = m.group(0)
    return {"parsed": parsed, "body": body, "raw": raw, "ctype": ctype, "audio_url": audio_url}


async def send_audio_bytes(update: Update, raw: bytes, uid: str) -> bool:
    bio = BytesIO(raw)
    bio.name = "record.ogg"
    try:
        await update.message.reply_voice(
            voice=bio,
            caption=f"🔑 <code>{uid}</code>",
            parse_mode=ParseMode.HTML,
        )
        return True
    except TelegramError:
        bio2 = BytesIO(raw)
        bio2.name = "record.mp3"
        try:
            await update.message.reply_audio(
                audio=bio2,
                caption=f"🔑 <code>{uid}</code>",
                parse_mode=ParseMode.HTML,
            )
            return True
        except TelegramError:
            return False


async def receive_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if is_menu_text(text):
        return await route_menu(update, context)
    if not await gate(update, context):
        return ConversationHandler.END

    uid = text
    if len(uid) < 6:
        await update.message.reply_text("সঠিক UID দিন।")
        return WAIT_UID

    wait = await update.message.reply_text("🔎 রেকর্ড খোঁজা হচ্ছে...")
    try:
        hist = await fetch_history(uid)
    except Exception as e:
        await wait.edit_text(f"❌ হিস্টরি API এরর: {e}")
        return ConversationHandler.END

    parsed = hist.get("parsed") or {}
    if isinstance(parsed, dict) and parsed.get("status") == "processing":
        await wait.edit_text(
            "⏳ কল এখনো চলছে বা অডিও তৈরি হয়নি।\n২–৩ মিনিট পর আবার একই UID পাঠান।",
            reply_markup=main_kb(),
        )
        return ConversationHandler.END

    audio_url = hist.get("audio_url")
    raw = hist.get("raw") or b""
    ctype = hist.get("ctype") or ""

    if audio_url:
        try:
            timeout = aiohttp.ClientTimeout(total=40)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(audio_url) as resp:
                    audio_bytes = await resp.read()
            if audio_bytes and len(audio_bytes) > 500:
                if await send_audio_bytes(update, audio_bytes, uid):
                    await wait.delete()
                    return ConversationHandler.END
            await update.message.reply_voice(
                voice=audio_url,
                caption=f"🔑 <code>{uid}</code>",
                parse_mode=ParseMode.HTML,
            )
            await wait.delete()
            return ConversationHandler.END
        except Exception as e:
            log.warning("audio fetch fail: %s", e)

    if "audio" in ctype or raw[:3] == b"ID3" or raw[:4] in (b"OggS", b"RIFF"):
        if await send_audio_bytes(update, raw, uid):
            await wait.delete()
            return ConversationHandler.END

    await wait.edit_text(
        "⚠️ এখনো অডিও পাওয়া যায়নি। কিছুক্ষণ পর আবার চেষ্টা করুন।\n"
        f"UID: <code>{uid}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=main_kb(),
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("বাতিল।", reply_markup=main_kb())
    return ConversationHandler.END


async def route_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text_is(text, BTN_SEND):
        return await menu_send(update, context)
    if text_is(text, BTN_BONUS):
        return await menu_bonus(update, context)
    if text_is(text, BTN_REFER):
        return await menu_refer(update, context)
    if text_is(text, BTN_BAL):
        return await menu_balance(update, context)
    if text_is(text, BTN_REC):
        return await menu_record(update, context)
    return ConversationHandler.END


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ অ্যাডমিন নন।")
        return ConversationHandler.END
    await update.message.reply_text(
        f"🛠 <b>Admin Panel</b>\n👥 ইউজার: {user_count()}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_kb(),
    )
    return ConversationHandler.END


async def admin_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("অ্যাডমিন নন", show_alert=True)
        return ConversationHandler.END
    context.user_data["adm_action"] = q.data
    labels = {
        "adm_add": "ফরম্যাট: <code>USER_ID AMOUNT</code>",
        "adm_rem": "ফরম্যাট: <code>USER_ID AMOUNT</code>",
        "adm_ban": "ইউজার আইডি পাঠান",
        "adm_unban": "ইউজার আইডি পাঠান",
    }
    await q.answer()
    await q.edit_message_text(labels[q.data], parse_mode=ParseMode.HTML)
    return ADMIN_TARGET


async def admin_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    action = context.user_data.get("adm_action")
    parts = (update.message.text or "").split()
    try:
        uid = int(parts[0])
    except (IndexError, ValueError):
        await update.message.reply_text("সঠিক ইউজার আইডি দিন।")
        return ADMIN_TARGET
    ensure_user(uid, None, "Unknown")
    if action == "adm_add":
        amt = int(parts[1]) if len(parts) > 1 else 1
        add_points(uid, amt)
        u = get_user(uid)
        await update.message.reply_text(f"✅ {uid} +{amt} → {u['points']}", reply_markup=main_kb())
    elif action == "adm_rem":
        amt = int(parts[1]) if len(parts) > 1 else 1
        add_points(uid, -amt)
        u = get_user(uid)
        await update.message.reply_text(f"✅ {uid} -{amt} → {u['points']}", reply_markup=main_kb())
    elif action == "adm_ban":
        set_banned(uid, True)
        await update.message.reply_text(f"🚫 {uid} ব্যান", reply_markup=main_kb())
    elif action == "adm_unban":
        set_banned(uid, False)
        await update.message.reply_text(f"✅ {uid} আনব্যান", reply_markup=main_kb())
    context.user_data.pop("adm_action", None)
    return ConversationHandler.END


def main():
    if not config.BOT_TOKEN or str(config.BOT_TOKEN).startswith("PUT_"):
        raise SystemExit("BOT_TOKEN সেট করুন Railway Variables এ")

    init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pick_prank, pattern=r"^prank_\d+$"),
            MessageHandler(filters.Regex("(?i)CALL RECORD"), menu_record),
            CallbackQueryHandler(admin_pick, pattern=r"^adm_(add|rem|ban|unban)$"),
        ],
        states={
            WAIT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_number)],
            WAIT_UID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_uid)],
            ADMIN_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_target)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(verify_join, pattern=r"^verify_join$"))
    app.add_handler(MessageHandler(filters.Regex("(?i)SEND CALL"), menu_send))
    app.add_handler(MessageHandler(filters.Regex("(?i)^(.{0,3})?BONUS$"), menu_bonus))
    app.add_handler(MessageHandler(filters.Regex("(?i)REFER"), menu_refer))
    app.add_handler(MessageHandler(filters.Regex("(?i)^(.{0,3})?BALANCE$"), menu_balance))
    app.add_handler(MessageHandler(filters.Regex("(?i)CALL RECORD"), menu_record))

    log.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

