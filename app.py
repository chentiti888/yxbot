#!/usr/bin/env python3
# 单文件 Telegram 猜数字机器人
# 依赖：python-telegram-bot 22.x
# 可直接修改下方 BOT_TOKEN / ADMIN_ID，也可通过环境变量 BOT_TOKEN / ADMIN_ID 配置。
# 首次运行会自动创建同目录下的 guess_bot.sqlite3，用于保存积分和设置。

import os
import random
import sqlite3
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ===== 只需要配置这里 =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "把新机器人的BotFather Token填在这里")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # 填你的 Telegram 数字用户 ID
# ==========================

START_POINTS = 1000
MIN_BET = 10
BET_OPTIONS = (10, 50, 100, 200)
WIN_MULTIPLIER = 2.8  # 猜中后返还总额 = 下注 × 倍数（含本金）
DB_PATH = Path(__file__).resolve().with_name("guess_bot.sqlite3")

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("guess-bot")


def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                points INTEGER NOT NULL DEFAULT 1000,
                played INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            VALUES ('probabilities', '34,33,33')
        """)
        conn.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            VALUES ('game_on', '1')
        """)


def get_settings(conn):
    row = conn.execute(
        "SELECT value FROM settings WHERE key='probabilities'"
    ).fetchone()
    probs = [int(x) for x in row["value"].split(",")]
    row = conn.execute(
        "SELECT value FROM settings WHERE key='game_on'"
    ).fetchone()
    return probs, row["value"] == "1"


