# iglead — Leaderboard Kompetitor Instagram

Tool CLI untuk memantau akun kompetitor di Instagram, menyimpan riwayatnya, dan
memeringkatkannya dengan skor komposit terbobot.

```
#       Akun               Skor  Follower   Growth   ER%  Interaksi  Post/mgg
-  ---  -----------------  ----  --------  -------  ----  ---------  --------
1    =  Kopi Senja         85.0     75.1K  +24.74%  5.63       4.2K       4.9
2    =  Dapur Umami        52.6    126.2K  +14.33%  3.10       3.9K       4.0
3   ▲1  Brand Saya (kita)  41.1     75.1K  +10.71%  3.97       3.0K       4.0
4   ▼1  Roti Bakar Malam   29.6    150.5K   +6.72%  2.20       3.3K       2.8
5    =  Nusantara Bites    15.0    220.4K   +2.43%  1.21       2.7K       1.9
```

Data diambil lewat **Instagram Graph API** (endpoint `business_discovery`) —
jalur resmi Meta untuk membaca metrik publik akun Business/Creator lain. Tidak
ada scraping, tidak ada login palsu, tidak ada akses ke data privat.

## Coba dulu tanpa kredensial

Ada data demo sintetis supaya Anda bisa melihat hasilnya sebelum mengurus token:

```bash
python demo/seed_demo.py
python -m iglead --config demo/competitors.demo.yml --db demo.db rank --compare-days 14
python -m iglead --config demo/competitors.demo.yml --db demo.db report -o demo_report.html
```

## Instalasi

```bash
pip install -e .        # menyediakan perintah `iglead`
```

Butuh Python 3.10+ dan PyYAML. Tanpa instalasi pun bisa dijalankan sebagai
`python -m iglead`.

## Setup Graph API

Ini bagian yang paling merepotkan, tapi cuma sekali.

1. **Akun Instagram harus Business atau Creator**, dan tertaut ke sebuah
   Facebook Page. Ini berlaku untuk akun Anda *dan* akun kompetitor yang ingin
   dipantau — akun personal atau privat tidak akan terbaca.
