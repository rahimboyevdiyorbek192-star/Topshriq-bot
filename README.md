# 🤖 Topshiriqlar boti (Topshriq-bot)

Rahbar va xodimlar uchun Telegram topshiriqlarini boshqarish boti. Rahbar
**Topshiriqlar guruhi**ga topshiriq yozadi (muddat va Word/Excel/PowerPoint
namunalari bilan), xodimlar esa **Ijro guruhi**ga bajarilgan ishlarini
tashlaydi. Bot kim bajardi/bajarmaganini avtomatik hisoblab, **svodka** (shu
jumladan Excel hisobot) tayyorlaydi va muddat yaqinlashganda eslatib turadi.

## Asosiy imkoniyatlar

- 📝 **Topshiriq yaratish** — `#topshiriq` bilan boshlangan xabar, muddat
  avtomatik aniqlanadi, namuna fayllar (albom ham) biriktiriladi.
- 📢 **Avtomatik e'lon** — har topshiriq ijro guruhiga e'lon qilinadi.
- ✅ **Ijroni kuzatish** — xodim e'longa reply qilib yoki `#T3` yozib ishini
  yuboradi; bot avtomatik hisobga oladi.
- 📊 **Svodka** — kim bajardi / bajarmadi, foizlar, progress-bar.
- 📄 **Excel hisobot** — xodimlar × topshiriqlar jadvali (`/excel`).
- ⏰ **Avtomatik eslatmalar** — muddatdan oldin va o'tganda bajarmaganlarni
  belgilab (mention) eslatadi.
- 👥 **Xodimlar ro'yxati** — o'zi to'ladi yoki qo'lda boshqariladi.

## O'rnatish

### 1. Botni yaratish
Telegramda [@BotFather](https://t.me/BotFather) orqali bot yarating va
**tokenni** oling. BotFather'da `/setprivacy` → **Disable** qiling (bot guruh
xabarlarini ko'rishi uchun) yoki botni guruhda **admin** qiling.

### 2. Loyihani sozlash
```bash
git clone <repo-url>
cd Topshriq-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3. `.env` faylini to'ldiring
| O'zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | BotFather bergan token (majburiy) |
| `MANAGER_IDS` | Rahbar(lar) Telegram ID'si (vergul bilan) |
| `TASKS_GROUP_ID` | Topshiriqlar guruhi ID'si |
| `EXECUTION_GROUP_ID` | Ijro guruhi ID'si |
| `TIMEZONE` | Vaqt mintaqasi (default: `Asia/Tashkent`) |
| `REMINDER_MINUTES` | Eslatma vaqtlari, daqiqada (masalan `120,30`) |

> **ID'larni bilish:** botni guruhga qo'shing va `/id` deb yozing — chat va
> foydalanuvchi ID'lari chiqadi.

### 4. Ishga tushirish
```bash
python run.py
```

## Foydalanish

### Rahbar — topshiriq yaratish (Topshiriqlar guruhida)
Xabarni `#topshiriq` bilan boshlang, birinchi qator — sarlavha, `Muddat:` qatori
— muddat. Namuna fayllarni shu xabarga biriktiring:

```
#topshiriq
Oylik hisobot tayyorlash
Muddat: 07.08.2026 17:00
Har bir bo'lim bo'yicha to'liq hisobot kerak
```
Qo'llab-quvvatlanadigan muddat formatlari: `17:00`, `soat 17:00`,
`07.08 17:00`, `07.08.2026 17:00`, `2026-08-07 17:00`.

### Xodim — ishni topshirish (Ijro guruhida)
- Botning topshiriq e'loniga **reply** qiling, **yoki**
- Xabar boshida topshiriq raqamini yozing: `#T3`

Fayl, rasm yoki matnni shu tarzda yuborsangiz bot avtomatik qabul qiladi.

### Komandalar
| Komanda | Kim | Tavsif |
|---|---|---|
| `/svodka` | Rahbar | Umumiy svodka |
| `/svodka N` | Rahbar | N-topshiriq bo'yicha svodka |
| `/excel` | Rahbar | Excel hisobot (`/excel hammasi` — yopilganlar bilan) |
| `/topshiriqlar` | Hamma | Ochiq topshiriqlar |
| `/yopish N` | Rahbar | Topshiriqni yopish |
| `/eslatma N` | Rahbar | Bajarmaganlarga eslatma |
| `/hodimlar` | Rahbar | Xodimlar ro'yxati |
| `/hodim_qoshish` | Rahbar | (reply bilan) xodim qo'shish |
| `/hodim_ochirish ID` | Rahbar | Xodimni chiqarish |
| `/ruyxatdan_otish` | Xodim | O'zini ro'yxatga qo'shish |
| `/mening` | Xodim | O'z topshiriqlari holati |
| `/id` | Hamma | Chat/foydalanuvchi ID |
| `/help` | Hamma | Yordam |

## Xodimlar ro'yxati
Ijro guruhida birinchi marta ish yuborgan xodim **avtomatik** ro'yxatga
qo'shiladi. Shuningdek rahbar qo'lda `/hodim_qoshish` (xodim xabariga reply)
bilan qo'shishi mumkin. Svodka foizlari shu ro'yxatdagi xodimlarga nisbatan
hisoblanadi.

## Texnik tafsilotlar
- **Til/kutubxona:** Python 3.11+, [aiogram 3](https://docs.aiogram.dev)
- **Ma'lumotlar bazasi:** SQLite (`aiosqlite`)
- **Eslatmalar:** APScheduler (har 5 daqiqada tekshiradi)
- **Excel:** openpyxl

## Loyiha tuzilmasi
```
bot/
├── main.py            # kirish nuqtasi
├── config.py          # .env sozlamalari
├── database.py        # SQLite bilan ishlash
├── middlewares.py     # albom yig'ish, bog'liqliklar
├── scheduler.py       # avtomatik eslatmalar
├── handlers/
│   ├── common.py      # /start, /help, /id
│   ├── employees.py   # xodimlarni boshqarish
│   ├── tasks.py       # topshiriq yaratish
│   ├── submissions.py # ishlarni qabul qilish
│   └── reports.py     # svodka, excel, eslatma
└── utils/
    ├── deadline.py    # muddat parsingi
    ├── files.py       # fayl ajratish
    └── report.py      # svodka/excel generatsiya
```
```
run.py                 # python run.py
```
