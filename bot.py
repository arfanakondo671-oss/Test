#!/usr/bin/env python3
"""
Prank Call Telegram Bot
Bot must be ADMIN in all 4 channels to check membership.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import aiohttp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
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

WAIT_NUMBER, WAIT_UID, ADMIN_ACTION, ADMIN_TARGET = range(4)

JOINED_STATUSES = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
    ChatMemberStatus.RESTRICTED,
}


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ───────────────────────── Force Join ─────────────────────────
async def check_channels(bot, user_id: int) -> list[dict]:
    missing = []
    for ch in config.CHANNELS:
        try:
            member = await bot.get_chat_member(ch["id"], user_id)
            if member.status not in JOINED_STATUSES or member.status == ChatMemberStatus.LEFT:
                missing.append(ch)
            elif member.status == ChatMemberStatus.BANNED:
                missing.append(ch)
        except TelegramError as e:
            log.warning("Membership check failed %s: %s", ch["id"], e)
            missing.append(ch)
    return missing


def join_keyboard(missing: list[dict] | None = None) -> InlineKeyboardMarkup:
    rows = []
    channels = missing if missing is not None else config.CHANNELS
    for ch in channels:
        rows.append([InlineKeyboardButton(ch["name"], url=ch["link"])])
    rows.append(
        [InlineKeyboardButton("✅ আমি জয়েন করেছি  ·  Verify", callback_data="verify_join")]
    )
    return InlineKeyboardMarkup(rows)


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📞  SEND CALL", callback_data="menu_send")],
            [
                InlineKeyboardButton("🎁  BONUS", callback_data="menu_bonus"),
                InlineKeyboardButton("👥  REFER", callback_data="menu_refer"),
            ],
            [
                InlineKeyboardButton("💰  BALANCE", callback_data="menu_balance"),
                InlineKeyboardButton("🎧  CALL RECORD", callback_data="menu_record"),
            ],
        ]
    )


def prank_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i, p in enumerate(config.PRANKS, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{i}.  {p['title']}", callback_data=f"prank_{p['id']}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️  মেইন মেনু", callback_data="menu_home")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Add Coin", callback_data="adm_add"),
                InlineKeyboardButton("➖ Remove Coin", callback_data="adm_rem"),
            ],
            [
                InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
                InlineKeyboardButton("✅ Unban User", callback_data="adm_unban"),
            ],
            [InlineKeyboardButton("⬅️ ব্যাক", callback_data="menu_home")],
        ]
    )


JOIN_TEXT = (
    "✨ <b>স্বাগতম!</b>\n\n"
    "বট ব্যবহার করতে নিচের <b>সব চ্যানেলে</b> জয়েন থাকতে হবে।\n"
    "কোনো একটি থেকে লিভ নিলে সেই চ্যানেল আবার জয়েন করতে হবে।\n\n"
    "👇 চ্যানেলগুলোতে জয়েন করে <b>Verify</b> চাপুন।"
)

HOME_TEXT = (
    "🎯 <b>Prank Call Bot</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "বন্ধুদের মজার প্র্যাঙ্ক কল পাঠান 😄\n\n"
    "📞 <b>SEND CALL</b> — প্র্যাঙ্ক সিলেক্ট করুন\n"
    "🎁 <b>BONUS</b> — প্রতিদিন {bonus} পয়েন্ট\n"
    "👥 <b>REFER</b> — রেফারে {ref} পয়েন্ট\n"
    "💰 <b>BALANCE</b> — আপনার পয়েন্ট\n"
    "🎧 <b>CALL RECORD</b> — UID দিয়ে রেকর্ড শুনুন\n"
    "━━━━━━━━━━━━━━━━\n"
    "💵 প্রতি কল খরচ: <b>{cost} পয়েন্ট</b>"
)


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
        text = JOIN_TEXT
        if len(missing) < len(config.CHANNELS):
            names = "\n".join(f"• {c['name']}" for c in missing)
            text = (
                "⚠️ <b>আপনি কিছু চ্যানেল থেকে লিভ নিয়েছেন!</b>\n\n"
                "আবার জয়েন করুন:\n"
                f"{names}\n\n"
                "জয়েন করে ✅ Verify চাপুন।"
            )
        kb = join_keyboard(missing)
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
            await update.message.reply_text(
                text, reply_markup=kb, parse_mode=ParseMode.HTML
            )
        return False
    return True


# ───────────────────────── Start ─────────────────────────
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
                    f"🎉 নতুন রেফার! +{config.REFERRAL_REWARD} পয়েন্ট\n"
                    f"👤 {user.full_name}",
                )
            except TelegramError:
                pass

    if not await gate(update, context):
        return

    await update.message.reply_text(
        HOME_TEXT.format(
            bonus=config.DAILY_BONUS,
            ref=config.REFERRAL_REWARD,
            cost=config.CALL_COST,
        ),
        reply_markup=main_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def verify_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = q.from_user
    ensure_user(user.id, user.username, user.full_name)
    if is_banned(user.id):
        await q.answer("🚫 ব্যান করা আছে।", show_alert=True)
        return
    missing = await check_channels(context.bot, user.id)
    if missing:
        names = ", ".join(c["name"] for c in missing)
        await q.answer(f"এখনো জয়েন করেননি: {names}", show_alert=True)
        try:
            await q.edit_message_text(
                "⚠️ সব চ্যানেলে জয়েন করে আবার Verify চাপুন।",
                reply_markup=join_keyboard(missing),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass
        return
    await q.answer("✅ ভেরিফাইড!", show_alert=False)
    await q.edit_message_text(
        HOME_TEXT.format(
            bonus=config.DAILY_BONUS,
            ref=config.REFERRAL_REWARD,
            cost=config.CALL_COST,
        ),
        reply_markup=main_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def menu_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await gate(update, context):
        return ConversationHandler.END
    await q.edit_message_text(
        HOME_TEXT.format(
            bonus=config.DAILY_BONUS,
            ref=config.REFERRAL_REWARD,
            cost=config.CALL_COST,
        ),
        reply_markup=main_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


# ───────────────────────── Menus ─────────────────────────
async def menu_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return
    u = get_user(q.from_user.id)
    pts = u["points"] if u else 0
    if pts < config.CALL_COST:
        await q.answer("পয়েন্ট কম! BONUS বা REFER নিন।", show_alert=True)
        return
    await q.answer()
    await q.edit_message_text(
        "🎭 <b>কোন প্র্যাঙ্ক পাঠাবেন?</b>\n"
        "একটা সিলেক্ট করুন 👇",
        reply_markup=prank_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def pick_prank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return ConversationHandler.END
    prank_id = q.data.split("_", 1)[1]
    context.user_data["prank_id"] = prank_id
    title = config.PRANK_MAP.get(prank_id, prank_id)
    await q.answer()
    await q.edit_message_text(
        f"🎭 <b>সিলেক্টেড:</b> {title}\n"
        f"🆔 Joke ID: <code>{prank_id}</code>\n\n"
        "📱 এখন যাকে কল পাঠাবেন তার <b>১১ ডিজিটের নাম্বার</b> লিখুন।\n"
        "উদাহরণ: <code>017XXXXXXXX</code> বা <code>88017XXXXXXXX</code>\n\n"
        "❌ বাতিল করতে /cancel",
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


async def send_prank_api(number: str, prank_id: str) -> dict:
    url = f"{config.PRANK_API}?number={number}&prank={prank_id}"
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            text = await resp.text()
    uid = None
    audio = None
    # try json
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            uid = (
                data.get("uid")
                or data.get("UID")
                or data.get("id")
                or data.get("generated_uid")
            )
            audio = data.get("audio") or data.get("url") or data.get("record")
            return {"ok": True, "uid": uid, "audio": audio, "raw": text, "json": data}
    except json.JSONDecodeError:
        pass
    m = re.search(
        r"([0-9a-f]{8,32}@jokesphone)", text, re.I
    ) or re.search(r"([0-9a-f]{10,}@[A-Za-z0-9_.-]+)", text, re.I)
    if m:
        uid = m.group(1)
    m2 = re.search(r"https?://[^\s\"']+\.(?:mp3|wav|ogg|m4a)", text, re.I)
    if m2:
        audio = m2.group(0)
    return {"ok": True, "uid": uid, "audio": audio, "raw": text, "json": None}


async def receive_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return ConversationHandler.END
    user = update.effective_user
    u = get_user(user.id)
    if not u or u["points"] < config.CALL_COST:
        await update.message.reply_text(
            "❌ পর্যাপ্ত পয়েন্ট নেই।", reply_markup=main_keyboard()
        )
        return ConversationHandler.END

    number = normalize_number(update.message.text or "")
    if not number:
        await update.message.reply_text(
            "⚠️ সঠিক <b>১১ ডিজিটের</b> বাংলাদেশি নাম্বার দিন।\n"
            "যেমন: <code>01712345678</code>",
            parse_mode=ParseMode.HTML,
        )
        return WAIT_NUMBER

    prank_id = context.user_data.get("prank_id")
    if not prank_id:
        await update.message.reply_text("আবার সিলেক্ট করুন।", reply_markup=main_keyboard())
        return ConversationHandler.END

    wait = await update.message.reply_text("⏳ কল পাঠানো হচ্ছে...")
    try:
        result = await send_prank_api(number, prank_id)
    except Exception as e:
        log.exception("API error")
        await wait.edit_text(f"❌ API এরর: {e}", reply_markup=main_keyboard())
        return ConversationHandler.END

    uid = result.get("uid") or "N/A"
    add_points(user.id, -config.CALL_COST)
    save_call(user.id, number, prank_id, str(uid))
    left = (get_user(user.id) or {}).get("points", 0)
    title = config.PRANK_MAP.get(prank_id, prank_id)

    text = (
        "✅ <b>Prank Call Sent Successfully!</b>\n\n"
        f"🎯 Target: <code>{number}</code>\n"
        f"🆔 Joke ID: <code>{prank_id}</code>\n"
        f"📝 Joke: {title}\n"
        f"🔑 Generated UID: <code>{uid}</code>\n\n"
        "💡 কলের ভয়েস রেকর্ড শুনতে UID ব্যবহার করুন।\n"
        f"💰 অবশিষ্ট পয়েন্ট: <b>{left}</b>"
    )
    await wait.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())
    context.user_data.pop("prank_id", None)
    return ConversationHandler.END


async def menu_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return
    ok = claim_bonus(q.from_user.id, config.DAILY_BONUS)
    u = get_user(q.from_user.id)
    pts = u["points"] if u else 0
    if ok:
        await q.answer()
        await q.edit_message_text(
            f"🎁 <b>ডেইলি বোনাস ক্লেইম হয়েছে!</b>\n\n"
            f"+{config.DAILY_BONUS} পয়েন্ট যোগ হয়েছে।\n"
            f"💰 এখন ব্যালেন্স: <b>{pts}</b>\n\n"
            "আবার ক্লেইম করতে আগামীকাল আসুন।",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )
    else:
        await q.answer("আজকের বোনাস ইতিমধ্যে নিয়েছেন!", show_alert=True)


async def menu_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return
    await q.answer()
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{q.from_user.id}"
    await q.edit_message_text(
        "👥 <b>রেফার সিস্টেম</b>\n\n"
        f"প্রতিটি সফল রেফারে আপনি পাবেন <b>{config.REFERRAL_REWARD} পয়েন্ট</b>।\n"
        "বন্ধুকে এই লিংক পাঠান:\n\n"
        f"🔗 <code>{link}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📤 শেয়ার করুন", url=f"https://t.me/share/url?url={link}&text=Prank%20Call%20Bot")],
                [InlineKeyboardButton("⬅️ মেইন মেনু", callback_data="menu_home")],
            ]
        ),
    )


async def menu_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return
    u = get_user(q.from_user.id)
    pts = u["points"] if u else 0
    await q.answer()
    await q.edit_message_text(
        "💰 <b>আপনার ব্যালেন্স</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🆔 User ID: <code>{q.from_user.id}</code>\n"
        f"💎 পয়েন্ট: <b>{pts}</b>\n"
        f"📞 প্রতি কল: {config.CALL_COST} পয়েন্ট",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


async def menu_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not await gate(update, context):
        return WAIT_UID
    await q.answer()
    await q.edit_message_text(
        "🎧 <b>CALL RECORD</b>\n\n"
        "যে UID জেনারেট হয়েছিল সেটা পাঠান।\n"
        "যেমন: <code>0c1ee0f22f7fb4b4@jokesphone</code>\n\n"
        "❌ বাতিল: /cancel",
        parse_mode=ParseMode.HTML,
    )
    return WAIT_UID


async def receive_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await gate(update, context):
        return ConversationHandler.END
    uid = (update.message.text or "").strip()
    if not uid or " " in uid and "@" not in uid and len(uid) < 6:
        await update.message.reply_text("সঠিক UID দিন।")
        return WAIT_UID

    wait = await update.message.reply_text("🔎 রেকর্ড খোঁজা হচ্ছে...")
    url = f"{config.HISTORY_API}?uid={uid}"
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                body = await resp.text()
                ctype = resp.headers.get("Content-Type", "")
                raw = await resp.read()
    except Exception as e:
        await wait.edit_text(f"❌ হিস্টরি API এরর: {e}", reply_markup=main_keyboard())
        return ConversationHandler.END

    audio_url = None
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            audio_url = (
                data.get("audio")
                or data.get("url")
                or data.get("record")
                or data.get("file")
            )
            if isinstance(audio_url, dict):
                audio_url = audio_url.get("url")
    except json.JSONDecodeError:
        m = re.search(r"https?://[^\s\"'<>]+", body)
        if m:
            audio_url = m.group(0)

    if audio_url:
        try:
            await wait.edit_text("🎧 রেকর্ড পাওয়া গেছে, পাঠানো হচ্ছে...")
            await update.message.reply_audio(
                audio=audio_url,
                caption=f"🔑 UID: <code>{uid}</code>",
                parse_mode=ParseMode.HTML,
            )
            await wait.delete()
        except TelegramError:
            await wait.edit_text(
                f"🎧 অডিও লিংক:\n{audio_url}\n\n🔑 <code>{uid}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=main_keyboard(),
            )
    elif "audio" in ctype or raw[:4] in (b"ID3\x03", b"RIFF", b"OggS", b"\xff\xfb"):
        await update.message.reply_voice(
            voice=raw,
            caption=f"🔑 UID: <code>{uid}</code>",
            parse_mode=ParseMode.HTML,
        )
        await wait.delete()
    else:
        snippet = body[:400] if body else "empty"
        await wait.edit_text(
            f"⚠️ অডিও পাওয়া যায়নি।\nUID: <code>{uid}</code>\n\n<code>{snippet}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard(),
        )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("বাতিল করা হয়েছে।", reply_markup=main_keyboard())
    return ConversationHandler.END


# ───────────────────────── Admin ─────────────────────────
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ অ্যাডমিন নন।")
        return
    n = user_count()
    await update.message.reply_text(
        f"🛠 <b>Admin Panel</b>\n👥 ইউজার: {n}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def admin_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("অ্যাডমিন নন", show_alert=True)
        return ConversationHandler.END
    action = q.data  # adm_add / adm_rem / adm_ban / adm_unban
    context.user_data["adm_action"] = action
    labels = {
        "adm_add": "কত পয়েন্ট অ্যাড করবেন ও ইউজার আইডি\nফরম্যাট: <code>USER_ID AMOUNT</code>",
        "adm_rem": "কত পয়েন্ট কাটবেন ও ইউজার আইডি\nফরম্যাট: <code>USER_ID AMOUNT</code>",
        "adm_ban": "ব্যান করতে ইউজার আইডি পাঠান",
        "adm_unban": "আনব্যান করতে ইউজার আইডি পাঠান",
    }
    await q.answer()
    await q.edit_message_text(labels[action], parse_mode=ParseMode.HTML)
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
        await update.message.reply_text(
            f"✅ {uid} এ +{amt} পয়েন্ট। এখন: {u['points']}",
            reply_markup=admin_keyboard(),
        )
    elif action == "adm_rem":
        amt = int(parts[1]) if len(parts) > 1 else 1
        add_points(uid, -amt)
        u = get_user(uid)
        await update.message.reply_text(
            f"✅ {uid} থেকে -{amt}। এখন: {u['points']}",
            reply_markup=admin_keyboard(),
        )
    elif action == "adm_ban":
        set_banned(uid, True)
        await update.message.reply_text(f"🚫 {uid} ব্যান।", reply_markup=admin_keyboard())
    elif action == "adm_unban":
        set_banned(uid, False)
        await update.message.reply_text(f"✅ {uid} আনব্যান।", reply_markup=admin_keyboard())
    context.user_data.pop("adm_action", None)
    return ConversationHandler.END


def main():
    if not config.BOT_TOKEN or config.BOT_TOKEN.startswith("PUT_"):
        raise SystemExit("BOT_TOKEN সেট করুন .env বা config.py তে")

    init_db()
    app = Application.builder().token(config.BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(pick_prank, pattern=r"^prank_\d+$"),
            CallbackQueryHandler(menu_record, pattern=r"^menu_record$"),
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
            CallbackQueryHandler(menu_home, pattern=r"^menu_home$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(verify_join, pattern=r"^verify_join$"))
    app.add_handler(CallbackQueryHandler(menu_home, pattern=r"^menu_home$"))
    app.add_handler(CallbackQueryHandler(menu_send, pattern=r"^menu_send$"))
    app.add_handler(CallbackQueryHandler(menu_bonus, pattern=r"^menu_bonus$"))
    app.add_handler(CallbackQueryHandler(menu_refer, pattern=r"^menu_refer$"))
    app.add_handler(CallbackQueryHandler(menu_balance, pattern=r"^menu_balance$"))
    app.add_handler(CallbackQueryHandler(menu_record, pattern=r"^menu_record$"))

    log.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
