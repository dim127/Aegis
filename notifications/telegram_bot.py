from datetime import datetime

DATE_FMT = "%Y-%m-%d %H:%M:%S"


def fmt_price(price, reference=None) -> str:
    """Decimals scaled to magnitude — a flat 2dp renders XRP as '1.06'.

    Pass `reference` (usually the entry) so every price in one setup shares the
    same decimals; otherwise a TP below $1 gets more digits than its entry.
    """
    if price is None:
        return "?"
    magnitude = abs(reference if reference is not None else price)
    if magnitude >= 1000:
        decimals = 2
    elif magnitude >= 10:
        decimals = 3
    elif magnitude >= 1:
        decimals = 4
    else:
        decimals = 6
    return f"{price:.{decimals}f}"


def format_setup_message(setup: dict) -> str:
    emoji = "\U0001f7e2" if setup["direction"] == "long" else "\U0001f534"
    direction = "LONG" if setup["direction"] == "long" else "SHORT"
    base = setup.get("base", "???")
    ts = setup.get("timestamp", datetime.now())
    ts_str = str(ts) if not hasattr(ts, "strftime") else ts.strftime(DATE_FMT)

    entry = setup["entry"]
    lines = [
        f"{emoji} *{base} {direction}* · {setup.get('tf_combo', '15m/1m')}",
        "```",
        f"Entry  {fmt_price(entry)}",
        f"SL     {fmt_price(setup['sl'], entry)}   ({setup.get('risk_pct', 0):.2f}%)",
        f"TP     {fmt_price(setup['tp'], entry)}   ({setup['rr']:.2f}R)",
        "```",
        "",
        f"1. {setup.get('poi_label', '')}",
        f"2. {setup.get('sweep_label', '')}",
        f"3. {setup.get('mss_label', '')}",
        f"4. {setup.get('ote_label', '')}",
        f"5. {setup.get('fvg_label', '')}",
        "",
        f"_{ts_str}_",
    ]
    return "\n".join(lines)



def format_heartbeat(report: dict) -> str:
    """Periodic status of every live signal: green still valid, red finished.

    Sent on a timer so silence is never ambiguous — no message would otherwise
    mean the same thing whether nothing changed or the bot had died.
    """
    now = datetime.now().strftime("%H:%M")
    valid = report.get("valid") or []
    invalid = report.get("invalid") or []

    if not valid and not invalid:
        return f"\U0001f4e1 *Heartbeat* {now}\n_Tidak ada sinyal aktif._"

    lines = [f"\U0001f4e1 *Heartbeat* {now}"]

    if valid:
        lines += ["", f"\U0001f7e2 *Masih valid* ({len(valid)})"]
        for s in valid:
            entry = s["entry"]
            progress = s.get("progress_r")
            if s.get("status") == "TRIGGERED":
                state = f"berjalan {progress:+.2f}R" if progress is not None else "berjalan"
            else:
                state = "menunggu entry"
            lines.append(
                f"  {_side(s)} *{_base(s)}* {s.get('tf_combo', '')} · {state}"
            )
            lines.append(
                f"     harga {fmt_price(s['price'], entry)} · entry {fmt_price(entry)}"
            )

    if invalid:
        lines += ["", f"\U0001f534 *Tidak valid* ({len(invalid)})"]
        for s in invalid:
            realized = s.get("realized_r")
            tail = f" · {realized:+.2f}R" if realized is not None else ""
            lines.append(
                f"  {_side(s)} *{_base(s)}* {s.get('tf_combo', '')} · "
                f"{s.get('reason', s.get('status', '?'))}{tail}"
            )

    return "\n".join(lines)


def _base(signal: dict) -> str:
    return str(signal.get("pair", "?")).split("/")[0]


def _side(signal: dict) -> str:
    return "LONG " if signal.get("direction") == "long" else "SHORT"



def format_no_trade_message() -> str:
    return f"\u2014 Tidak ada setup. _{datetime.now().strftime('%H:%M')}_"


def format_scan_banner(num_setups: int) -> str:
    now = datetime.now().strftime("%H:%M")
    label = "setup" if num_setups == 1 else "setup"
    return f"\U0001f50d *{num_setups} {label} ditemukan* \u00b7 {now}"


def format_status_message() -> str:
    import db

    lines = [
        "\U0001f4ca *Aegis V4 \u2014 Status*",
        "",
    ]
    # PENDING/TRIGGERED, not PLACED/OPEN — those were order statuses and no
    # longer exist, so this silently reported "none" however many signals were
    # live.
    signals = db.fetch_trade_journal("PENDING") + db.fetch_trade_journal("TRIGGERED")
    if signals:
        lines.append(f"*Sinyal aktif:* {len(signals)}")
        for s in signals:
            side = "LONG" if s.get("direction") == "long" else "SHORT"
            entry = s.get("entry")
            sl = s.get("sl")
            entry_str = f" @ ${fmt_price(entry)}" if entry else ""
            sl_str = f" SL ${fmt_price(sl, entry)}" if sl else ""
            lines.append(f"  {side} {s.get('pair', '?')} "
                         f"[{s.get('tf_combo', '?')}]{entry_str}{sl_str}")
    else:
        lines.append("_Tidak ada sinyal aktif._")

    summary = db.performance_summary()
    if summary["trades"]:
        lines += [
            "",
            "*Hasil tercatat:*",
            f"  {summary['trades']} sinyal, win rate {summary['win_rate']:.0f}%",
            f"  expectancy {summary['expectancy_r']:+.2f}R, total {summary['total_r']:+.2f}R",
        ]

    return "\n".join(lines)


def format_error_message(error: str) -> str:
    return (
        f"\u26a0\ufe0f *Aegis Error*\n"
        f"```\n{error}\n```"
    )


def format_help_message(interval: int) -> str:
    return (
        "\U0001f916 *Aegis*\n\n"
        "/scan \u2014 pindai sekarang\n"
        "/status \u2014 sinyal aktif\n"
        "/help \u2014 bantuan ini\n\n"
        f"Scan otomatis tiap {interval} menit, heartbeat tiap 15 menit.\n\n"
        "_Aegis memberi sinyal, tidak mengeksekusi order._"
    )


def format_start_message(interval: int) -> str:
    return (
        "\U0001f916 *Aegis V4 \u2014 SMC Scanner*\n\n"
        "Commands:\n"
        "/scan \u2014 Run SMC scan now\n"
        "/status \u2014 Show bot status\n"
        "/help \u2014 Show all commands\n\n"
        f"Auto-scan every {interval} min."
    )
