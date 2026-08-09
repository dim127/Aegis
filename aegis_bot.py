#!/usr/bin/env python3
import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from scan_lock import ScanLock
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.insert(0, os.path.dirname(__file__))
from strategy.aegis_strategy import AegisSMCStrategy
import signal_monitor
from notifications.telegram_bot import (
    format_setup_message,
    format_no_trade_message,
    format_scan_banner,
    format_error_message,
    format_status_message,
    format_help_message,
    format_start_message,
    format_heartbeat,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "aegis_config.json")


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


CONFIG = load_config()
SCAN_INTERVAL = CONFIG.get("telegram", {}).get("scan_interval_minutes", 15)
HEARTBEAT_INTERVAL = CONFIG.get("telegram", {}).get("heartbeat_interval_minutes", 15)

strategy = AegisSMCStrategy()


def run_scan():
    return strategy.analyze()


async def perform_scan(context: ContextTypes.DEFAULT_TYPE, is_manual=False):
    logger.info("Running scan...")
    try:
        results = await asyncio.get_event_loop().run_in_executor(None, run_scan)
        context.bot_data["last_scan"] = datetime.now()

        if not results:
            if not is_manual:
                return
            msg = format_no_trade_message()
        else:
            banner = format_scan_banner(len(results))
            setups = "\n\n".join(format_setup_message(s) for s in results)
            msg = f"{banner}\n\n{setups}"

        await context.bot.send_message(
            chat_id=CHAT_ID, text=msg, parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("Scan failed")
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=format_error_message(str(e)),
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("Failed to send error notification")


async def perform_heartbeat(context: ContextTypes.DEFAULT_TYPE):
    """Report which live signals still stand and which have resolved.

    Sent on a timer rather than only on change, so silence is never ambiguous:
    without it, "nothing happened" and "the bot died" look identical.
    """
    try:
        report = await asyncio.get_event_loop().run_in_executor(
            None, signal_monitor.check_all
        )
        if not report["valid"] and not report["invalid"]:
            return
        await context.bot.send_message(
            chat_id=CHAT_ID, text=format_heartbeat(report), parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("Heartbeat failed")
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID, text=format_error_message(str(e)), parse_mode="Markdown"
            )
        except Exception:
            logger.exception("Failed to send heartbeat error")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        format_start_message(SCAN_INTERVAL),
        parse_mode="Markdown",
    )


async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"\U0001f50d Scanning all {len(strategy.pairs)} pairs...")
    await perform_scan(context, is_manual=True)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_scan = context.bot_data.get("last_scan")
    msg = format_status_message()
    if last_scan:
        msg += f"\n\n_Last scan: {last_scan.strftime('%Y-%m-%d %H:%M:%S')}_"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        format_help_message(SCAN_INTERVAL),
        parse_mode="Markdown",
    )


def main():
    if not BOT_TOKEN or not CHAT_ID:
        logger.error(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env"
        )
        sys.exit(1)

    with ScanLock() as lock:
        if not lock.acquired:
            logger.error("Scan lock held (poll_scanner.py running) — exiting")
            sys.exit(1)

        app = Application.builder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("scan", scan_command))
        app.add_handler(CommandHandler("status", status_command))
        app.add_handler(CommandHandler("help", help_command))

        app.job_queue.run_repeating(
            perform_scan,
            interval=SCAN_INTERVAL * 60,
            first=10,
        )
        app.job_queue.run_repeating(
            perform_heartbeat,
            interval=HEARTBEAT_INTERVAL * 60,
            first=60,
        )

        logger.info(
            "Aegis V4 bot started. Scan interval: %d min | Chat: %s",
            SCAN_INTERVAL,
            CHAT_ID,
        )
        app.run_polling()


if __name__ == "__main__":
    main()