2. Buat app di [developers.facebook.com](https://developers.facebook.com), lalu
   tambahkan produk **Instagram Graph API**.
3. Di **Graph API Explorer**, buat token dengan scope:
   `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`,
   `pages_show_list`.
4. Ambil ID akun Instagram Business Anda:
   ```
   GET /me/accounts                                  -> catat {page-id}
   GET /{page-id}?fields=instagram_business_account  -> ini ID yang dipakai
   ```
5. Simpan keduanya:
   ```bash
   cp .env.example .env     # lalu isi IG_ACCESS_TOKEN dan IG_BUSINESS_ACCOUNT_ID
   ```
6. Uji koneksinya:
   ```bash
   iglead check
   ```

> Token hasil Graph API Explorer berumur pendek (±1 jam). Untuk pemakaian rutin,
> tukar dengan long-lived token (berlaku ±60 hari) lewat endpoint
> `oauth/access_token` dengan `grant_type=fb_exchange_token`.

## Pemakaian

```bash
iglead init                          # buat competitors.yml + database
# sunting competitors.yml, isi daftar kompetitor

iglead fetch                         # tarik data terbaru, simpan sebagai snapshot
iglead rank                          # tampilkan leaderboard
iglead rank --compare-days 7         # sekalian tampilkan pergerakan peringkat
iglead rank --csv leaderboard.csv    # ekspor ke CSV
iglead rank --markdown               # tabel Markdown untuk Notion/Slack
iglead report -o leaderboard.html    # laporan HTML mandiri
iglead history kopisenja             # riwayat follower satu akun
iglead status                        # ringkasan isi database
```

Alur normalnya: jalankan `fetch` terjadwal (harian atau mingguan), lalu `rank`
atau `report` kapan pun butuh. Nilai tool ini menumpuk seiring waktu — makin
banyak snapshot, makin bermakna angka pertumbuhannya.

Contoh cron harian jam 7 pagi:

```cron
0 7 * * * cd /path/ke/proyek && /usr/bin/python3 -m iglead fetch >> fetch.log 2>&1
```

## Konfigurasi

`competitors.yml` (lihat `competitors.example.yml` untuk versi lengkapnya):

```yaml
own_account: brand_saya

competitors:
  - username: kompetitor_a
    label: "Kompetitor A"
  - kompetitor_b            # bentuk singkat juga boleh

posts_limit: 25             # post terakhir yang ditarik per akun (maks 50)
lookback_days: 30           # rentang analisis engagement & frekuensi
growth_window_days: 30      # rentang pembanding pertumbuhan follower

weights:
  engagement_rate: 0.35
  follower_growth_pct: 0.25
  followers: 0.15
  interactions_per_post: 0.15
  posting_frequency: 0.10
```

Username boleh ditulis sebagai `nama`, `@nama`, atau URL profil penuh — semuanya
dinormalisasi. Bobot otomatis dinormalisasi ke total 1.0, jadi `35/25/15/15/10`
sama saja dengan versi desimalnya.

## Cara skor dihitung

Setiap metrik dinormalisasi **min-max ke skala 0–100 relatif terhadap peserta
leaderboard**, lalu dijumlahkan berbobot:

| Metrik | Arti |
|---|---|
| `engagement_rate` | Interaksi rata-rata per post ÷ jumlah follower, dalam persen |
| `follower_growth_pct` | Pertumbuhan follower dibanding snapshot `growth_window_days` lalu |
| `followers` | Jumlah follower saat ini |
| `interactions_per_post` | Rata-rata like + komentar per post |
| `posting_frequency` | Rata-rata post per minggu dalam rentang analisis |

Konsekuensi penting dari normalisasi relatif: **skor 100 berarti terbaik di
antara akun yang dibandingkan, bukan sempurna secara absolut.** Menambah atau
mengurangi kompetitor akan menggeser skor semua akun. Yang dibaca adalah urutan
dan jaraknya, bukan angka mutlaknya.

Kalau semua peserta punya angka identik pada suatu metrik (termasuk saat hanya
ada satu akun), metrik itu diberi nilai netral 50 supaya tidak ada yang
diuntungkan.

Sesuaikan bobot dengan tujuan Anda:

- Kejar **engagement** → naikkan `engagement_rate`
- Kejar **jangkauan** → naikkan `followers`
- Pantau **momentum** → naikkan `follower_growth_pct`

## Impor manual lewat CSV

Kalau kompetitor bukan akun Business (jadi tidak terbaca API), atau Anda punya
catatan historis, datanya bisa dimasukkan lewat CSV. Jenis file dideteksi
otomatis dari headernya.

```bash
iglead import snapshots.csv
iglead import posts.csv
```

```csv
# snapshots.csv
username,captured_at,followers_count,media_count
kompetitor_a,2024-05-01,48000,1069

# posts.csv
username,post_id,timestamp,like_count,comments_count,media_type,permalink
kompetitor_a,abc123,2024-05-02,2450,88,IMAGE,https://instagram.com/p/abc123/
```

Kolom alias diterima: `followers`/`posts` untuk snapshot, `likes`/`comments`/`date`
untuk post. Tanggal boleh ISO-8601 atau `YYYY-MM-DD`.

## Penyimpanan data

SQLite (`iglead.db` secara default), dua tabel:

- `snapshots` — **append-only**, satu baris per akun per pengambilan. Inilah yang
  membuat riwayat pertumbuhan follower tetap utuh.
- `posts` — di-upsert berdasarkan `post_id`, karena jumlah like dan komentar
  masih berubah setelah post terbit.

Rentang analisis ditambatkan ke waktu snapshot, bukan jam sekarang — jadi
menjalankan `rank` beberapa hari setelah `fetch` terakhir tetap memberi angka
yang konsisten.

## Batasan yang perlu diketahui

- **Hanya akun Business/Creator.** Akun personal dan privat tidak bisa dibaca
  `business_discovery`. Akun seperti itu akan dilewati dengan peringatan, dan
  `fetch` tetap melanjutkan akun lainnya.
- **Tidak ada data impressions/reach kompetitor.** Metrik insight semacam itu
  hanya tersedia untuk akun sendiri. Karena itu engagement rate di sini dihitung
  terhadap jumlah follower, bukan terhadap reach.
- **Akun yang menyembunyikan jumlah like** akan terbaca 0 like; komentarnya tetap
  terhitung, tapi engagement rate-nya jadi understated.
- **Pertumbuhan butuh riwayat.** Setelah `fetch` pertama, kolom growth berisi
  `n/a` karena belum ada pembanding. Jalankan beberapa hari untuk mengisinya.
- **Kuota API.** Graph API membatasi 200 panggilan per jam per user. Tool ini
  memakai 1 panggilan per akun per `fetch`, dan otomatis mengulang dengan
  backoff saat kena rate limit.

## Pengembangan

```bash
pip install pytest
python -m pytest tests/ -q
```

Struktur modul:

| File | Isi |
|---|---|
| `iglead/config.py` | Pembacaan & validasi konfigurasi |
| `iglead/instagram.py` | Klien Graph API, retry, klasifikasi error |
| `iglead/storage.py` | Skema & query SQLite |
| `iglead/metrics.py` | Perhitungan metrik turunan |
| `iglead/leaderboard.py` | Normalisasi, pembobotan, pemeringkatan |
| `iglead/report.py` | Keluaran tabel, CSV, Markdown, HTML |
| `iglead/csv_io.py` | Impor data manual |
| `iglead/cli.py` | Definisi perintah |

## Catatan kepatuhan

Tool ini hanya membaca data publik lewat API resmi Meta, dengan token milik
Anda sendiri, dalam batas kuota yang berlaku. Patuhi Platform Terms Meta saat
menyimpan dan membagikan data yang dihasilkan.
