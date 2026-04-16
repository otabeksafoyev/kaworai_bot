import asyncio
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Configure root logging *before* any handler/database module is imported so
# module-level log calls at import time are captured with the right format.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)

from database.engine import init_db  # noqa: E402
from handlers.admin import admin_router  # noqa: E402
from handlers.admin_pro import pro_admin_router  # noqa: E402
from handlers.callbacks import callback_router  # noqa: E402
from handlers.genres import genre_router  # noqa: E402
from handlers.inline import inline_router  # noqa: E402
from handlers.pro_payment import pro_payment_router  # noqa: E402
from handlers.users import user_router  # noqa: E402
from handlers.users_pro import pro_user_router  # noqa: E402
from loader import bot, dp  # noqa: E402
from middlewares.subscription import SubscriptionMiddleware  # noqa: E402
from middlewares.throttling import ThrottlingMiddleware  # noqa: E402

logger = logging.getLogger(__name__)


async def on_startup():
    logger.info("Ma'lumotlar bazasi jadvallari tekshirilmoqda...")
    try:
        await init_db()
        logger.info("Baza jadvallari tayyor.")
    except Exception:
        logger.exception("Bazani yaratishda jiddiy xato")
        sys.exit(1)


async def main():
    await on_startup()

    # Routerlar (pro_payment ENG BIRINCHI — kawaii_pass ni ushlaydi)
    dp.include_router(pro_payment_router)
    dp.include_router(admin_router)
    dp.include_router(pro_admin_router)
    dp.include_router(pro_user_router)
    dp.include_router(user_router)
    dp.include_router(callback_router)
    dp.include_router(inline_router)
    dp.include_router(genre_router)

    # Throttling middleware — foydalanuvchi spam / brute-force qilishining
    # oldini oladi. Handler qabul qilinganidan oldin ishga tushadi, shuning
    # uchun uni subscription middleware'dan oldin qo'shamiz.
    dp.message.middleware(ThrottlingMiddleware())
    dp.callback_query.middleware(ThrottlingMiddleware())

    # Obuna tekshiruv middleware
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    bot_info = await bot.get_me()
    logger.info("Bot ishga tushdi: @%s (id=%s)", bot_info.username, bot_info.id)

    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    except Exception:
        logger.exception("Polling davomida xatolik")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot foydalanuvchi tomonidan to'xtatildi.")
