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

    lines = [
        f"{emoji} *{base} [{setup.get('tf_combo', '15m/1m')}] | {direction}*",
        f"```",
        f"Entry    ${fmt_price(setup['entry'])}",
        f"SL       ${fmt_price(setup['sl'], setup['entry'])}",
        f"TP       ${fmt_price(setup['tp'], setup['entry'])}",
        f"RR       1:{setup['rr']:.2f} (net 1:{setup.get('rr_net', setup['rr']):.2f})",
        f"Risk     ${fmt_price(setup['risk'], setup['entry'])} ({setup.get('risk_pct', 0):.2f}%)",
        f"Confl    {setup['confluence']}/8",
        f"```",
        f"",
        f"*HTF:* {setup.get('htf_bias_text', 'N/A')}",
        f"*LTF:* {setup.get('ltf_conf_text', 'N/A')}",
        f"*Action:* {setup.get('action', 'N/A')}",
        f"",
    ]

    reasons = setup.get("reasons")
    if reasons:
        lines.append(f"*Confluence Factors:*")
        for i, r in enumerate(reasons, 1):
            lines.append(f"  {i}. {r}")
        lines.append("")

    lines.extend(format_market_context(setup))

    lines.append(f"_Scan: {ts_str}_")
    return "\n".join(lines)


def format_market_context(setup: dict) -> list:
    """Observed market state around a setup.

    Kept visually separate from the confluence factors: those are what fired the
    setup, this is what helps you judge it. None of it filters anything.
    """
    ctx = setup.get("context") or {}
    if not ctx:
        return []

    entry = setup.get("entry")
    lines = ["*Konteks Pasar* _(data asli, bukan filter)_"]

    if ctx.get("open_interest") is not None:
        change = ctx.get("oi_change_24h_pct")
        suffix = ""
        if change is not None:
            suffix = f" ({change:+.2f}%/24j, {'dibangun' if change > 0 else 'diurai'})"
        lines.append(f"  • OI: {ctx['open_interest']:,.0f}{suffix}")

    if ctx.get("funding_bp") is not None:
        z = ctx.get("funding_z")
        side = "long bayar short" if ctx["funding_bp"] > 0 else "short bayar long"
        ztext = "" if z is None else f", z={z:+.2f}"
        lines.append(f"  • Funding: {ctx['funding_bp']:+.3f}bp — {side}{ztext}")

    if ctx.get("volume_ratio") is not None:
        lines.append(f"  • Volume: {ctx['volume_ratio']:.2f}x rata-rata")

    liq = ctx.get("liquidity") or {}
    if liq.get("bid_share") is not None:
        dom = "bid tebal" if liq["bid_share"] > 0.5 else "ask tebal"
        lines.append(f"  • Order book: {liq['bid_share']*100:.0f}% bid — {dom}")
    for key, label in (("bid_wall", "Dinding bid"), ("ask_wall", "Dinding ask")):
        wall = liq.get(key)
        if wall:
            lines.append(f"    {label}: ${fmt_price(wall['price'], entry)} "
                         f"({wall['dist_pct']:+.2f}%)")

    lines.append("")
    return lines


def format_no_trade_message() -> str:
    now = datetime.now().strftime(DATE_FMT)
    return (
        "\u274c *No Trade* \u2014 No valid SMC setup found.\n"
        f"_Scanned: {now}_"
    )


def format_scan_banner(num_setups: int) -> str:
    now = datetime.now().strftime(DATE_FMT)
    return (
        f"\U0001f50d *Aegis V4 \u2014 SMC Scan* ({now})\n"
        f"Setups: {num_setups}"
    )


def format_status_message() -> str:
    import db

    lines = [
        "\U0001f4ca *Aegis V4 \u2014 Status*",
        "",
    ]
    trades = db.fetch_trade_journal("PLACED") + db.fetch_trade_journal("OPEN")
    if trades:
        lines.append(f"*Active Trades:* {len(trades)}")
        for t in trades:
            side = "LONG" if t.get("direction") == "long" else "SHORT"
            sym = t.get("pair", "?")
            entry = t.get("entry")
            sl = t.get("sl")
            entry_str = f" @ ${fmt_price(entry)}" if entry else ""
            sl_str = f" SL ${fmt_price(sl)}" if sl else ""
            lines.append(f"  {side} {sym} [{t.get('status', '?')}]{entry_str}{sl_str}")
    else:
        lines.append("_No active trades._")

    summary = db.performance_summary()
    if summary["trades"]:
        lines += [
            "",
            "*Realized:*",
            f"  {summary['trades']} trades, {summary['win_rate']:.0f}% win rate",
            f"  {summary['expectancy_r']:+.2f}R expectancy, {summary['total_r']:+.2f}R total",
        ]

    return "\n".join(lines)


def format_error_message(error: str) -> str:
    return (
        f"\u26a0\ufe0f *Aegis Error*\n"
        f"```\n{error}\n```"
    )


def format_help_message(interval: int) -> str:
    return (
        "\U0001f916 *Aegis V4 \u2014 Commands*\n\n"
        "/scan \u2014 Run SMC scan immediately\n"
        "/status \u2014 Show open positions & status\n"
        "/help \u2014 Show this help\n\n"
        f"Auto-scan every {interval} min.\n"
        "*SMC Rules:* 3/8 confluence, 1:3 RR, limit order at FVG"
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
