import logging
import sys

# Пытаемся импортировать настройки, иначе ставим INFO по умолчанию
try:
    from config import LOGGER_LEVEL
except ImportError:
    LOGGER_LEVEL = logging.INFO

class Colors:
    GREEN = '\033[0;32m'
    GRAY = '\033[0;37m'
    RESET = '\033[0m'

def configure_logger():
    logger = logging.getLogger("mafbot")
    logger.setLevel(LOGGER_LEVEL)
    
    # Логируем в стандартный вывод (консоль)
    terminal_logger = logging.StreamHandler(sys.stdout)
    
    # Формат: [Время] Сообщение
    # \r используется, чтобы курсор возвращался в начало строки (полезно при tqdm, но тут опционально)
    formatter = logging.Formatter(
        f"\r{Colors.GRAY}[%(asctime)s.%(msecs).03d]{Colors.RESET} %(message)s", 
        datefmt="%H:%M:%S"
    )
    
    terminal_logger.setFormatter(formatter)
    logger.addHandler(terminal_logger)
    logger.propagate = False
    
    return logger

# Отключаем лишний шум от библиотеки werkzeug (веб-сервер)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Инициализируем логгер
logger = configure_logger()

def log_update(update):
    """
    Логирует входящее событие от Telegram.
    Нужно вызывать эту функцию перед обработкой апдейта.
    """
    msg = ''
    qc = Colors.RESET
    chat_id = 0
    user_id = 0
    
    # 1. Обычное сообщение
    if update.message:
        chat_id = update.message.chat.id
        user_id = update.message.from_user.id
        # Если текста нет (стикер, фото), ставим пустую строку
        msg = update.message.text if update.message.text else '<media>'
        qc = Colors.RESET
        
    # 2. Нажатие на кнопку (Callback)
    elif update.callback_query:
        chat_id = update.callback_query.message.chat.id
        user_id = update.callback_query.from_user.id
        msg = update.callback_query.data
        qc = Colors.GREEN
        
    # 3. Редактирование сообщения (добавил для полноты)
    elif update.edited_message:
        chat_id = update.edited_message.chat.id
        user_id = update.edited_message.from_user.id
        msg = f"[EDIT] {update.edited_message.text}"
        qc = Colors.GRAY
        
    else:
        # Другие типы событий (inline, channel_post) пока игнорируем или логируем кратко
        return

    # repr() экранирует спецсимволы (например \n), срез [1:-1] убирает кавычки
    safe_msg = repr(msg)[1:-1]
    
    # Форматирование: <ChatID : UserID> Текст
    logger.info(f'<{chat_id:>14}:{user_id:<9}> {qc}{safe_msg}{Colors.RESET}')