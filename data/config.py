from environs import Env

env = Env()
env.read_env()

BOT_TOKEN = env.str("BOT_TOKEN")
ADMINS = env.list("ADMIN_ID")  # .env dagi ADMIN_ID ni o'qiydi
DB_URL = env.str("DB_URL")
REDIS_URL = env.str("REDIS_URL")