"""Telegram message formatting.

Every message here is read on a phone, often at a glance, so the design bias
is one scannable line per fact rather than a complete report. The ICT
sequence (POI -> sweep -> MSS -> OTE) is compressed into two arrow-linked
lines instead of five numbered ones — the full reasoning is still there,
just not one bullet per step.
"""
from datetime import datetime

DATE_FMT = "%d %b %H:%M"


def fmt_price(price, reference=None) -> str:
    """Decimals scaled to magnitude, with thousands separators.

    Pass `reference` (usually the entry) so every price in one setup shares
    the same decimal count; otherwise a TP below $1 gets more digits than its
    entry. Without separators, BTC-sized numbers like 63910.5 are hard to
    parse at a glance — 63,910.50 is not.
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
    return f"{price:,.{decimals}f}"


def _base(signal: dict) -> str:
    return str(signal.get("pair", "?")).split("/")[0]


def _side(signal: dict) -> str:
    return "LONG" if signal.get("direction") == "long" else "SHORT"


def _distance_pct(signal: dict, price: float) -> float:
    """Percent gap between current price and the signal's entry."""
    entry = signal["entry"]
    return (price - entry) / entry * 100.0


def format_setup_message(setup: dict) -> str:
    emoji = "\U0001f7e2" if setup["direction"] == "long" else "\U0001f534"
    base = setup.get("base") or _base(setup)
    ts = setup.get("timestamp", datetime.now())
    ts_str = ts.strftime(DATE_FMT) if hasattr(ts, "strftime") else str(ts)
    entry = setup["entry"]

    tp_tag = "swing" if setup.get("tp_source") == "swing" else "fallback"

    lines = [
        f"{emoji} *{base} {_side(setup)}* · {setup.get('tf_combo', '')}",
        "```",
        f"Entry  {fmt_price(entry)}",
        f"SL     {fmt_price(setup['sl'], entry)}   ({setup.get('risk_pct', 0):.2f}%)",
        f"TP     {fmt_price(setup['tp'], entry)}   ({setup['rr']:.2f}R · {tp_tag})",
        "```",
        f"{setup.get('poi_label', '?')} → Sweep {fmt_price(setup.get('sweep_price', 0), entry)}",
        f"{setup.get('mss_label', '?')} → {setup.get('ote_label', '?')}",
        "",
        f"_{ts_str}_",
    ]
    return "\n".join(lines)


def format_heartbeat(report: dict) -> str:
    """Periodic status of every live signal: green still valid, red finished.

    Sent on a timer so silence is never ambiguous — no message would
    otherwise mean the same thing whether nothing changed or the bot had
    died. One line per signal, so the whole picture fits in a glance
    regardless of count.
    """
    now = datetime.now().strftime("%H:%M")
    valid = report.get("valid") or []
    invalid = report.get("invalid") or []

    if not valid and not invalid:
        return f"\U0001f4e1 *Heartbeat* {now}\n_Tidak ada sinyal aktif._"

    lines = [f"\U0001f4e1 *Heartbeat* {now} — {len(valid)} aktif, {len(invalid)} selesai"]

    for s in valid:
        if s.get("status") == "TRIGGERED":
            progress = s.get("progress_r")
            state = f"{progress:+.2f}R" if progress is not None else "berjalan"
        else:
            state = f"menunggu ({_distance_pct(s, s['price']):+.2f}%)"
        lines.append(f"\U0001f7e2 {_side(s)} {_base(s)} {s.get('tf_combo', '')} · {state}")

    for s in invalid:
        realized = s.get("realized_r")
        tail = f" {realized:+.2f}R" if realized is not None else ""
        reason = s.get("reason", s.get("status", "?"))
        lines.append(f"\U0001f534 {_side(s)} {_base(s)} {s.get('tf_combo', '')} · {reason}{tail}")

    return "\n".join(lines)


def format_no_trade_message() -> str:
    return f"— Tidak ada setup. _{datetime.now().strftime('%H:%M')}_"


def format_scan_banner(num_setups: int) -> str:
    now = datetime.now().strftime("%H:%M")
    return f"\U0001f50d *{num_setups} setup ditemukan* · {now}"


def format_status_message() -> str:
    import db

    lines = ["\U0001f4ca *Aegis — Status*"]

    # PENDING/TRIGGERED, not PLACED/OPEN — those were order statuses and no
    # longer exist, so this silently reported "none" however many signals
    # were live.
    signals = db.fetch_trade_journal("PENDING") + db.fetch_trade_journal("TRIGGERED")
    if signals:
        lines.append("")
        for s in signals:
            entry = s.get("entry")
            sl = s.get("sl")
            lines.append(
                f"{_side(s)} {_base(s)} {s.get('tf_combo', '?')} · "
                f"[{s.get('status', '?')}] entry {fmt_price(entry)} SL {fmt_price(sl, entry)}"
            )
    else:
        lines += ["", "_Tidak ada sinyal aktif._"]

    summary = db.performance_summary()
    if summary["trades"]:
        lines += [
            "",
            f"*Hasil:* {summary['trades']} sinyal · win rate {summary['win_rate']:.0f}% · "
            f"expectancy {summary['expectancy_r']:+.2f}R · total {summary['total_r']:+.2f}R",
        ]

    return "\n".join(lines)


def format_error_message(error: str) -> str:
    return f"⚠️ *Aegis Error*\n```\n{error}\n```"


def format_help_message(interval: int) -> str:
    return (
        "\U0001f916 *Aegis*\n\n"
        "/scan — pindai sekarang\n"
        "/status — sinyal aktif\n"
        "/help — bantuan ini\n\n"
        f"Scan tiap {interval} menit · heartbeat tiap 15 menit.\n\n"
        "_Aegis memberi sinyal, tidak mengeksekusi order._"
    )


def format_start_message(interval: int) -> str:
    return (
        "\U0001f916 *Aegis — ICT/SMC Scanner*\n\n"
        "/scan — pindai sekarang\n"
        "/status — sinyal aktif\n"
        "/help — bantuan\n\n"
        f"Scan otomatis tiap {interval} menit."
    )
