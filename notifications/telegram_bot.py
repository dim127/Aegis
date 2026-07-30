import json
import os
from datetime import datetime

DATE_FMT = "%Y-%m-%d %H:%M:%S"


def format_setup_message(setup: dict) -> str:
    emoji = "\U0001f7e2" if setup["direction"] == "long" else "\U0001f534"
    direction = "LONG" if setup["direction"] == "long" else "SHORT"
    base = setup.get("base", "???")
    ts = setup.get("timestamp", datetime.now())
    ts_str = str(ts) if not hasattr(ts, "strftime") else ts.strftime(DATE_FMT)

    lines = [
        f"{emoji} *{base} [{setup.get('tf_combo', '15m/1m')}] | {direction}*",
        f"```",
        f"Entry    ${setup['entry']:.2f}",
        f"SL       ${setup['sl']:.2f}",
        f"TP       ${setup['tp']:.2f}",
        f"RR       1:{setup['rr']:.2f}",
        f"Risk     ${setup['risk']:.2f}",
        f"Confl    {setup['confluence']}/5",
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

    lines.append(f"_Scan: {ts_str}_")
    return "\n".join(lines)


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
    lines = [
        "\U0001f4ca *Aegis V4 \u2014 Status*",
        "",
    ]
    pos_path = os.path.join(os.path.dirname(__file__), "..", "positions.json")
    if os.path.exists(pos_path):
        with open(pos_path) as f:
            data = json.load(f)
        trades = data.get("active_trades", {})
        if trades:
            lines.append(f"*Active Trades:* {len(trades)}")
            for name, t in trades.items():
                side = t.get("side", "?")
                sym = t.get("symbol", "?")
                entry = t.get("entry")
                entry_str = f" @ ${entry:.2f}" if entry else ""
                sl = t.get("sl")
                sl_str = f" SL ${sl:.2f}" if sl else ""
                lines.append(f"  {side} {sym}{entry_str}{sl_str}")
        else:
            lines.append("_No active trades._")
    else:
        lines.append("_No active trades._")

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
        "*SMC Rules:* 3/5 confluence, 1:4 RR, limit order at FVG"
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
