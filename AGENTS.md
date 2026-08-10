# Aegis V4 — SMC Signal Scanner

> **Aturan utama ada di [CLAUDE.md](CLAUDE.md) — baca itu dulu.**
> Ringkasnya: Aegis hanya memberi sinyal, tidak pernah mengeksekusi order, dan
> tidak punya scoring atau threshold apa pun. Aturan pertama ditegakkan otomatis
> oleh `tests/test_no_execution.py`.

## Overview

Aegis memindai perpetual **Hyperliquid** dengan Smart Money Concepts murni dan
melaporkan setup yang ditemukannya. Tidak ada indikator teknikal, tidak ada
sistem skor, tidak ada ambang — hanya **price action dan struktur pasar**.

## Urutan ICT — lima tahap, semuanya wajib

Dua timeframe punya **peran berbeda**. HTF menyediakan zona, LTF memberi
konfirmasi. Menuntut MSS di keduanya adalah kesalahan sebelumnya — itu meminta
HTF mengerjakan tugas LTF, dan hasilnya menolak semua kandidat.

| # | Tahap | Timeframe |
|---|-------|-----------|
| 1 | **POI** — FVG belum termitigasi | HTF |
| 2 | **Retracement** — harga benar-benar kembali ke zona itu | LTF |
| 3 | **Sweep** — likuiditas disapu **di dalam POI**, lalu direbut kembali | LTF |
| 4 | **MSS** — pergeseran struktur yang membreak sweep tadi | LTF |
| 5 | **Entry** — FVG segar di pita **OTE 61.8–78.6%** dari leg MSS | LTF |

Setiap tahap biner, diperiksa berurutan, dan penolakan selalu menyebut tahap
mana yang gagal — jadi setup yang tidak muncul selalu bisa dijelaskan.

**Confluence di sini bukan tally.** Ia berarti dua timeframe menjalankan peran
masing-masing dengan benar, bukan dua poin yang dijumlahkan.

## Level datang dari struktur

```
entry   FVG di zona OTE
stop    di belakang sweep — level yang kalau tembus, tesis reversal batal
target  swing berlawanan terdekat (likuiditas yang dituju harga)
```

**R adalah keluaran, bukan masukan.** Ia hasil dari jarak antar swing, bukan
angka yang ditetapkan lebih dulu lalu dipaksakan ke chart. `rr_target: 3.0`
hanya cadangan untuk saat tidak ada swing berlawanan dalam jangkauan.

Harga di-snap ke tick size Hyperliquid, jadi level yang dikutip benar-benar bisa
dipasang di order book.

## Timeframe

Tiga kombinasi, HTF untuk struktur dan LTF untuk entry:

```
15m / 1m      1h / 5m      4h / 15m
```

Semua evaluasi hanya pada **candle tertutup** — candle berjalan dibuang.
Struktur yang dibaca dari bar yang masih bisa berubah adalah struktur yang bisa
batal.

## Pairs

Hyperliquid perpetual, quote USDC:

```
BTC  ETH  BNB  SOL  HYPE  XRP  LINK
```

Diukur pada data 4h: tujuh pair ini punya korelasi rata-rata **0.754**, setara
hanya **~1.3 pair independen**. HYPE satu-satunya yang benar-benar berbeda
(varians idiosinkratik 65% vs 17–20% lainnya). Menambah major lagi menaikkan
jumlah sinyal tanpa menambah informasi — dan menyamarkan kelemahan statistik,
karena n terlihat besar sementara kekuatan uji tidak ikut naik.

## Pelacakan hasil

Sinyal dilacak sampai selesai memakai harga publik, tanpa order apa pun:

```
PENDING  -> TRIGGERED    harga menyentuh entry
         -> INVALIDATED  SL tersentuh SEBELUM entry
         -> EXPIRED      basi tanpa tersentuh
TRIGGERED -> CLOSED      TP atau SL
```

**SL sebelum entry adalah INVALIDATED, bukan loss.** Trade-nya tidak pernah
terjadi; mencatatnya sebagai kekalahan mencemari win rate dengan setup yang
tidak pernah diambil. Dari klasifikasi backtest, **37% sinyal tidak pernah
terisi** — kalau semuanya dihitung kalah, angkanya salah total.

