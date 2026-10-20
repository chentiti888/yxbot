#!/usr/bin/env python3
import os
import random
import sqlite3
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.environ.get("ADMIN_ID", "").strip()
DB_PATH = os.environ.get("DB_PATH", "/opt/tg-guess-bot/data.sqlite3")
INITIAL_POINTS = int(os.environ.get("INITIAL_POINTS", "1000"))
MIN_BET = int(os.environ.get("MIN_BET", "10"))
MAX_BET = int(os.environ.get("MAX_BET", "1000"))
if not BOT_TOKEN:
    raise SystemExit("缺少 BOT_TOKEN 环境变量")
if not ADMIN_ID_RAW.isdigit():
    raise SystemExit("缺少有效的 ADMIN_ID 环境变量")
ADMIN_ID = int(ADMIN_ID_RAW)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("guess-bot")

os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=30000")
conn.executescript("""
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY,
  username TEXT NOT NULL DEFAULT '',
  points INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  guess INTEGER NOT NULL,
  result INTEGER NOT NULL,
  bet INTEGER NOT NULL,
  payout INTEGER NOT NULL,
  balance_after INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
""")
conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('game_enabled','1')")
conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('probabilities','34,33,33')")
conn.commit()

def now():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

def get_setting(key, default=""):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(key, value):
    conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
    conn.commit()

def ensure_user(user):
    username = user.username or user.full_name or ""
    conn.execute(
        "INSERT OR IGNORE INTO users(user_id,username,points,created_at) VALUES(?,?,?,?)",
        (user.id, username, INITIAL_POINTS, now())
    )
    conn.execute("UPDATE users SET username=? WHERE user_id=?", (username, user.id))
    conn.commit()

def balance(user_id):
    row = conn.execute("SELECT points FROM users WHERE user_id=?", (user_id,)).fetchone()
    return int(row["points"]) if row else 0

def enabled():
    return get_setting("game_enabled", "1") == "1"

def probabilities():
    try:
        vals = [int(x) for x in get_setting("probabilities", "34,33,33").split(",")]
        if len(vals) == 3 and all(x >= 0 for x in vals) and sum(vals) == 100:
            return vals
    except Exception:
        pass
    return [34, 33, 33]

def draw_number():
    # The configured probabilities are shown to players in /rules.
    return random.choices([1, 2, 3], weights=probabilities(), k=1)[0]

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 开始猜数字", callback_data="play"),
         InlineKeyboardButton("💰 我的积分", callback_data="balance")],
        [InlineKeyboardButton("📜 游戏规则", callback_data="rules"),
         InlineKeyboardButton("🏆 排行榜", callback_data="rank")],
        [InlineKeyboardButton("🧾 最近记录", callback_data="history")]
    ])

