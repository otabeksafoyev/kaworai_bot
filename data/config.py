from environs import Env

env = Env()
env.read_env()

BOT_TOKEN = env.str("BOT_TOKEN")
ADMINS = env.list("ADMIN_ID")
ADMIN_ID = env.int("ADMIN_ID")
DB_URL = env.str("DB_URL")
REDIS_URL = env.str("REDIS_URL")
NEWS_CHANNEL_ID = env.int("NEWS_CHANNEL_ID")
SECRET_CHANNEL_ID = env.int("SECRET_CHANNEL_ID")