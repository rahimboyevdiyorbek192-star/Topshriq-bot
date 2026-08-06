"""Userbot uchun Telethon session string yaratish (BIR MARTA ishlatiladi)."""
import asyncio

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    print("Telethon o'rnatilmagan. Buyruq: pip install telethon")
    raise SystemExit(1)


async def main():
    print("=" * 55)
    print("  USERBOT SESSION YARATISH")
    print("=" * 55)
    print()
    print("Kerakli ma'lumotlar: https://my.telegram.org saytidan oling")
    print()

    api_id   = int(input("API ID: ").strip())
    api_hash = input("API Hash: ").strip()
    phone    = input("Telefon raqam (+998xxxxxxxxx): ").strip()

    print()
    print("SMS kod yoki Telegram ilovasidagi kod so'raladi...")
    print()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start(phone=phone)

    session_string = client.session.save()
    await client.disconnect()

    print()
    print("✅ Session string yaratildi!")
    print()
    print("Quyidagini .env fayliga ko'chiring:")
    print(f"TG_USERBOT_SESSION={session_string}")
    print()
    print("Shuningdek:")
    print(f"TG_API_ID={api_id}")
    print(f"TG_API_HASH={api_hash}")


if __name__ == "__main__":
    asyncio.run(main())