def is_admin(user_id):
    return user_id == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    text = (
        "🎲 <b>猜数字小游戏</b>\n\n"
        f"欢迎你，{user.first_name or '玩家'}！\n"
        f"当前积分：<b>{balance(user.id)}</b>\n\n"
        "选择 1、2、3 中的一个数字，设置下注积分，立即开奖。\n"
        "本机器人仅使用虚拟积分，不支持充值或提现。"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = probabilities()
    await update.effective_message.reply_text(
        "📜 <b>游戏规则</b>\n\n"
        "1. 每次选择数字 1、2、3 之一。\n"
        f"2. 每次下注范围：{MIN_BET}–{MAX_BET} 积分。\n"
        "3. 猜中数字 1/2/3，分别返还下注额的 1/2/3 倍（含本金）。\n"
        "4. 猜错则扣除本次下注。\n"
        f"5. 当前开奖概率：数字1 {p[0]}% / 数字2 {p[1]}% / 数字3 {p[2]}%。\n"
        "6. 这是虚拟积分娱乐测试，不涉及充值、提现或现金兑换。",
        parse_mode="HTML", reply_markup=main_keyboard()
    )

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    await update.effective_message.reply_text(
        f"💰 你的积分余额：<b>{balance(user.id)}</b>",
        parse_mode="HTML", reply_markup=main_keyboard()
    )

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user = q.from_user
    ensure_user(user)
    if q.data == "balance":
        await q.edit_message_text(
            f"💰 你的积分余额：<b>{balance(user.id)}</b>",
            parse_mode="HTML", reply_markup=main_keyboard()
        )
    elif q.data == "rules":
        p = probabilities()
        await q.edit_message_text(
            "📜 <b>游戏规则</b>\n\n"
            f"下注范围：{MIN_BET}–{MAX_BET} 积分\n"
            "猜中 1/2/3 分别返还下注额的 1/2/3 倍（含本金）；猜错扣除下注。\n"
            f"当前开奖概率：1={p[0]}%，2={p[1]}%，3={p[2]}%。\n"
            "仅供虚拟积分测试，不支持充值或提现。",
            parse_mode="HTML", reply_markup=main_keyboard()
        )
    elif q.data == "play":
        if not enabled():
            await q.edit_message_text("⛔ 游戏暂时关闭。", reply_markup=main_keyboard())
            return
        context.user_data.pop("guess", None)
        await q.edit_message_text(
            f"🎯 请选择数字：\n当前积分：{balance(user.id)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("1️⃣ 数字 1（1倍）", callback_data="guess:1"),
                InlineKeyboardButton("2️⃣ 数字 2（2倍）", callback_data="guess:2"),
                InlineKeyboardButton("3️⃣ 数字 3（3倍）", callback_data="guess:3")
            ], [InlineKeyboardButton("返回菜单", callback_data="menu")]])
        )
    elif q.data.startswith("guess:"):
        if not enabled():
            await q.edit_message_text("⛔ 游戏暂时关闭。", reply_markup=main_keyboard())
            return
        guess = int(q.data.split(":")[1])
        context.user_data["guess"] = guess
        await q.edit_message_text(
            f"你选择了数字 <b>{guess}</b>。\n请输入下注积分（{MIN_BET}–{MAX_BET} 的整数）。\n"
            f"当前余额：{balance(user.id)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("取消", callback_data="menu")]])
        )
        context.user_data["await_bet"] = True
    elif q.data == "history":
        rows = conn.execute(
            "SELECT guess,result,bet,payout,balance_after,created_at FROM rounds WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (user.id,)
        ).fetchall()
        if not rows:
            msg = "你还没有游戏记录。"
        else:
            lines = ["🧾 <b>最近 10 次记录</b>"]
            for r in rows:
                outcome = "中奖" if r["payout"] > 0 else "未中"
                lines.append(f"猜{r['guess']} / 开{r['result']} · 下注{r['bet']} · 返还{r['payout']} · {outcome}")
            msg = "\n".join(lines)
        await q.edit_message_text(msg, parse_mode="HTML", reply_markup=main_keyboard())
    elif q.data == "rank":
        rows = conn.execute(
            "SELECT username,points FROM users ORDER BY points DESC LIMIT 10"
        ).fetchall()
        lines = ["🏆 <b>积分排行榜</b>"]
        for i, r in enumerate(rows, 1):
            name = (r["username"] or "玩家").replace("<", "").replace(">", "")
            lines.append(f"{i}. {name} — {r['points']} 积分")
        await q.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=main_keyboard())
    elif q.data == "menu":
        context.user_data.pop("await_bet", None)
        context.user_data.pop("guess", None)
        await q.edit_message_text("主菜单：", reply_markup=main_keyboard())

async def handle_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("await_bet"):
        return
    user = update.effective_user
    ensure_user(user)
    raw = (update.effective_message.text or "").strip()
    if not raw.isdigit():
        await update.effective_message.reply_text(f"请输入整数下注额（{MIN_BET}–{MAX_BET}）。")
        return
    bet = int(raw)
    if bet < MIN_BET or bet > MAX_BET:
        await update.effective_message.reply_text(f"下注范围是 {MIN_BET}–{MAX_BET} 积分，请重新输入。")
        return
    guess = context.user_data.get("guess")
    if guess not in (1, 2, 3):
        context.user_data["await_bet"] = False
        await update.effective_message.reply_text("本次选择已失效，请重新开始。", reply_markup=main_keyboard())
        return
    if not enabled():
        context.user_data["await_bet"] = False
        await update.effective_message.reply_text("游戏暂时关闭。", reply_markup=main_keyboard())
        return

    # Atomic balance check/debit/settlement avoids double spending.
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT points FROM users WHERE user_id=?", (user.id,)).fetchone()
        current = int(row["points"]) if row else 0
        if current < bet:
            conn.rollback()
            await update.effective_message.reply_text(
                f"积分不足。当前余额 {current}，本次下注 {bet}。",
                reply_markup=main_keyboard()
            )
            return
        result = draw_number()
        payout = bet * guess if guess == result else 0
        new_balance = current - bet + payout
        conn.execute("UPDATE users SET points=?,username=? WHERE user_id=?",
                     (new_balance, user.username or user.full_name or "", user.id))
        conn.execute(
            "INSERT INTO rounds(user_id,guess,result,bet,payout,balance_after,created_at) VALUES(?,?,?,?,?,?,?)",
            (user.id, guess, result, bet, payout, new_balance, now())
        )
        conn.commit()
    except Exception:
        conn.rollback()
        log.exception("settlement failed")
        await update.effective_message.reply_text("结算失败，请稍后再试；未确认前不要重复提交。")
        return
    finally:
        context.user_data["await_bet"] = False
        context.user_data.pop("guess", None)

    if guess == result:
        net = payout - bet
        result_text = f"🎉 <b>猜中了！</b>\n开奖结果：{result}\n返还：{payout} 积分\n本次净收益：+{net} 积分"
    else:
        result_text = f"😅 <b>没猜中</b>\n你猜：{guess}\n开奖结果：{result}\n本次损失：{bet} 积分"
    await update.effective_message.reply_text(
        f"{result_text}\n\n💰 当前余额：<b>{new_balance}</b>",
        parse_mode="HTML", reply_markup=main_keyboard()
    )

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("无权限。")
        return
    await update.effective_message.reply_text(
        "🛠 管理员命令：\n"
        "/prob 34 33 33 — 设置数字1/2/3概率，总和必须100\n"
        "/addpoints 用户ID 数量 — 增加积分\n"
        "/setpoints 用户ID 数量 — 设置积分\n"
        "/game_on — 开启游戏\n"
        "/game_off — 关闭游戏\n"
        "/stats — 查看统计\n"
        "/admin — 显示本帮助"
    )

