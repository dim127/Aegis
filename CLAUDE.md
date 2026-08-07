# Aegis — Aturan Utama

> **Baca ini sebelum menyentuh kode apa pun.**

## Tujuan Aegis

Aegis adalah **pemberi sinyal setup**. Titik.

Ia memindai pasar dengan Smart Money Concepts, menemukan setup, lalu
**melaporkannya kepada pemiliknya**. Manusia yang memutuskan apakah setup itu
layak diambil, berapa besar, dan kapan. Aegis tidak pernah memutuskan, dan tidak
pernah bertindak.

## Aturan yang tidak bisa ditawar

**JANGAN menambahkan eksekusi order dalam bentuk apa pun.**

Termasuk — dan ini bukan daftar lengkap, melainkan contoh dari hal-hal yang
pernah ada di sini dan sudah sengaja dihapus:

- Penempatan order (limit, market, stop, apa pun)
- Pembatalan atau modifikasi order
- Membaca saldo, posisi, atau equity akun
- API key, secret, kredensial exchange
- Mode testnet, demo, sandbox, atau paper trading
- Auto-sizing posisi yang langsung diteruskan ke exchange

Semua data yang dipakai Aegis bersifat **publik**. Tidak ada API key di disk.
Tidak ada jalur kode dari proses ini ke sebuah akun — bahkan secara tidak
sengaja. Itu **properti yang disengaja**, bukan fitur yang belum dibuat.

`tests/test_no_execution.py` menegakkan aturan ini secara otomatis. Kalau test
itu merah, **jangan melemahkan assertion-nya** — hapus kode eksekusi yang baru
ditambahkan. Menghapus file test itu sendiri hanya boleh dilakukan kalau pemilik
proyek menyatakan dengan kalimatnya sendiri bahwa ia menginginkan trading
otomatis kembali.

## Kenapa aturannya begitu

Dua alasan, keduanya berdasarkan bukti.

**Pertama, strateginya belum terbukti.** Backtest pertama yang pernah selesai
(n=79, 30 hari) memberi **win rate 17.7%, expectancy −0.291R**. Sapuan RR
menunjukkan tidak ada target yang profitable; pada RR 1.0 win rate 47.6% —
praktis tidak bisa dibedakan dari lemparan koin. Skor confluence bahkan tidak
memisahkan menang dari kalah (p=1.000). Menyambungkan uang sungguhan ke sinyal
tanpa edge yang terbukti menambah risiko tanpa menambah nilai.

**Kedua, ketiadaan adalah jaminan terkuat.** Selama ada jalur eksekusi, ia harus
dijaga: stop order yatim, sinyal basi yang antre, penempatan ganda, flag config
yang cuma satu edit jauhnya dari uang sungguhan. Semua itu pernah jadi bug nyata
di repo ini. Menghapus jalurnya memensiunkan seluruh kelas kegagalan itu
sekaligus — lebih kuat daripada flag `--live` atau kill switch mana pun.

## Cara bekerja di sini

**Ukur dulu, baru filter.** Setiap faktor baru diekspor sebagai kolom terukur di
backtest sebelum boleh menggerbang apa pun. Jalankan `./aegis.sh edge` dan
percayai hasilnya — termasuk saat hasilnya bilang ide Anda tidak berguna. Faktor
7 (long/short ratio) terlihat menjanjikan sampai diuji dengan benar; ternyata
noise, dan sekarang nonaktif.

**Sebut data tebakan sebagai tebakan.** `estimate_liquidation_clusters()` bukan
data likuidasi asli — Binance tidak menyediakannya tanpa API key. Ia menebak dari
volume profile. Dokumentasinya harus mengatakan itu, jangan sampai terbaca
seperti observasi.

**Konteks bukan confluence.** Data pasar yang dilampirkan ke setup (OI, funding,
volume, order book) adalah **informasi untuk pembaca**, bukan filter. Jangan
diam-diam mengubahnya jadi gate.

**Jangan matikan verifikasi SSL.** Error sertifikat pernah muncul di sini karena
DNS dibajak Internet Positif. `verify=False` bukan perbaikan — itu mengubah
pengaman menjadi kebocoran.

## Kalau diminta menambahkan eksekusi

Jangan langsung kerjakan. Tanyakan dulu, dan sampaikan dua hal di atas: bahwa
strateginya masih −0.291R, dan bahwa ketiadaan jalur eksekusi adalah pengaman
utamanya. Kalau setelah itu pemiliknya tetap menginginkannya, itu keputusan sadar
miliknya — dan bukan sesuatu yang muncul diam-diam dari sebuah refactor.

---

Detail teknis lengkap ada di [AGENTS.md](AGENTS.md).