## Notifikasi

Heartbeat tiap 15 menit: 🟢 masih valid, 🔴 tidak valid. Dikirim berkala, bukan
hanya saat berubah — kalau hanya saat berubah, "tidak ada yang bergerak" dan
"bot mati" terlihat sama.

Dedup menekan pengulangan: state yang sama dinyatakan ulang sekali per
`repeat_interval_minutes` (default 60). Diukur pada simulasi 12 jam, 48
heartbeat menjadi 12 pesan. Interval ini **harus melebihi** periode heartbeat —
kalau sama, tiap pengulangan datang persis saat yang sebelumnya kedaluwarsa dan
tidak ada yang tertekan.

CRITICAL tidak pernah tertahan.

## File Structure

```
aegis/
├── analysis/
│   ├── scan_smc.py          # scanner live
│   ├── replay_smc.py        # replay candle tertutup
│   └── backtest/            # download_history, scan_history, simulate, report
├── strategy/aegis_strategy.py  # lima syarat SMC
├── indicators.py            # CHoCH, BOS, FVG, OB, swing, sweep, liquidity target
├── execution.py             # data pasar PUBLIK — tanpa API key, tanpa order
├── signal_monitor.py        # PENDING -> TRIGGERED -> CLOSED
├── notifications/
│   ├── telegram_bot.py      # format pesan
│   └── notifier.py          # dedup, severity, isolasi kegagalan
├── scan_lock.py             # lock instance tunggal
├── db.py                    # cache OHLCV + jurnal sinyal
├── check_status.py          # sinyal aktif vs harga sekarang
├── poll_scanner.py          # polling 60 detik
├── aegis_bot.py             # bot Telegram
└── aegis_config.json        # config SMC (tanpa kredensial)
```

## Commands

```bash
./aegis.sh scan               # pindai sekarang
./aegis.sh poll               # polling scanner
./aegis.sh bot                # bot Telegram
./aegis.sh status             # sinyal aktif vs harga
./aegis.sh backtest 30        # download -> scan -> simulate -> report
./aegis.sh test               # unit test

# TIDAK PERLU API KEY. Semua data yang dipakai Aegis bersifat publik.
```

## Don'ts

- **JANGAN** menambahkan eksekusi order dalam bentuk apa pun — tidak ada
  penempatan order, tidak ada API key, tidak ada mode paper.
- **JANGAN** menambahkan scoring, threshold, bobot, atau hitungan faktor.
  Syarat boleh biner (ada/tidak), tidak boleh bertingkat.
- **JANGAN** menambah indikator teknikal (RSI, MACD, EMA, Bollinger).
- **JANGAN** menonaktifkan verifikasi SSL untuk "memperbaiki" error koneksi.
- **JANGAN** menjalankan `aegis_bot.py` dan `poll_scanner.py` bersamaan.

## Status kejujuran

Backtest terakhir yang tercatat (versi Binance dengan scoring, n=79, 30 hari):
**win rate 17.7%, expectancy −0.291R**. Sapuan RR tidak menemukan target yang
profitable, dan pada RR 1.0 win rate 47.6% — praktis tidak bisa dibedakan dari
lemparan koin. Skor confluence tidak memisahkan menang dari kalah (p=1.000),
yang menjadi salah satu alasan sistem skor dibuang.

**Versi Hyperliquid murni ini belum punya angka sendiri.** Ia lebih ketat
(syarat MSS di dua timeframe, bukan salah satu), jadi hasilnya akan berbeda —
tapi ke arah mana belum diukur. Perlakukan keluarannya sebagai kandidat untuk
dianalisis sendiri, bukan rekomendasi.

Catatan untuk backtest di Hyperliquid: OHLCV 1m hanya tersedia ~3.5 hari ke
belakang, jadi kombo 15m/1m praktis tidak bisa di-backtest di sana. 15m mencapai
~30 hari dan 4h ~250 hari.
