# Aegis V4 — Pure SMC Strategy

## Overview
Aegis V4 adalah crypto trading bot berbasis **Smart Money Concepts (SMC)** murni.  
Tidak ada scoring system, tidak ada threshold buatan — hanya **price action + market structure**.

## Core Philosophy
| Aturan | Deskripsi |
|--------|-----------|
| **SMC-only** | Entry berdasarkan CHOCH + BOS + FVG + OB konfluensi. Tidak ada indikator tambahan. |
| **Limit order di FVG** | Entry hanya via limit order di FVG midpoint. Tidak ada market order entry. |
| **1:3 RR minimum** | Setiap setup wajib memiliki Risk-to-Reward minimum 1:3. |
| **Multi-TF confluence** | 15m/1h/4h untuk market structure, 1m/5m/15m untuk execution. Minimal 3 dari 8 faktor confluence. |
| **FVG freshness** | Hanya trade FVG yang belum termitigasi (price belum masuk gap). |
| **Once in position: hold to SL/TP** | Tidak ada trailing, tidak ada partial exit. Hanya SL atau TP. |
| **No doubt** | Entry sudah divalidasi, sekarang hold sampai SL/TP. |

## Confluence Factors (8 faktor)
| # | Faktor | Sumber | Sifat |
|---|--------|--------|-------|
| 1 | HTF struktur shift (CHOCH/BOS/BREAK) | 15m/1h/4h | Wajib (1 atau 2) |
| 2 | LTF CHOCH alignment | 1m/5m/15m | Wajib (1 atau 2) |
| 3 | LTF FVG fresh (belum mitigated) | 1m/5m/15m | Wajib |
| 4 | Order Block proximity (dalam 2× ATR) | HTF | Konfirmasi |
| 5 | Breakout candle (impulsive + volume) | LTF | Konfirmasi |
| 6 | Liquidity Sweep (harga menyapu swing sebelumnya + reversal) | LTF | Wajib |
| 7 | ~~Binance Long/Short 24h (contrarian)~~ | fapi.binance.com/futures/data | **NONAKTIF** — lihat bawah |
| 8 | Liquidation cluster (estimasi volume profile) | OHLCV lokal | Konfirmasi |

