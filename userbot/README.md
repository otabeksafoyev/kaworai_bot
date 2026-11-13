# Kaworai Userbot

Ishga tushirish (kaworai_bot papkasidan): `python -m userbot.main`

.env ga qo'shing:
  USERBOT_LOGIN_BOT_TOKEN=<@BotFather dan yangi bot>
  USERBOT_FERNET_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
  USERBOT_AUTO_CONFIRM=0   # 1 bo'lsa tasdiqsiz qo'shadi (tavsiya etilmaydi)

Muhim: userbot akkaunti maxfiy kanal(lar)da ADMIN bo'lishi kerak (post yozish huquqi bilan).
Railway: alohida servis (Start command: python -m userbot.main), o'sha env va DATABASE_URL bilan.

## Nishon botlar va moslik foizi (`/targets`)

Boshqaruv botida `/targets`:
- **Avtomatik rejimni yoqish** — Kaworai 70% bilan ro'yxatga qo'shiladi. Bu rejimda AI natijasi adminga ko'rsatilmaydi.
- **Yumora-uslubidagi bot qo'shish** — nom → BOT_TOKEN → DATABASE_URL → yuklash kanali (UPLOAD_CHANNEL_ID) → foiz.
  Ma'lumotlar xabar o'chirilib, Fernet bilan shifrlanib saqlanadi. Bot ham, userbot akkaunti ham yuklash kanalida admin bo'lishi kerak.
- Har bir bot uchun foizni o'zgartirish, yoqish/o'chirish, olib tashlash. **Eski rejimga qaytish** — nishonlarni tozalaydi
  (eski oqim: har bir post sizning tasdig'ingiz bilan faqat Kaworai ga).

Oqim: post → manba bot → nom tekshiruvi → AI ma'lumot (bir marta) → **moslik foizi** → foizi chegaradan kam bo'lmagan har bir botga:
- anime botda yo'q bo'lsa — yangi anime + barcha qismlar; bor bo'lsa — faqat bazadagi oxirgi qismdan keyingilari;
- so'ng news kanallarga e'lon: Kaworai — kontent turiga mos guruh (Anime / Dorama / Serial / Kino), Yumora — barcha news kanallar.
- Yumora faqat **anime** qabul qiladi (dorama/serial/kino postlari unga o'tkazilmaydi). Yumora `code` — keyingi bo'sh raqam.

Foiz (`scoring.py`): nom 25, yil 20, janr 25, tavsif 30 — faqat post/manba matnida va AI natijasida ikkalasida ham bor belgilar solishtiriladi
(yil: `Yil: 2024`, janr: `Janr: a, b`, tavsif: `Tavsif: ...` yoki eng uzun qator). Faqat nom mos kelsa foiz 60% dan oshmaydi;
AI "nom aniq topilmadi" desa 50% dan oshmaydi; AI ma'lumoti to'liq bo'lmasa (tavsif/janr/yil) hech qaysi botga qo'shilmaydi.
Chegara: foiz **shu qiymatdan kam bo'lmasa** qo'shiladi (>=).
