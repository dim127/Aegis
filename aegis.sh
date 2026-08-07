#!/usr/bin/env bash
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -x "$DIR/venv/bin/python3" ]; then
    PY="$DIR/venv/bin/python3"
else
    PY="python3"
    echo "WARNING: venv/bin/python3 tidak ditemukan — pakai \$PATH python3." >&2
fi

usage() {
    cat <<'EOF'
Aegis V4 — SMC signal scanner (tidak mengeksekusi order)

  ./aegis.sh scan               Full SMC scan (7 pair × 3 combo)
  ./aegis.sh poll               Polling scanner (60 detik, pakai lock)
  ./aegis.sh bot                Telegram bot (pakai lock sama)
  ./aegis.sh status             Sinyal aktif vs harga sekarang
  ./aegis.sh backtest [days=30] Download → scan → simulate → report
  ./aegis.sh edge [days=30]     Uji apakah tiap faktor benar-benar punya edge
  ./aegis.sh test               Jalankan seluruh unit test
  ./aegis.sh help               Tampilkan daftar ini
EOF
}

run() {
    "$PY" "$@"
}

case "${1:-}" in
    scan)      run analysis/scan_smc.py ;;
    poll)      run poll_scanner.py ;;
    bot)       run aegis_bot.py ;;
    status)    run check_status.py ;;
    edge)      run analysis/backtest/factor_edge.py --days "${2:-30}" ;;
    backtest)
        days="${2:-30}"
        run analysis/backtest/download_history.py --days "$days" || exit 1
        run analysis/backtest/scan_history.py --days "$days" || exit 1
        run analysis/backtest/simulate.py --days "$days" || exit 1
        run analysis/backtest/report.py --days "$days" || exit 1
        ;;
    test)      run -m unittest discover -s tests ;;
    help|"")   usage ;;
    *)
        echo "Perintah tidak dikenal: $1" >&2
        usage
        exit 1
        ;;
esac