Aturan kelulusan:
- **Wajib**: Structure shift (faktor 1 ATAU 2) + FVG fresh (#3) + Liquidity Sweep (#6)
- **Minimal**: 3 dari 8 faktor total (`smc.min_confluence`)
- Semua setup yang lolos pasti punya structure shift + FVG + liquidity sweep
- Faktor 7 (long/short) bersifat **contrarian**: mendukung LONG saat mayoritas SHORT (`long_short_bias`), begitu sebaliknya
- Faktor 8 dihitung hanya jika cluster terdekat searah perjalanan harga berada dalam `cluster_proximity_pct` % (± cluster terdekat ≤ 3%) dari entry
- **Backtest**: faktor 7 **bisa** di-backtest (lihat bawah), faktor 8 ikut terhitung dari OHLCV cache

## Data Posisi Pasar (gratis, tanpa API key)

Semua dari endpoint `fapi.binance.com/futures/data`, disimpan di tabel `positioning_history`
dengan lookup **as-of** (tidak pernah membaca observasi yang terbit setelah candle yang dinilai).

```bash
./venv/bin/python3 analysis/backtest/download_positioning.py --period 4h --open-interest
```

### Sumber Long/Short — `smc.market.long_short_source`
| Nilai | Endpoint | Arti |
|-------|----------|------|
| `top_position` **(default)** | topLongShortPositionRatio | Posisi tertimbang trader top — **berapa besar size** yang long |
| `top_account` | topLongShortAccountRatio | Jumlah akun trader top |
| `global_account` | globalLongShortAccountRatio | Semua akun retail, bobot sama — **berapa banyak orang** yang long |

Default diganti ke `top_position` karena `global_account` menghitung kepala, bukan uang.
Sampel bersamaan di BTC: global account **55.2%** long, top-trader position **61.4%** long —
dua cerita berbeda untuk sinyal contrarian.

### Koreksi penting
`scan_history.py` dulu hardcode `long_short = None` dengan alasan "tidak ada data historis".
**Itu salah** — Binance menyediakan ~30 hari. Akibatnya setiap sinyal backtest dinilai dengan
satu faktor lebih sedikit daripada sinyal live, jadi threshold apa pun yang di-tuning dari
backtest mis-kalibrasi terhadap sinyal yang sebenarnya di-trade.

### Retensi vs resolusi (openInterestHist)
| Period | Cakupan |
|--------|---------|
| 5m | 1.7 hari |
| 15m | 5.2 hari |
| 1h | 20.8 hari |
| **4h** | **30.8 hari** ← dipakai backtest |

Karena hanya 4h yang menutup window cache, **open interest dipakai sebagai ukuran regime**
(posisi sedang dibangun atau diurai), **bukan** konfirmasi sweep per-kejadian — sweep di 15m
selesai dalam beberapa candle, mustahil diukur resolusi 4h. Resolusi lebih halus akan membuatnya
tidak bisa di-backtest, yaitu jebakan yang persis baru diperbaiki di faktor 7.

`ls_long_pct` dan `oi_change_24h_pct` **diekspor ke CSV backtest tapi bukan gate** —
diukur dulu terhadap hasil sebelum dipakai memfilter. Hasil pengukurannya di bawah.

### Kenapa faktor 7 dinonaktifkan

Diuji dengan n=1071 observasi (bukan ~20 trade) + permutation test:

| Uji | Korelasi vs return 24j | p |
|-----|------------------------|---|
| Mentah | −0.1122 | 0.0000 |
| **Setelah demean per pair** | **+0.0021** | **0.945** |
| Paruh pertama | +0.0980 | 0.025 |
| Paruh kedua | −0.0898 | 0.041 |

Korelasi mentah yang "signifikan" **hilang total** setelah efek level per pair dibuang, dan
split-sample memberi tanda **berlawanan** — ciri noise, bukan sinyal.

Penyebabnya struktural: crowd perpetual **selalu** net long.

```
Sebaran ls_long_pct : min 54.1%  max 68.5%
Observasi < 50% long: 0 dari 1071
Faktor 7 menyala    : SHORT 1309x, LONG 0x
```

Karena syaratnya `crowd != direction`, faktor ini memberi **+1 confluence ke setiap short dan
tidak pernah ke long**. Itu bukan sinyal contrarian, melainkan **bias arah konstan** — dan
menjelaskan baseline 114 short vs 57 long.

Konsekuensinya `_rank()` juga diperbaiki: kunci utama sekarang `fvg_timestamp` (kesegaran
setup), bukan `confluence`, supaya bias konstan tidak otomatis memenangkan short di setiap
bentrokan long-vs-short.

**Open interest**: korelasi +0.076 (4j, p=0.014) / +0.092 (12j, p=0.002) / +0.051 (24j, p=0.108).
Tandanya **positif** — OI naik, harga naik. Itu momentum, bukan konfirmasi sweep. Efeknya
menjelaskan <1% variasi, jadi tetap sebagai kolom terukur saja.

> Semua ini **satu window 30 hari, satu regime turun**. Kesimpulan "tidak ada edge" berlaku
> untuk sampel ini, bukan kebenaran universal.

### Funding rate — satu-satunya yang menunjukkan sinyal nyata

Diuji **166 hari** (n=6446), bukan 30 hari, jadi mencakup beberapa regime.

| Uji | Hasil |
|-----|-------|
| Variasi dua arah | **32.8% negatif** (faktor 7: 0%) |
| Korelasi mentah | −0.0761 (p=0.0000) |
| **Setelah demean per pair** | **−0.0847 (p=0.0000)** ← **bertahan**, tidak kolaps |
| Arah per pair | **negatif di 7/7 pair** |

Hubungan quintile-nya **monotonik** — ini yang paling meyakinkan:

| Funding (demeaned) | Return 24j |
|--------------------|------------|
| sangat rendah (−0.798bp) | **+0.535%** |
| rendah (−0.075bp) | +0.092% |
| netral (+0.150bp) | −0.128% |
| tinggi (+0.453bp) | −0.174% |
| sangat tinggi (+0.824bp) | **−0.256%** |

Arahnya **contrarian**: funding tinggi (long bayar short) → return negatif → dukung SHORT.

**PERINGATAN — jangan diabaikan:**

| Periode | Korelasi | p |
|---------|----------|---|
| 1 (Feb–Apr) | −0.0953 | 0.0000 |
| 2 (Apr–Jun) | −0.1278 | 0.0000 |
| **3 (Jun–Agu)** | **+0.0607** | 0.0046 |

Periode ke-3 **berbalik tanda** — dan periode itulah yang mencakup window backtest 30 hari kita.
Jadi funding **belum** dijadikan faktor confluence. Ia diekspor sebagai `funding_bp` dan
`funding_z` ke CSV backtest supaya terus terukur sambil data bertambah.

`zscore_as_of()` memakai z-score relatif terhadap sejarah pair itu sendiri, **bukan** ambang
absolut — persis kesalahan yang membuat faktor 7 tidak pernah menyala untuk long.

## Market Structure — klasifikasi & window

`detect_structure()` memakai **dua lookback berbeda**, dan menyatukannya dulu adalah bug nyata:

| Lookback | Guna | Default |
|----------|------|---------|
| `window` | Swing mana yang dianggap **level yang dipecahkan** | 15 |
| `trend_window` | Rangkaian swing untuk menentukan **ada tren atau tidak** | `window × 2` (30) |

Dua swing per sisi tidak muat dalam 15 bar. Diukur di BTC 4h: tren hanya terdeteksi
**13.8%** dari bar pada window=15, versus **~43%** pada 30–40. Akibatnya `bullish_trend` /
`bearish_trend` hampir selalu False, jadi setiap break dilabeli BOS.

Klasifikasi (deskriptif, **bukan** filter):
- **CHOCH** — break melawan tren yang ada (reversal)
- **BOS** — break searah tren yang ada (continuation)
- **BREAK** — break tanpa tren yang terbentuk; bukan keduanya

Gate tetap memakai `bullish_break` / `bearish_break` mentah, jadi perilaku entry **tidak berubah**
oleh klasifikasi ini. Tujuannya supaya tiap jenis bisa **diukur** dulu sebelum ada yang difilter.

> Sebelum perbaikan: BREAK 140 / CHOCH 5 / BOS 0 (dari 145 sinyal).
> Sesudah: BREAK 85 / CHOCH 46 / BOS 14.

**Stop loss** di-anchor ke **swing terakhir** sebelum FVG (`liquidity_inflection`), bukan
rolling min/max 30 bar. Rolling extreme bukan level struktural — itu cuma harga terjauh yang
pernah disentuh, jadi jauh dari entry dan menggelembungkan R. Fallback ke rolling extreme kalau
tidak ada swing terkonfirmasi di window.

`latest_structure_event` dibatasi `max_bars_back=30`: tanpa itu, break 4h dari >2 minggu lalu
masih bisa meloloskan entry live.

## Risk Management
| Parameter | Value |
|-----------|-------|
| RR Target | 1:3 (`smc.rr_target`, tidak boleh < 3.0) |
| SL | Di belakang swing point terdekat (liquidity inflection) + **1.5× ATR Buffer** |
| TP | 3× risk dari entry |
| Position | Limit order di FVG midpoint |
| Harga | Di-snap ke **tick size exchange** (`price_to_precision`), bukan `round(x, 2)` |
| **Min stop distance** | Stop wajib ≥ `min_cost_multiple` × biaya round-trip (default 8 × 0.08% = **0.64%**). Setup dengan stop lebih rapat ditolak — fee memakan sebagian besar 1R |
| Risk per trade | `risk.risk_percent` dari equity akun (fallback `risk.capital`); **leverage tidak mengalikan risk** |
| Notional cap | `risk.max_notional_pct` (default 300% dari capital) |
| Fill window | Limit order dibatalkan setelah `fill_window_minutes` (default 60) |
| **Signal TTL** | Sinyal PENDING lebih tua dari `signal_ttl_minutes` (default 15) di-EXPIRED, tidak di-place |
| One position per pair | Satu posisi per pair; sinyal baru di-skip selama masih ada trade PLACED/OPEN di pair yang sama |
| Max concurrent | `risk.max_concurrent_positions` (default 3) — 7 major sangat berkorelasi |
| Kill switch | `risk.enabled: false` menghentikan semua placement (monitoring tetap jalan) |

### Cost model (`risk.costs`)
Round-trip = `maker_fee_pct` (limit entry) + `taker_fee_pct` (STOP_MARKET exit) + `slippage_pct`.
Default 0.02 + 0.04 + 0.02 = **0.08%**. Setiap setup melaporkan `rr_net` — RR setelah biaya.

> Dari 28 sinyal historis, **16 (57%) ditolak** gate ini — hampir semuanya combo 15m/1m
> dengan stop 0.08%–0.27%, di mana fee memakan 30–100% dari 1R.

## Outcome tracking
`trade_journal` menyimpan hasil nyata, bukan hanya niat:
`fill_price`, `fill_time`, `exit_price`, `exit_time`, `exit_reason`, `fees_paid`, `realized_r`,
plus `sl_order_id` / `tp_order_id` agar stop yang tersisa bisa di-cancel.
`db.performance_summary()` → win rate, expectancy R, total R. Tampil di `/status` dan `./aegis.sh status`.

## Pairs
Binance USDT-M futures (via CCXT `binanceusdm`):
- BTC/USDT:USDT
- ETH/USDT:USDT
- BNB/USDT:USDT
- SOL/USDT:USDT
- HYPE/USDT:USDT
- XRP/USDT:USDT
- LINK/USDT:USDT

## File Structure
```
aegis/
├── analysis/
│   ├── scan_smc.py          # SMC scanner (live)
│   ├── replay_smc.py        # Closed-candle replay
│   └── backtest/            # scan_history, simulate, report, download_history
├── strategy/aegis_strategy.py  # SMC strategy class
├── indicators.py            # SMC indicator functions (CHOCH, FVG, OB, BOS, etc.)
├── market_metrics.py        # Long/Short 24h + estimasi liquidation cluster
├── execution.py             # Order execution via CCXT (Binance futures)
├── trade_manager.py         # Place + monitor limit/SL/TP dari journal
├── scan_lock.py             # Single-instance lock (bot vs poll_scanner)
├── binance_credentials.json # Isi API key/secret Binance mainnet (tidak di-git)
├── binance_testnet_credentials.json  # API key/secret Binance Testnet (tidak di-git)
├── db.py                    # OHLCV cache + signals & trade journal
├── poll_scanner.py          # Polling scanner (60 detik, pakai lock)
├── aegis_bot.py             # Telegram bot (pakai lock sama)
├── journals/                # Trading journal
└── aegis_config.json        # Exchange & SMC config
```

## Commands
```bash
# Shortcut (otomatis pakai venv, bisa dijalankan dari mana saja)
./aegis.sh scan               # Full scan
./aegis.sh poll               # Polling scanner
./aegis.sh bot                # Telegram bot
./aegis.sh trade --once       # Eksekusi journal
./aegis.sh status             # Status trade aktif
./aegis.sh positions          # Posisi di exchange
./aegis.sh backtest --days 30 # Backtest penuh
./aegis.sh test               # Unit tests

# Isi API key Binance (opsional, hanya untuk eksekusi order)
# → isi .env (BINANCE_API_KEY / BINANCE_SECRET_KEY) ATAU binance_credentials.json,
#   tidak perlu sentuh aegis_config.json

# MODE TESTNET (uji eksekusi, uang palsu, data terpisah):
# 1. Buat key di https://testnet.binancefuture.com → isi .env
#    (BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_SECRET) ATAU binance_testnet_credentials.json
# 2. Set exchange.binance.testnet = true di aegis_config.json
# 3. Semua data otomatis pindah ke aegis_cache_testnet.db + aegis_signals_testnet.db
#    (harga testnet adalah simulasi — hasil scan beda dari live)
# 4. Kembalikan flag ke false untuk kembali ke mainnet

# Full SMC scan (7 pair × 3 combo: 15m/1m, 1h/5m, 4h/15m)
./venv/bin/python3 analysis/scan_smc.py

# Polling scanner (60 detik) — hanya satu scanner yang boleh jalan
./venv/bin/python3 poll_scanner.py

# Telegram bot
./venv/bin/python3 aegis_bot.py

# Download history untuk backtest (default 30 hari)
./venv/bin/python3 analysis/backtest/download_history.py --days 30
./venv/bin/python3 analysis/backtest/scan_history.py --days 30
./venv/bin/python3 analysis/backtest/simulate.py --days 30

# Eksekusi order dari journal (perlu API key Binance di config)
./venv/bin/python3 trade_manager.py --once
```

## Execution Flow
1. Scanner (`scan_smc.py` / bot / poll_scanner) → journal ke `aegis_signals.db` + antrian `trade_journal` (status PENDING)
   - Mode testnet: journal ke `aegis_signals_testnet.db` / `trade_journal` di `aegis_cache_testnet.db`
   - Dedup pakai identitas setup (pair + tf_combo + direction), **bukan** entry price — entry adalah
     FVG midpoint yang bergeser tiap scan
2. `reconcile()` saat startup → adopsi order yatim di exchange kalau proses mati saat placement
3. `trade_manager.py` → place limit entry, status PENDING → PLACED
4. Saat entry terisi → PLACED → OPEN, `fill_price` dicatat, **baru** SL/TP stop dipasang
   (stop reduce-only yang dipasang sebelum fill akan yatim kalau entry expired)
5. Position ditutup oleh SL/TP → stop sisanya di-cancel, `exit_price` + `realized_r` dicatat, status CLOSED
6. Tanpa API key Binance, journal tetap tercatat dan trade_manager hanya log (dormant)

**Safety:** `trade_manager` menolak jalan di mainnet tanpa flag `--live`, dan memegang lock
`.aegis_trade.lock` supaya dua proses tidak place order dari row PENDING yang sama.

## Don'ts
- **JANGAN** menambah indikator (RSI, MACD, EMA, Bollinger, dll) — SMC murni.
- **JANGAN** membuat "scoring" atau threshold buatan **tanpa bukti backtest**.
  Gate biaya (min stop distance) adalah kontrol *risk*, bukan scoring: dia menolak setup yang
  secara matematis tidak bisa profit setelah fee, bukan menebak arah.
- **JANGAN** market entry — selalu limit order di FVG.
- **JANGAN** mengubah RR target < 1:3.
- **JANGAN** menyentuh file `.env` atau credential.
- **JANGAN** trailing atau partial exit — hold to SL/TP.
- **JANGAN** menjalankan `aegis_bot.py` dan `poll_scanner.py` bersamaan (pakai lock `.aegis_scan.lock`).
