"""Userbot uchun Telethon session string yaratish (BIR MARTA ishlatiladi).

Kirish usullari:
  1. QR-kod   — Telegram ilovasida skanerlash (tavsiya, SMS kerak emas)
  2. Telefon  — SMS yoki Telegram kod orqali (zaxira)
"""
import asyncio
import sys

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("Telethon o'rnatilmagan.  pip install telethon")
    raise SystemExit(1)


def _print_qr(url: str) -> None:
    """URL ni terminalda QR-kod sifatida chizadi."""
    try:
        import qrcode as _qr
        qr = _qr.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
        return
    except ImportError:
        pass

    # qrcode yo'q — segno sinab ko'ramiz
    try:
        import segno
        segno.make(url).terminal(compact=True)
        return
    except ImportError:
        pass

    # Hech biri yo'q — URL ni ko'rsatamiz
    print(f"\n  URL: {url}\n")
    print("  QR-kod ko'rsatish uchun:  pip install qrcode[pil]")


async def _qr_login(client: TelegramClient) -> bool:
    """QR-kod orqali kirish. True = muvaffaqiyatli."""
    print("\n" + "─" * 55)
    print("  QR-KOD ORQALI KIRISH")
    print("─" * 55)
    print()
    print("  1. Telefoningizdagi Telegram ilovasini oching")
    print("  2. Sozlamalar → Qurilmalar → Kompyuterni ulash")
    print("  3. Quyidagi QR-kodni skanerlang:")
    print()

    try:
        qr = await client.qr_login()
    except Exception as e:
        print(f"  QR-kod xato: {e}")
        return False

    # QR-kod yangilanib turadi — har yangilanishda qayta chizamiz
    async def _on_expire(qr_obj):
        print("\n  QR-kod yangilandi, qayta skanerlang:\n")
        _print_qr(qr_obj.url)

    qr.recreated.append(_on_expire)
    _print_qr(qr.url)

    print()
    print("  Skanerlashni kutmoqda... (to'xtatish: Ctrl+C)")
    print()

    try:
        await qr.wait(timeout=120)
        return True
    except asyncio.TimeoutError:
        print("  Vaqt tugadi (2 daqiqa). Qayta urinib ko'ring.")
        return False
    except Exception as e:
        # SessionPasswordNeededError — 2FA
        err = str(type(e).__name__)
        if "SessionPassword" in err or "Password" in err:
            pwd = input("  2FA paroli: ").strip()
            try:
                await client.sign_in(password=pwd)
                return True
            except Exception as e2:
                print(f"  Noto'g'ri parol: {e2}")
                return False
        print(f"  Xato: {e}")
        return False


async def _phone_login(client: TelegramClient) -> bool:
    """SMS/Telegram kod orqali kirish."""
    print("\n" + "─" * 55)
    print("  TELEFON ORQALI KIRISH")
    print("─" * 55)
    phone = input("\n  Telefon raqam (+998xxxxxxxxx): ").strip()
    try:
        await client.send_code_request(phone)
        code = input("  Telegram/SMS kodi: ").strip()
        await client.sign_in(phone, code)
        return True
    except Exception as e:
        err = str(type(e).__name__)
        if "SessionPassword" in err or "Password" in err:
            pwd = input("  2FA paroli: ").strip()
            try:
                await client.sign_in(password=pwd)
                return True
            except Exception as e2:
                print(f"  Noto'g'ri parol: {e2}")
                return False
        print(f"  Xato: {e}")
        return False


async def main():
    print()
    print("╔" + "═" * 53 + "╗")
    print("║       USERBOT SESSION YARATISH                      ║")
    print("╚" + "═" * 53 + "╝")
    print()
    print("  my.telegram.org saytidan API ID va Hash oling:")
    print("  1. my.telegram.org → API development tools")
    print("  2. App title: istalgan nom, Platform: Other")
    print()

    api_id   = input("  API ID   : ").strip()
    api_hash = input("  API Hash : ").strip()

    if not api_id.isdigit():
        print("  API ID raqam bo'lishi kerak!")
        return

    print()
    print("  Kirish usulini tanlang:")
    print("  1 — QR-kod (tavsiya, SMS kerak emas)")
    print("  2 — Telefon raqam (SMS yoki Telegram kod)")
    print()
    choice = input("  Tanlov [1/2, default=1]: ").strip() or "1"

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    await client.connect()

    ok = False
    if choice == "2":
        ok = await _phone_login(client)
    else:
        ok = await _qr_login(client)
        if not ok:
            print("\n  QR-kod ishlamadi. Telefon orqali urinib ko'ramizmi? [ha/yo'q]: ", end="")
            if input().strip().lower() in ("ha", "h", "yes", "y"):
                ok = await _phone_login(client)

    if not ok:
        print("\n  ❌ Kirish amalga oshmadi.")
        await client.disconnect()
        return

    session_string = client.session.save()
    await client.disconnect()

    print()
    print("╔" + "═" * 53 + "╗")
    print("║  ✅ SESSION MUVAFFAQIYATLI YARATILDI!               ║")
    print("╚" + "═" * 53 + "╝")
    print()
    print("  Quyidagilarni .env fayliga ko'chiring:")
    print()
    print(f"  TG_API_ID={api_id}")
    print(f"  TG_API_HASH={api_hash}")
    print(f"  TG_USERBOT_SESSION={session_string}")
    print()
    print("  Keyin boti qayta ishga tushiring.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