def ensure_user(user):
    with db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO users(user_id, username, points)
               VALUES (?, ?, ?)""",
            (user.id, user.username or user.full_name or "", START_POINTS),
        )
        conn.execute(
            "UPDATE users SET username=? WHERE user_id=?",
            (user.username or user.full_name or "", user.id),
        )
        row = conn.execute(
            "SELECT points, played, wins FROM users WHERE user_id=?",
            (user.id,),
        ).fetchone()
    return row


def main_keyboard():
    rows = [
        [InlineKeyboardButton(f"下注 {amount} 积分", callback_data=f"bet:{amount}")
         for amount in BET_OPTIONS[:2]],
        [InlineKeyboardButton(f"下注 {amount} 积分", callback_data=f"bet:{amount}")
         for amount in BET_OPTIONS[2:]],
        [InlineKeyboardButton("我的积分", callback_data="balance"),
         InlineKeyboardButton("游戏规则", callback_data="rules")],
    ]
    return InlineKeyboardMarkup(rows)


def guess_keyboard(amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("猜 1", callback_data=f"guess:{amount}:1"),
         InlineKeyboardButton("猜 2", callback_data=f"guess:{amount}:2"),
         InlineKeyboardButton("猜 3", callback_data=f"guess:{amount}:3")],
        [InlineKeyboardButton("返回下注", callback_data="home")],
    ])


def rules_text():
    return (
        "🎮 猜数字规则\n\n"
        "1. 先选择下注积分，再猜 1、2 或 3。\n"
        f"2. 猜中返还下注的 {WIN_MULTIPLIER:g} 倍（包含本金）；猜错扣除下注。\n"
        f"3. 最低下注 {MIN_BET} 积分；可选下注："
        + "、".join(map(str, BET_OPTIONS))
        + "。\n"
        "4. 积分仅为游戏内虚拟积分，不支持充值或提现。\n"
        "5. 开奖概率由管理员设置，可用 /prob 查看。"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = ensure_user(user)
    text = (
        f"🎲 欢迎来到猜数字！\n\n"
        f"当前积分：{row['points']}\n"
        "先选择下注金额，再猜一个数字。"
    )
    await update.effective_message.reply_text(text, reply_markup=main_keyboard())


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = ensure_user(update.effective_user)
    text = (
        f"👤 用户：{update.effective_user.full_name}\n"
        f"🪙 当前积分：{row['points']}\n"
        f"🎮 已玩局数：{row['played']}\n"
        f"🏆 猜中局数：{row['wins']}"
    )
    await update.effective_message.reply_text(text, reply_markup=main_keyboard())


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(rules_text(), reply_markup=main_keyboard())


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("无权限。")
        return
    await update.effective_message.reply_text(
        "管理员命令：\n"
        "/prob 34 33 33 — 设置 1/2/3 的开奖概率，总和必须为 100\n"
        "/prob — 查看当前概率\n"
        "/addpoints 用户ID 数量 — 增加积分\n"
        "/setpoints 用户ID 数量 — 设置积分\n"
        "/game_on — 开启游戏\n"
        "/game_off — 关闭游戏\n"
        "/stats — 查看统计"
    )


async def prob_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("无权限。")
        return
    with db() as conn:
        if len(context.args) == 0:
            probs, _ = get_settings(conn)
            await update.effective_message.reply_text(
                f"当前开奖概率：1={probs[0]}%，2={probs[1]}%，3={probs[2]}%"
            )
            return
        if len(context.args) != 3:
            await update.effective_message.reply_text("用法：/prob 34 33 33")
            return
        try:
            probs = [int(x) for x in context.args]
        except ValueError:
            await update.effective_message.reply_text("概率必须是整数。")
            return
        if any(x < 0 or x > 100 for x in probs) or sum(probs) != 100:
            await update.effective_message.reply_text("三个概率必须在 0–100 之间，且总和为 100。")
            return
        conn.execute(
            "UPDATE settings SET value=? WHERE key='probabilities'",
            (",".join(map(str, probs)),),
        )
    await update.effective_message.reply_text(
        f"已设置开奖概率：1={probs[0]}%，2={probs[1]}%，3={probs[2]}%"
    )


async def points_command(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("无权限。")
        return
    if len(context.args) != 2:
        await update.effective_message.reply_text(
            f"用法：/{mode} 用户ID 数量"
        )
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text("用户 ID 和数量必须是整数。")
        return
    if amount < 0 or (mode == "addpoints" and amount == 0):
        await update.effective_message.reply_text("数量不正确。")
        return
    with db() as conn:
        row = conn.execute(
            "SELECT points FROM users WHERE user_id=?", (target_id,)
        ).fetchone()
        if row is None:
            await update.effective_message.reply_text(
                "数据库里还没有这个用户。请让对方先发送 /start。"
            )
            return
        new_points = amount if mode == "setpoints" else row["points"] + amount
        conn.execute(
            "UPDATE users SET points=? WHERE user_id=?",
            (new_points, target_id),
        )
    await update.effective_message.reply_text(
        f"已处理用户 {target_id} 的积分，当前积分：{new_points}"
    )


async def addpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await points_command(update, context, "addpoints")


async def setpoints(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await points_command(update, context, "setpoints")


async def game_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, enabled: bool):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("无权限。")
        return
    with db() as conn:
        conn.execute(
            "UPDATE settings SET value=? WHERE key='game_on'",
            ("1" if enabled else "0",),
        )
    await update.effective_message.reply_text("游戏已开启。" if enabled else "游戏已关闭。")


async def game_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await game_toggle(update, context, True)


async def game_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await game_toggle(update, context, False)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text("无权限。")
        return
    with db() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS users, COALESCE(SUM(points), 0) AS points,
                   COALESCE(SUM(played), 0) AS played,
                   COALESCE(SUM(wins), 0) AS wins
            FROM users
        """).fetchone()
        probs, enabled = get_settings(conn)
    await update.effective_message.reply_text(
        f"📊 游戏统计\n用户数：{row['users']}\n"
        f"积分总额：{row['points']}\n总局数：{row['played']}\n"
        f"猜中局数：{row['wins']}\n游戏状态：{'开启' if enabled else '关闭'}\n"
        f"开奖概率：{probs[0]}% / {probs[1]}% / {probs[2]}%"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    row = ensure_user(user)
    data = query.data or ""

    if data == "home":
        await query.edit_message_text(
            f"🎲 猜数字\n当前积分：{row['points']}\n请选择下注金额。",
            reply_markup=main_keyboard(),
        )
        return

    if data == "balance":
        await query.edit_message_text(
            f"🪙 当前积分：{row['points']}\n已玩局数：{row['played']}\n"
            f"猜中局数：{row['wins']}",
            reply_markup=main_keyboard(),
        )
        return

    if data == "rules":
        await query.edit_message_text(rules_text(), reply_markup=main_keyboard())
        return

    if data.startswith("bet:"):
        try:
            amount = int(data.split(":")[1])
        except (ValueError, IndexError):
            return
        if amount not in BET_OPTIONS:
            await query.edit_message_text("下注金额无效。", reply_markup=main_keyboard())
            return
        with db() as conn:
            _, enabled = get_settings(conn)
        if not enabled:
            await query.edit_message_text("游戏暂时关闭，请稍后再来。", reply_markup=main_keyboard())
            return
        if row["points"] < amount:
            await query.edit_message_text(
                f"积分不足。你有 {row['points']} 积分。",
                reply_markup=main_keyboard(),
            )
            return
        await query.edit_message_text(
            f"本局下注：{amount} 积分\n请选择你猜的数字：",
            reply_markup=guess_keyboard(amount),
        )
        return

    if data.startswith("guess:"):
        parts = data.split(":")
        if len(parts) != 3:
            return
        try:
            amount, guess = int(parts[1]), int(parts[2])
        except ValueError:
            return
        if amount not in BET_OPTIONS or guess not in (1, 2, 3):
            await query.edit_message_text("本次操作无效。", reply_markup=main_keyboard())
            return

        # 事务中重新读取积分和设置，防止连续点击导致重复下注。
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user_row = conn.execute(
                "SELECT points FROM users WHERE user_id=?", (user.id,)
            ).fetchone()
            probs, enabled = get_settings(conn)
            if not enabled:
                conn.rollback()
                await query.edit_message_text("游戏暂时关闭。", reply_markup=main_keyboard())
                return
            if user_row is None or user_row["points"] < amount:
                conn.rollback()
                current = 0 if user_row is None else user_row["points"]
                await query.edit_message_text(
                    f"积分不足，当前积分：{current}",
                    reply_markup=main_keyboard(),
                )
                return

            # 先扣下注；开奖概率由管理员设置。
            result = random.choices((1, 2, 3), weights=probs, k=1)[0]
            new_points = user_row["points"] - amount
            won = result == guess
            payout = int(amount * WIN_MULTIPLIER) if won else 0
            new_points += payout
            conn.execute(
                "UPDATE users SET points=?, played=played+1, wins=wins+? WHERE user_id=?",
                (new_points, 1 if won else 0, user.id),
            )
            conn.commit()

        if won:
            result_text = (
                f"🎉 猜中了！开奖结果：{result}\n"
                f"下注：{amount}\n返还：{payout}（含本金）\n"
                f"本局净赚：{payout - amount}\n剩余积分：{new_points}"
            )
        else:
            result_text = (
                f"😅 没猜中，开奖结果：{result}\n"
                f"本局扣除：{amount}\n剩余积分：{new_points}"
            )
        await query.edit_message_text(result_text, reply_markup=main_keyboard())
        return


def main():
    if not BOT_TOKEN or BOT_TOKEN == "把新机器人的BotFather Token填在这里":
        raise SystemExit("请先在 app.py 顶部填写独立机器人的 BOT_TOKEN。")
    if ADMIN_ID <= 0:
        raise SystemExit("请先在 app.py 顶部填写你的 Telegram 数字用户 ID（ADMIN_ID）。")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("prob", prob_command))
    app.add_handler(CommandHandler("addpoints", addpoints))
    app.add_handler(CommandHandler("setpoints", setpoints))
    app.add_handler(CommandHandler("game_on", game_on))
    app.add_handler(CommandHandler("game_off", game_off))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(button_handler))
    log.info("Guess bot starting.")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