async def admin_prob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.effective_message.reply_text("无权限。")
    try:
        vals = [int(x) for x in context.args]
        if len(vals) != 3 or any(x < 0 for x in vals) or sum(vals) != 100:
            raise ValueError()
        set_setting("probabilities", ",".join(map(str, vals)))
        await update.effective_message.reply_text(
            f"已设置开奖概率：数字1 {vals[0]}%，数字2 {vals[1]}%，数字3 {vals[2]}%。\n"
            "此设置会显示在玩家游戏规则中。"
        )
    except ValueError:
        await update.effective_message.reply_text("格式：/prob 34 33 33（总和必须为100）")

async def admin_points(update: Update, context: ContextTypes.DEFAULT_TYPE, set_mode=False):
    if not is_admin(update.effective_user.id):
        return await update.effective_message.reply_text("无权限。")
    try:
        uid, amount = int(context.args[0]), int(context.args[1])
        if amount < 0 or amount > 10**9:
            raise ValueError()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT points FROM users WHERE user_id=?", (uid,)).fetchone()
        if not row:
            conn.rollback()
            return await update.effective_message.reply_text("找不到该用户。用户需先 /start。")
        if set_mode:
            new = amount
        else:
            new = int(row["points"]) + amount
        conn.execute("UPDATE users SET points=? WHERE user_id=?", (new, uid))
        conn.commit()
        await update.effective_message.reply_text(f"已更新用户 {uid} 的积分：{new}")
    except (ValueError, IndexError):
        await update.effective_message.reply_text("格式：/addpoints 用户ID 数量 或 /setpoints 用户ID 数量")
    except Exception:
        conn.rollback()
        log.exception("admin points failed")
        await update.effective_message.reply_text("操作失败。")

async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_points(update, context, False)

async def setpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_points(update, context, True)

async def game_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.effective_message.reply_text("无权限。")
    set_setting("game_enabled", "1")
    await update.effective_message.reply_text("游戏已开启。")

async def game_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.effective_message.reply_text("无权限。")
    set_setting("game_enabled", "0")
    await update.effective_message.reply_text("游戏已关闭。")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.effective_message.reply_text("无权限。")
    users = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(points),0) p FROM users").fetchone()
    rounds = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(bet),0) b, COALESCE(SUM(payout),0) p FROM rounds").fetchone()
    p = probabilities()
    await update.effective_message.reply_text(
        f"用户数：{users['n']}\n积分总余额：{users['p']}\n"
        f"总局数：{rounds['n']}\n累计下注：{rounds['b']}\n累计返还：{rounds['p']}\n"
        f"概率：1={p[0]}% / 2={p[1]}% / 3={p[2]}%\n"
        f"游戏状态：{'开启' if enabled() else '关闭'}"
    )

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("balance", show_balance))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("prob", admin_prob))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("setpoints", setpoints))
    app.add_handler(CommandHandler("game_on", game_on))
    app.add_handler(CommandHandler("game_off", game_off))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bet))
    log.info("猜数字机器人启动，数据库：%s", DB_PATH)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=False)
    try:
        import asyncio
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
