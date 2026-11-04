# Nasiya AI — to'liq o'rnatish qo'llanmasi

Bu qo'llanma 4 bosqichdan iborat:

1. **Kompyuteringizda ishga tushirish** (Windows) — sinash uchun
2. **AI modelni ulash** (Fireworks / Baseten — Muse Spark Open)
3. **GitHub'ga yuklash** (hackathon talabi: ochiq repo)
4. **Serverga o'rnatish** (Kamatera) — bot 24/7 ishlashi va Mini App uchun

> ⚠️ Hech qachon bot tokeni, API kalit yoki parolni GitHub'ga, Discord'ga yoki boshqa joyga yubormang.
> Ular faqat `.env` faylida turadi va `.env` GitHub'ga chiqmaydi (`.gitignore` ichida).

---

## 1-bosqich. Kompyuterda ishga tushirish (Windows)

### 1.1. Kerakli dasturlar (bir marta)

| Dastur | Qayerdan | Eslatma |
|---|---|---|
| Python 3.12 yoki yangi | python.org/downloads | O'rnatishda **"Add python.exe to PATH"** belgisini qo'ying |
| Git | git-scm.com | Hamma sozlamalar standart |
| (ixtiyoriy) ffmpeg | gyan.dev/ffmpeg | Ovozli xabarlar uchun kerak. Serverga avtomatik o'rnatiladi |

