# Aegis — Aturan Utama

> **Baca ini sebelum menyentuh kode apa pun.**

## Tujuan Aegis

Aegis adalah **pemberi sinyal setup**. Titik.

Ia memindai perpetual **Hyperliquid** dengan Smart Money Concepts murni,
menemukan setup, lalu **melaporkannya kepada pemiliknya**. Manusia yang memutuskan apakah setup itu
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

**JANGAN menambahkan scoring atau threshold.** Ini aturan kedua setelah
larangan eksekusi, dan alasannya sama tegasnya: skor membuat setup jadi
plin-plan. Sebuah angka 4/8 tidak berarti apa-apa secara khusus — ia hanya
mengundang perdebatan apakah 4 cukup. Setup di Aegis **memenuhi struktur atau
tidak**, dan setiap penolakan menyebut gerbang mana yang gagal.

Yang dilarang: hitungan faktor (`min_confluence`), bobot, ambang biaya, toleransi
kedekatan, skor gabungan. Yang boleh: syarat struktural biner — MSS ada atau
tidak, FVG segar atau sudah termitigasi, sweep terjadi atau tidak.

**Confluence di sini berarti struktural, bukan tally.** HTF *dan* LTF harus
sama-sama menunjukkan MSS searah. Itu dua pembacaan independen yang sepakat,
bukan dua poin yang dijumlahkan.

**Level datang dari struktur, bukan angka pilihan.** Entry di FVG midpoint, stop
di swing terakhir, target di swing berlawanan. **R adalah keluaran** — hasil dari
jarak antar swing, bukan angka yang ditetapkan lebih dulu.

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
