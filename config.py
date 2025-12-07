import os
import logging

# --- ОСНОВНЫЕ НАСТРОЙКИ ---

# Токен бота — только из переменной окружения
TOKEN = os.getenv('TOKEN', '')
if not TOKEN:
    raise RuntimeError("Environment variable TOKEN is required")

# ID админа (для команд /reset, /cancel чужих игр)
# Можно узнать у @userinfobot; хранить в переменной окружения
ADMIN_ID = int(os.getenv('ADMIN_ID', ''))

SKIP_PENDING = False  # Пропускать ли старые сообщения при запуске бота
DELETE_FROM_EVERYONE = False  # Удалять ли сообщения у всех (нужны права админа) или только у бота

# --- НАСТРОЙКИ ИГРЫ ---

# Минимальное кол-во игроков (4 для Новогоднего режима, 6+ для классики)
PLAYERS_COUNT_TO_START = 4

# Максимальное кол-во игроков (увеличил до 12, чтобы работали все роли из handlers.py)
PLAYERS_COUNT_LIMIT = 12 

# Время жизни заявки на игру (в секундах). 10 минут = 600 сек.
REQUEST_OVERDUE_TIME = 2 * 60 

# --- ПУТИ К ФАЙЛАМ ---

# Базовый путь проекта
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---

LOGGER_LEVEL = logging.INFO

# --- НАСТРОЙКИ WEBHOOK (ДЛЯ СЕРВЕРА) ---

# Если False — используется Polling (для запуска на компьютере)
# Если True — используется Webhook (для продакшн сервера с белым IP)
SET_WEBHOOK = False 

if SET_WEBHOOK:
    # IP вашего сервера (где запущен бот)
    SERVER_IP = os.getenv('SERVER_IP', '0.0.0.0')
    
    # Порт (обычно 443, 80, 88 или 8443 для Telegram)
    SERVER_PORT = int(os.getenv('SERVER_PORT', 443))
    
    # Пути к SSL сертификатам (нужны только для самоподписанных сертификатов)
    # Если используете Cloudflare или Nginx с Let's Encrypt, оставьте None
    SSL_CERT = os.getenv('SSL_CERT', '/path/to/cert.pem')
    SSL_PRIV = os.getenv('SSL_PRIV', '/path/to/private.key')
