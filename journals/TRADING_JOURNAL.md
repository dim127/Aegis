# 📘 TRADING JOURNAL & POST-MORTEM LESSONS

Dokumen ini mencatat evaluasi historis setup trading (baik yang Miss maupun Hit) untuk secara otomatis memperbarui algoritma dan aturan analisis di masa depan.

---

## ❌ Evaluasi & Pembelajaran Setup Terdaftar

### 1. Post-Mortem BTC Long Setup ($65,000)
- **Hasil:** Miss (Kena SL $64,650, lalu memantul naik tanpa eksposure)
- **Akar Masalah:** 
  - Stop Loss dipasang persis di garis support datar tanpa penyangga (*Liquidity Buffer*), sehingga terkena aksi *Stop Hunt / Liquidity Sweep* oleh pasar sebelum memantul naik.
- **Aturan Perbaikan (Rule #1):**
  - **ATR & Liquidity Buffer SL Rule:** Stop Loss wajib menyertakan penyangga minimal **1.5x ATR** atau ditempatkan di bawah *100x Liquidation Cluster Heatmap*, bukan pas di garis support.

### 2. Post-Mortem SOL Long Setup ($74.75)
- **Hasil:** Terisi ($74.75), Tertekan oleh penurunan serentak Bitcoin ($64,260).
- **Akar Masalah:**
  - Mengambil setup Altcoin (Solana) tanpa memperhitungkan potensi penembusan support pada Bitcoin (*BTC Spillover Effect*).
- **Aturan Perbaikan (Rule #2):**
  - **2-Tranche Entry / BTC Steering Filter:** Gunakan skema entri 2 tahap (50% Support Utama, 50% Liquidity Sweep Zone) dan pastikan BTC tidak sedang jatuh tajam.

---

## 🛡️ ATURAN EMAS SISTEM ANALISIS BARU (GOLDEN RULES)

1. 📏 **ATR & Liquidity Buffer SL:** SL wajib diberi penyangga 1.5x ATR atau ditaruh di bawah 100x Liquidation Magnet agar tidak terkena *jarum candle (wick)*.
2. 🔀 **2-Tranche Entry Strategy:** Gunakan alokasi 50% di Support Utama & 50% di Liquidity Dip Zone untuk mendapatkan rata-rata entry terbaik.
3. 🧭 **BTC Steering Filter:** BTC adalah pengemudi pasar. Selalu periksa kesehatan chart BTC sebelum masuk ke Altcoin.
4. 🛑 **Strict Risk Limit:** Maksimal resiko 1% - 2% dari total equity per trade.
