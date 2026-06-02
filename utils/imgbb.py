"""
utils/imgbb.py — ImgBB rasmlarni yuklash utility

Admin poster yuborilganda Telegram file_id dan rasm yuklab,
ImgBB ga POST qilib doimiy URL oladi.

API hujjatlari: https://api.imgbb.com
Bepul, doimiy (expiration qo'yilmasa rasm hech qachon o'chmaydi).
"""

import base64
import logging

import aiohttp

logger = logging.getLogger(__name__)

IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"


async def upload_to_imgbb(api_key: str, image_bytes: bytes, name: str = "poster") -> str | None:
    """
    Rasm bytes ni ImgBB ga yuklaydi va doimiy URL qaytaradi.

    Args:
        api_key: ImgBB API key (data/config.py dan olinadi)
        image_bytes: Rasm bytes (Telegram download dan)
        name: Rasm nomi (ixtiyoriy)

    Returns:
        str: https://i.ibb.co/... doimiy URL
        None: xato bo'lsa
    """
    try:
        # Bytes ni base64 ga aylantiramiz
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        payload = {
            "key": api_key,
            "image": image_b64,
            "name": name,
            # expiration qo'yilmaydi → doimiy saqlanadi
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                IMGBB_UPLOAD_URL,
                data=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning("ImgBB upload xato: status=%s", resp.status)
                    return None

                result = await resp.json()

                if not result.get("success"):
                    logger.warning("ImgBB upload muvaffaqiyatsiz: %s", result)
                    return None

                # URL ni olish — display_url eng kichik (medium) variant
                # direct URL to'liq original rasm
                url = (
                    result.get("data", {}).get("display_url")
                    or result.get("data", {}).get("url")
                )
                logger.info("ImgBB upload muvaffaqiyatli: %s", url)
                return url

    except aiohttp.ClientError as e:
        logger.warning("ImgBB network xato: %s", e)
        return None
    except Exception as e:
        logger.exception("ImgBB kutilmagan xato: %s", e)
        return None


async def upload_telegram_photo_to_imgbb(bot, file_id: str, api_key: str, name: str = "poster") -> str | None:
    """
    Telegram file_id dan rasm yuklab ImgBB ga joylaydi.

    Args:
        bot: aiogram Bot instance
        file_id: Telegram photo file_id
        api_key: ImgBB API key
        name: Rasm nomi

    Returns:
        str: doimiy ImgBB URL yoki None
    """
    try:
        # Telegram dan fayl yuklab olamiz
        file = await bot.get_file(file_id)
        if not file.file_path:
            logger.warning("ImgBB: file_path yo'q, file_id=%s", file_id)
            return None

        # Rasmni bytes sifatida yuklaymiz
        file_bytes = await bot.download_file(file.file_path)
        if hasattr(file_bytes, "read"):
            image_bytes = file_bytes.read()
        else:
            image_bytes = bytes(file_bytes)

        return await upload_to_imgbb(api_key, image_bytes, name=name)

    except Exception as e:
        logger.warning("Telegram photo yuklab olishda xato: %s", e)
        return None
