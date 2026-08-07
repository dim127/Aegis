# Aegis V4 — SMC Signal Scanner

> **Aturan utama ada di [CLAUDE.md](CLAUDE.md) — baca itu dulu.**
> Ringkasnya: Aegis hanya memberi sinyal, tidak pernah mengeksekusi order.
> Aturan itu ditegakkan otomatis oleh `tests/test_no_execution.py`.

## Overview
Aegis V4 adalah **pemberi sinyal** crypto berbasis **Smart Money Concepts (SMC)**.
Ia memindai setup dan melaporkannya — **tidak pernah mengeksekusi order**.

> ### Tidak ada eksekusi order
> Aegis hanya membaca **data publik** Binance. Tidak ada API key, tidak ada
> kredensial di disk, tidak ada jalur kode yang bisa menyentuh akun — bahkan
> secara tidak sengaja. Ini properti yang **disengaja**, bukan fitur yang belum
> dibuat: jalur eksekusi paling aman adalah yang tidak ada.
>
> Aegis memberi **informasi**, bukan perintah. Keputusan entry, sizing, dan
> eksekusi sepenuhnya di tangan Anda.

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

## Venue: Binance USDT-M futures

Sinyal dibaca dari Binance dan dieksekusi manual di Binance juga, jadi harga yang
dikutip Aegis **persis harga yang bisa dipasang** di order book Anda:

| Simbol Aegis | Simbol Binance | Tick |
|--------------|----------------|------|
| `BTC/USDT:USDT` | `BTCUSDT` | 0.1 |
| `BNB/USDT:USDT` | `BNBUSDT` | 0.01 |
| `XRP/USDT:USDT` | `XRPUSDT` | 0.0001 |

Karena itu entry/SL/TP di-snap ke tick size asli (`quantize_price`) — angka seperti
`592.05` bisa langsung disalin ke form limit order tanpa ditolak exchange.

Asumsi biaya di `risk.costs` juga memakai tarif Binance VIP0: maker **0.02%**,
taker **0.04%**. Kalau Anda membayar fee dengan BNB (diskon 10%), biaya nyata lebih
rendah dari model — jadi gate biaya bersifat **konservatif**, menolak sedikit lebih
banyak setup daripada seharusnya. Itu arah kesalahan yang aman.

**Kenapa Binance, bukan Hyperliquid** (diuji 2026-08-07): kebutuhan utama sekarang
adalah mencari edge, dan itu butuh history sedalam mungkin. OHLCV 1m di Hyperliquid
hanya ~3.5 hari — kombo 15m/1m tidak akan bisa di-backtest sama sekali. Funding 21
hari vs 166 hari di Binance; open interest dan long/short ratio tidak punya history.
Hyperliquid tetap kandidat cadangan kalau ISP suatu saat memblokir `fapi.binance.com`
(`www.binance.com` dan `demo-fapi.binance.com` sudah diblokir).

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
├── market_metrics.py        # Long/Short, open interest, funding, liquidation cluster
├── execution.py             # Data pasar PUBLIK via CCXT — tanpa API key, tanpa order
├── scan_lock.py             # Single-instance lock (bot vs poll_scanner)
├── db.py                    # OHLCV cache + signals + positioning history
├── check_status.py          # Sinyal aktif vs harga sekarang
├── poll_scanner.py          # Polling scanner (60 detik, pakai lock)
├── aegis_bot.py             # Telegram bot (pakai lock sama)
├── journals/                # Trading journal manual
└── aegis_config.json        # SMC config (tidak ada kredensial)
```

## Commands
```bash
# Shortcut (otomatis pakai venv, bisa dijalankan dari mana saja)
./aegis.sh scan               # Full scan
./aegis.sh poll               # Polling scanner
./aegis.sh bot                # Telegram bot
./aegis.sh status             # Sinyal aktif vs harga sekarang
./aegis.sh backtest 30        # Backtest penuh
./aegis.sh edge 30            # Uji apakah tiap faktor punya edge
./aegis.sh test               # Unit tests

# TIDAK PERLU API KEY. Semua data yang dipakai Aegis bersifat publik.
# Kalau ada yang menyuruh mengisi kredensial untuk menjalankan scanner,
# itu keliru — scanner tidak punya jalur kode untuk menyentuh akun.

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

# Data posisi pasar (long/short, open interest, funding)
./venv/bin/python3 analysis/backtest/download_positioning.py --period 4h --open-interest --funding
```

## Don'ts
- **JANGAN** menambahkan eksekusi order dalam bentuk apa pun — tidak ada penempatan
  order, tidak ada API key, tidak ada mode paper. Aegis memberi informasi, titik.
  Kalau eksekusi otomatis diinginkan lagi, itu keputusan sadar pemiliknya, bukan
  sesuatu yang muncul diam-diam dari sebuah PR.
- **JANGAN** membuat "scoring" atau threshold buatan **tanpa bukti backtest**.
  Gate biaya (min stop distance) adalah kontrol *kualitas sinyal*, bukan scoring:
  dia menolak setup yang secara matematis tidak bisa profit setelah fee.
- **JANGAN** mengubah RR target < 1:3 tanpa data yang mendukung.
- **JANGAN** menonaktifkan verifikasi SSL (`verify=False`) untuk "memperbaiki" error
  koneksi. Error sertifikat pernah terjadi karena DNS dibajak Internet Positif —
  mematikan verifikasi justru mengirim data ke server pemfilter.
- **JANGAN** menjalankan `aegis_bot.py` dan `poll_scanner.py` bersamaan (pakai lock `.aegis_scan.lock`).

## Status kejujuran

Backtest terakhir (n=79, 30 hari, kombo 4h/15m + 1h/5m): **win rate 17.7%,
expectancy −0.291R**. Sapuan RR menunjukkan **tidak ada** target yang profitable,
dan pada RR 1.0 win rate 47.6% — praktis tidak bisa dibedakan dari lemparan koin.
Skor confluence juga tidak memisahkan menang dari kalah (p=1.000).

Artinya: **sinyal Aegis belum terbukti punya edge.** Perlakukan keluarannya sebagai
kandidat untuk dianalisis sendiri, bukan rekomendasi. Jalankan `./aegis.sh edge`
setiap kali menambah faktor baru — dan percayai hasilnya, termasuk saat hasilnya
mengatakan ide Anda tidak berguna.
