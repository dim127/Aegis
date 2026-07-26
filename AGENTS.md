# Aegis — AI Instruction & Guard Rules

## Project Overview
Aegis adalah crypto trading bot berbasis scoring multi-faktor. Bukan bot frekuensi tinggi — pendekatannya **disiplin, konservatif, berbasis konfirmasi teknikal + market structure**.

## Core Philosophy
| Aturan | Deskripsi |
|--------|-----------|
| **No entry tanpa skor ≥ 65** | Threshold mutlak. Tidak ada "feeling", FOMO, atau entry paksa. |
| **BTC Steering Filter wajib pass** | Jika BTC bearish (EMA9 < EMA21), altcoin long dilarang. |
| **Konfirmasi market structure** | Entry harus didukung OB/FVG/BOS dalam jarak 2× ATR. |
| **Fear & Greed sebagai sentimen** | Fear (<40) untuk long, Greed (>60) waspada short. |
| **Funding rate sebagai filter** | Funding terlalu tinggi (>1.5%) = short, negatif = long. |
| **Wait and scan dulu** | Jika tidak ada setup ≥65, tidak trade. Tidak ada paksaan. |
| **Risk management ketat** | SL 1.5× ATR, TP 3× ATR (1:2 RR). Trailing setelah profit 3%. |
| **15m entry filter** | Setelah skor ≥ 65, **wajib** konfirmasi OB/FVG/BOS di 15m sebelum entry. 15m bukan bagian scoring, hanya timing eksekusi. |

## Scoring Components (Total 100)
| Komponen | Max | Catatan |
|----------|-----|---------|
| Technical (trend, MACD, RSI, pullback) | 40 | Trend alignment + konfirmasi |
| Volume (spike vs average) | 20 | Lonjakan volume = konfirmasi |
| Market Structure (VWAP, BOS, OB, FVG) | 20 | Harga di atas VWAP + struktur |
| Derivatives (funding rate) | 20 | Funding wajar = bullish |
| Sentiment (Fear & Greed) | 10 | Fear = ekstrim = peluang |

## Multi-Timeframe Scoring (V2)
Skor gabung dari 3 timeframe dengan bobot:
- **1h**: 50%
- **4h**: 30%
- **1d**: 20%
- **Conflict discount**: -15% jika trend TF berbeda arah
- **Agreement bonus**: +10% jika semua TF searah
- Fungsi: `compute_multi_tf_scoring()` di `indicators.py`

## Don'ts (Guard Rules)
- **JANGAN** menurunkan threshold <65 untuk "membuat" setup.
- **JANGAN** menambah indikator baru tanpa persetujuan — sistem sudah matang.
- **JANGAN** mengubah scoring logic tanpa validasi backtest.
- **JANGAN** membuat AI "suggest trade" di bawah threshold.
- **JANGAN** menyentuh file `.env` atau credential.
- **JANGAN** menulis ulang strategi tanpa konteful penuh — pahami dulu.
- **JANGAN** memberikan saran entry tanpa scan aktual (jalankan scanner).
- **JANGAN** mengubah parameter risk (SL/TP multiplier, trailing, max open trades).

## Do's
- Jalankan scanner (`scan_altcoins.py`) untuk analisis nyata.
- Gunakan konteful yang ada — lihat `config.py`, `indicators.py`, `strategy/`.
- Jika user minta "analisis", jalankan scan dulu, baru interpretasi.
- Jika user minta perubahan kode, jelaskan dampak ke scoring dan risk.
- Prioritaskan konsistensi dan disiplin di atas apapun.