Tekshirish (PowerShell'da):
```powershell
python --version
git --version
```

### 1.2. Loyihani joylashtirish

1. `nasiya_ai.zip` ni oching va papkani shu yerga qo'ying: `C:\Projects\nasiya_ai`
2. PowerShell'ni oching va papkaga o'ting:
```powershell
cd C:\Projects\nasiya_ai
```

Papka tuzilishi:
```
nasiya_ai/
├─ config/            Django sozlamalari va URL'lar
├─ shop/              asosiy ilova
│  ├─ ai/             AI qatlami: mock (test), open (Muse Spark Open), meta (Meta API)
│  ├─ templates/shop/app.html   Mini App (bitta fayl)
│  ├─ bot.py          Telegram bot
│  ├─ api.py          Mini App API
│  ├─ services.py     biznes mantiq
│  ├─ reports.py      hisobotlar, menejer tavsiyalari, brifing
│  ├─ notify.py       eslatmalar (Telegram, SMS)
│  ├─ demo.py         /demo — 30 kunlik namuna do'kon
│  ├─ shelf.py        javon tahlili (surat → sanoq → solishtirish)
│  └─ tests.py        51 ta test
├─ deploy/
│  ├─ setup.sh        serverga o'rnatish (bir buyruq)
│  └─ update.sh       serverdagi kodni yangilash
├─ check_llm.py       AI modelni tekshirish
├─ requirements.txt
├─ .env.example       sozlamalar namunasi
├─ README.md          (inglizcha, hakamlar uchun)
└─ QOLLANMA.md        shu fayl
```

### 1.3. Python muhiti

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
> Agar `activate` xato bersa (scripts disabled): `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` → `Y`, keyin qayta urinib ko'ring.
> Har safar yangi PowerShell oynasini ochganda `venv\Scripts\activate` ni qayta bajaring.

### 1.4. Telegram bot yaratish

1. Telegram'da **@BotFather** → `/newbot`
2. Nom: masalan `Nasiya AI`; username: masalan `BarakaNasiyaBot` (oxiri `bot` bilan tugashi shart)
3. BotFather bergan **tokenni** nusxalang (`123456789:AAH...` ko'rinishida)
4. O'z Telegram ID'ingizni bilish: **@userinfobot** ga `/start` yozing → `Id: 123456789`

### 1.5. `.env` faylini to'ldirish

```powershell
copy .env.example .env
notepad .env
```
Quyidagilarni to'ldiring (qolganlari tegmasin):
```
TELEGRAM_BOT_TOKEN=123456789:AAH...          ← BotFather tokeni
BOT_USERNAME=BarakaNasiyaBot                  ← @ belgisisiz
AI_BACKEND=mock                               ← hozircha mock (kalit kelgach: open)
WEBAPP_DEV_USER=123456789                     ← o'z Telegram ID'ingiz (faqat kompyuterda!)
```
Saqlang (Ctrl+S) va yoping.

### 1.6. Baza va testlar

```powershell
python manage.py migrate
python manage.py test shop
```
Oxirida `OK` chiqishi kerak.

### 1.7. Botni ishga tushirish

```powershell
python manage.py runbot
```
`Bot ishga tushdi: @BarakaNasiyaBot` chiqadi. Telegram'da botingizga kiring:

1. `/start` → do'kon nomini yozing (masalan `Baraka`)
2. `/demo` → 30 kunlik namuna ma'lumot yuklanadi
3. Sinab ko'ring: `/brifing`, `/hafta`, `/maslahat`, `/qarzlar`, `/ombor`
4. Yozib ko'ring: `Akmal 2 ta non oldi` → "Qaysi Akmal?" tugmalari chiqadi

Botni to'xtatish: PowerShell'da **Ctrl+C**.

> Kompyuterda bot **mock** rejimida ishlaydi — oddiy qoidalar bilan, haqiqiy AI emas. Demo video uchun
> albatta 2-bosqichdagi haqiqiy modelni ulang.

### 1.8. Mini App'ni brauzerda ko'rish

Yangi PowerShell oynasida:
```powershell
cd C:\Projects\nasiya_ai
venv\Scripts\activate
python manage.py runserver
```
Brauzerda oching: **http://127.0.0.1:8000/app/** (qorong'i rejim: `http://127.0.0.1:8000/app/?theme=dark`)

> Telegram ichida Mini App faqat HTTPS bilan ochiladi — bu 4-bosqichda (server) bo'ladi.

---

## 2-bosqich. AI modelni ulash (Muse Spark Open)

Tashkilotchilar tasdiqladi: Meta'ning ochiq vaznli modellari (Muse Spark Open, Muse Glimmer) to'liq hisobga olinadi.

### 2.1. Fireworks (tavsiya — hackathon hamkori)

1. **fireworks.ai** da ro'yxatdan o'ting → Billing → kartani qo'shib **$5** to'ldiring
2. **API Keys** → yangi kalit yarating → nusxalang
3. **Models** bo'limida `Muse Spark Open` ni toping → sahifadagi **model nomini** nusxalang
   (`accounts/fireworks/models/...` ko'rinishida)

`.env` da:
```
AI_BACKEND=open
LLM_BASE_URL=https://api.fireworks.ai/inference/v1
LLM_API_KEY=fw_...
LLM_MODEL=accounts/fireworks/models/...     ← sahifadan aniq nom
```

### 2.2. Baseten (kredit kelsa)

```
AI_BACKEND=open
LLM_BASE_URL=https://inference.baseten.co/v1
LLM_API_KEY=...
LLM_MODEL=meta-models/muse-spark-open-1026
```

### 2.3. Tekshirish

```powershell
python check_llm.py
```
5 ta o'zbekcha gap JSON'ga aylanishi kerak (`Natija: 5/5`). Ovozni tekshirish: telefoningizda ovoz yozib,
faylni papkaga qo'ying va:
```powershell
python check_llm.py ovoz.ogg
```
**Natijani menga yuboring** — kerak bo'lsa promptni sozlayman.

---

## 3-bosqich. GitHub'ga yuklash

1. **github.com** → New repository → nomi `nasiya-ai` → **Public** → Create (README qo'shmang)
2. PowerShell'da (loyiha papkasida):
```powershell
git init
git add .
git status
```
3. ⚠️ `git status` ro'yxatida **`.env` bo'lmasligi** kerak. Agar bo'lsa — to'xtang va menga yozing.
4. Davom eting (`SIZNING_LOGIN` ni o'zgartiring):
```powershell
git commit -m "Nasiya AI: voice-first credit ledger for neighborhood shops"
git branch -M main
git remote add origin https://github.com/SIZNING_LOGIN/nasiya-ai.git
git push -u origin main
```
Keyingi o'zgarishlarda:
```powershell
git add .
git commit -m "nima o'zgardi"
git push
```

---

## 4-bosqich. Serverga o'rnatish (Kamatera)

### 4.1. Server ochish

Kamatera → Create Server:
- **OS:** Ubuntu 24.04
- **CPU/RAM:** 1–2 vCPU, 2 GB RAM
- **Disk:** 20–30 GB
- **Joylashuv:** Yevropa (Frankfurt yoki Amsterdam)
- **Parol:** kuchli parol (hech kimga yubormang)

Server ochilgach **IP manzilini** yozib oling.
> Kamatera panelida firewall bo'lsa, **22, 80, 443** portlarini oching.

### 4.2. Serverga kirish

Windows PowerShell'da (`1.2.3.4` o'rniga o'z IP'ingiz):
```powershell
ssh root@1.2.3.4
```
Birinchi marta `yes` yozing, keyin parolni kiriting (yozilayotgani ko'rinmaydi — bu normal).

### 4.3. Loyihani yuklab, o'rnatish

Serverda (`SIZNING_LOGIN` ni o'zgartiring):
```bash
apt-get update && apt-get install -y git
git clone https://github.com/SIZNING_LOGIN/nasiya-ai.git /opt/nasiya_ai
sudo bash /opt/nasiya_ai/deploy/setup.sh
```
Skript savollar beradi:
| Savol | Javob |
|---|---|
| Telegram bot token | BotFather tokeni |
| Bot username | `BarakaNasiyaBot` (@ siz) |
| LLM API kaliti | Fireworks kaliti (hali yo'q bo'lsa — Enter) |
| LLM base URL | Enter (Fireworks) yoki Baseten manzili |
| LLM model nomi | Fireworks sahifasidagi nom |

5–10 daqiqada o'rnatiladi. Oxirida chiqadi:
```
✅ Mini App/API ishlayapti
✅ Bot ishlayapti
Mini App:  https://1-2-3-4.sslip.io/app/
```

> ⚠️ Serverda bot ishga tushgach, **kompyuterdagi botni to'xtating** (Ctrl+C). Bir token bilan ikki joyda
> bot ishlasa, Telegram xato beradi.

### 4.4. Tekshirish

1. Telegram'da botga `/start` — pastda **📊 Do'kon** menyu tugmasi paydo bo'ladi
2. `/demo` → keyin **📊 Do'kon** → Mini App ochiladi
3. Brauzerda `https://1-2-3-4.sslip.io/app/` — "Telegram orqali oching" yozuvi chiqsa, hammasi to'g'ri

### 4.5. Kundalik buyruqlar (serverda)

| Nima | Buyruq |
|---|---|
| Bot loglari (jonli) | `journalctl -u nasiya-bot -f` |
| Mini App loglari | `journalctl -u nasiya-web -n 100` |
| Qayta ishga tushirish | `systemctl restart nasiya-bot nasiya-web` |
| Holat | `systemctl status nasiya-bot` |
| Sozlamani o'zgartirish | `nano /opt/nasiya_ai/.env` → Ctrl+O, Enter, Ctrl+X → keyin restart |
| Yangi kodni qo'yish | kompyuterda `git push`, serverda `sudo bash /opt/nasiya_ai/deploy/update.sh` |
| Admin panel uchun foydalanuvchi | `cd /opt/nasiya_ai && sudo -u nasiya venv/bin/python manage.py createsuperuser` |

### 4.6. AI kalitini keyinroq qo'shish

```bash
nano /opt/nasiya_ai/.env
```
O'zgartiring:
```
AI_BACKEND=open
LLM_API_KEY=fw_...
LLM_MODEL=accounts/fireworks/models/...
```
Saqlang va:
```bash
systemctl restart nasiya-bot nasiya-web
cd /opt/nasiya_ai && sudo -u nasiya venv/bin/python check_llm.py
```

---

## Asosiy imkoniyatlar — qanday ishlatiladi

### 📸 Javon tahlili (rasm orqali)
- Botga **javon rasmini** yuboring (izohsiz bo'lsa bot "Bu qanday rasm?" deb so'raydi → **📸 Javon**),
  yoki avval `/javon` buyrug'ini yozing, keyin rasm yuboring. Izohga "javon" deb yozsangiz — darhol tahlil qiladi.
- AI tovarlarni sanaydi va aytadi: javonda nima kam qoldi, nima ko'rinmayapti, bazada yo'q tovarlar.
- **Ertalab** va **kechqurun** suratga oling: kechki suratda bot ertalabkiga nisbatan nechta tovar kamayganini
  yozilgan savdo bilan solishtiradi va **yozilmay qolgan sotuvni** (taxminiy summasi bilan) ko'rsatadi.
- Natija Mini App → **Ombor** bo'limida ham turadi.
- Ertalabki brifingda "📸 Javonni suratga olib yuboring" eslatmasi chiqadi.
- Sanoq rasm bo'yicha **taxminiy** — tovarlar ko'rinadigan qilib, yorug' joyda suratga oling.

### 🤖 Qarzdorlarga avtomatik eslatma (Telegram)
1. Do'konchi mijoz telefonini kiritadi: botga *"Akmal aka telefoni 90 123 45 67"* yoki Mini App'da mijoz kartochkasi → Telefon.
2. Mijoz bir marta botni ochadi → `/start` → **🛒 Xaridorman** → **📱 Raqamimni yuborish**.
   Bot raqam bo'yicha uni topib **avtomatik ulaydi** (qaysi tartibda bo'lishi muhim emas).
3. Shundan keyin har kuni soat **10:00** da bot o'zi eslatma yuboradi:
   - va'da kuni kelgan yoki o'tgan mijozlarga;
   - 14+ kundan beri to'lamaganlarga;
   - bitta mijozga ko'pi bilan 3 kunda bir marta (spam bo'lmasligi uchun).
4. Do'konchiga hisobot keladi: kimga yuborildi, kim hali ulanmagan.

Buyruqlar: `/avto` — holat va navbatdagilar · `/avto off` / `/avto on` · `/avto 18` — soatni o'zgartirish ·
`/avto hozir` — hoziroq yuborish (demo uchun qulay).

> Telegram qoidasi: bot odamga faqat u botni bir marta ochgandan keyin yoza oladi. Shuning uchun mijoz bir marta
> raqamini yuborishi shart. Ulanmagan mijozlarga SMS faqat Eskiz.uz ulangan bo'lsa boradi.

---

### 🌐 Tillar: o'zbek, rus, ingliz
- `/start` da til tanlanadi; keyin `/til` (yoki `/lang`) bilan o'zgartiriladi. Mini App'da — yuqoridagi 🌐 tugma.
- Do'konchi va har bir mijozning tili alohida: eslatma mijozga **o'z tilida** boradi.
- Buyruqlar: o'zbekcha `/bugun /qarzlar /ombor …`, rus/ingliz tilida `/today /debts /stock …` — ikkalasi ham ishlaydi.
- Ruscha/inglizcha gaplarni to'liq tushunish real AI model (Muse Spark) orqali; `mock` rejimi faqat oddiy iboralarni tushunadi.
- ⚠️ Yangilagandan keyin bir marta: `python manage.py migrate` (yangi `lang` maydonlari). Serverda `deploy/update.sh` buni o'zi qiladi.

## Muammolar va yechimlar

| Muammo | Yechim |
|---|---|
| `python` topilmadi | Python'ni qayta o'rnating, "Add to PATH" belgisini qo'ying |
| `TELEGRAM_BOT_TOKEN .env faylida yo'q` | `.env` to'g'ri papkada ekanini va token yozilganini tekshiring |
| Bot javob bermaydi, logda `Conflict` | Bot boshqa joyda ham ishlayapti — kompyuterdagisini to'xtating |
| Mini App ochilmaydi (HTTPS xato) | `journalctl -u caddy -n 50` — 80/443 portlar ochiqligini tekshiring (Kamatera firewall) |
| `AI xatosi: LLM 401` | API kalit noto'g'ri |
| `AI xatosi: LLM 404` | `LLM_MODEL` nomi noto'g'ri — provayder sahifasidan qayta nusxalang |
| Ovoz ishlamaydi | `check_llm.py ovoz.ogg` natijasini menga yuboring |

---

## Muhim sanalar

| Sana | Nima |
|---|---|
| **4-noyabr, 21:00 ET** (Toshkent: **5-noyabr, 07:00**) | Topshirish muddati |
| ~25-noyabr | Kamatera sinov muddati tugashidan oldin serverni o'chirish yoki to'lovni tasdiqlash |