## File Structure
```
aegis/
├── analysis/          # Scanner scripts (scan_altcoins.py, scan_setups.py, scan_best_setup.py)
├── strategy/          # Trading strategy (base.py, aegis_strategy.py)
├── pairlist/          # Pairlist manager — static, volume-based, price/spread/volatility filters
├── risk/              # Risk management — StoplossGuard, MaxDrawdown, LowProfitPairs, Cooldown, PositionSizer
├── optimization/      # Hyperopt engine — parameter optimization, loss functions, space definitions
├── notifications/     # Notification system — Telegram, Webhook, Discord
├── monitors/          # Live position monitoring
├── web/               # Web dashboard & MCP server
├── backtesting/       # Backtesting engine + runner, comparison, data manager (caching)
├── indicators.py      # All TA + scoring logic (JANGAN UBAH tanpa konteful)
├── config.py          # Constants, pairs, thresholds
├── config_loader.py   # JSON config loader + env override
├── aegis_config.json  # Main config file
├── execution.py       # Order execution via CCXT
├── db.py              # Database
└── .env               # API keys (RAHASIA — jangan commit)
```

## Default Symbols
- `DEFAULT_SYMBOLS` = BTC, ETH, SOL
- `ALTCOIN_SYMBOLS` = ETH, BNB, SOL, XRP, ADA, AVAX, DOGE, LINK, DOT

## Commands
```bash
# Full altcoin scan (V3.1)
./venv/bin/python3 analysis/scan_altcoins.py

# Quick trend check (15m)
./venv/bin/python3 analysis/scan_setups.py

# Best setup summary
./venv/bin/python3 analysis/scan_best_setup.py

# Monitor AVAX limit order
./venv/bin/python3 monitors/monitor_avax.py

# Hyperliquid scan (perp markets)
./venv/bin/python3 analysis/scan_hyperliquid.py

# Hyperliquid pairlist test
./venv/bin/python3 -c "from pairlist.manager import PairlistManager; pm = PairlistManager({'pairlist_handlers': [{'method': 'HyperliquidMajorPairList', 'parameters': {}}]}); print(pm.refresh_pairlist())"

# Hyperliquid volume-based pairlist
./venv/bin/python3 -c "from pairlist.manager import PairlistManager; pm = PairlistManager({'pairlist_handlers': [{'method': 'HyperliquidVolumePairList', 'parameters': {'number_assets': 10, 'min_volume': 500000}}]}); tickers = __import__('ccxt').hyperliquid().fetch_tickers(); print(pm.refresh_pairlist(tickers=tickers))"

# Pairlist test
./venv/bin/python3 -c "from pairlist.manager import PairlistManager; pm = PairlistManager({'pairlist_handlers': [{'method': 'StaticPairList', 'parameters': {'pairs': ['BTC/USDT', 'ETH/USDT']}}]}); print(pm.refresh_pairlist())"

# Backtest with runner
./venv/bin/python3 -c "from backtesting.runner import BacktestRunner; from strategy.aegis_strategy import AegisStrategy; runner = BacktestRunner(); result = runner.run_strategy(AegisStrategy, ['BTC-USD', 'ETH-USD'], timerange='90d', interval='1h'); print(f'Profit: {result.total_profit:.2f}, Trades: {result.total_trades}, WR: {result.win_rate:.1f}%')"

# Hyperopt optimization
./venv/bin/python3 -c "from optimization.hyperopt import HyperoptEngine; from strategy.aegis_strategy import AegisStrategy; engine = HyperoptEngine(AegisStrategy, ['ETH-USD'], timerange='90d', interval='1h'); results = engine.optimize(epochs=20, verbose=True); print(results.summary())"
```

## Bahasa Inggris vs Indonesia
- Codebase dan komentar dalam **Bahasa Inggris**.
- Komunikasi dengan user dalam **Bahasa Indonesia**.
- Istilah teknikal (scoring, BOS, OB, FVG, SL, TP) tetap Inggris.

## Goals User
1. Sistem trading disiplin berbasis skor — bukan spekulasi.
2. Risk management ketat — preservasi modal > profit.
3. Skalabilitas ke live trading setelah cukup backtest.
4. Bot yang bisa jalan di VPS dengan monitoring web.
5. Tidak ada "pintu belakang" atau bypass aturan.

Jika ragu, **TANYA user dulu** sebelum bertindak. Jangan asumsi.
