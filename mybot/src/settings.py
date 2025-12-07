"""
Модуль настроек игры с интерактивными кнопками
"""
import database
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройки по умолчанию для каждой группы
DEFAULT_SETTINGS = {
    'discussion_time': 300,  # 5 минут обсуждения
    'vote_time': 30,  # 30 секунд голосования
    'night_time': 30,  # 30 секунд на ночные действия
    'auto_start': False,  # Автоматический старт при наборе игроков
    'min_players': 4,  # Минимальное количество игроков
    'max_players': 12,  # Максимальное количество игроков
    'show_roles_on_end': True,  # Показывать роли в конце игры
    'events_enabled': True,  # Включены ли события (метель, костёр и т.д.)
}

# Кэш настроек для быстрого доступа
_settings_cache = {}

def get_settings(chat_id):
    """Получить настройки для чата (с кэшированием)"""
    # Проверяем кэш
    if chat_id in _settings_cache:
        return _settings_cache[chat_id]
    
    settings = database.find_one('settings', {'chat_id': chat_id})
    if not settings:
        settings = {'chat_id': chat_id, **DEFAULT_SETTINGS}
        database.insert_one('settings', settings)
    
    # Сохраняем в кэш
    _settings_cache[chat_id] = settings
    return settings

def clear_settings_cache(chat_id=None):
    """Очистить кэш настроек"""
    global _settings_cache
    if chat_id:
        _settings_cache.pop(chat_id, None)
    else:
        _settings_cache.clear()

def update_setting(chat_id, key, value):
    """Обновить настройку"""
    database.update_one('settings', {'chat_id': chat_id}, {'$set': {key: value}}, upsert=True)
    # Очищаем кэш для этого чата
    clear_settings_cache(chat_id)

def get_settings_keyboard(chat_id):
    """Создать клавиатуру настроек"""
    settings = get_settings(chat_id)
    kb = InlineKeyboardMarkup(row_width=2)
    
    # Время обсуждения
    disc_time = settings.get('discussion_time', 300)
    disc_min = disc_time // 60
    kb.add(InlineKeyboardButton(
        f"⏱ Обсуждение: {disc_min} мин",
        callback_data='settings_discussion'
    ))
    
    # Время голосования
    vote_time = settings.get('vote_time', 30)
    kb.add(InlineKeyboardButton(
        f"🗳 Голосование: {vote_time} сек",
        callback_data='settings_vote'
    ))
    
    # Время ночи
    night_time = settings.get('night_time', 30)
    kb.add(InlineKeyboardButton(
        f"🌙 Ночь: {night_time} сек",
        callback_data='settings_night'
    ))
    
    # Минимум игроков
    min_players = settings.get('min_players', 4)
    kb.add(InlineKeyboardButton(
        f"👥 Мин. игроков: {min_players}",
        callback_data='settings_min_players'
    ))
    
    # Максимум игроков
    max_players = settings.get('max_players', 12)
    kb.add(InlineKeyboardButton(
        f"👥 Макс. игроков: {max_players}",
        callback_data='settings_max_players'
    ))
    
    # Автостарт
    auto_start = "✅" if settings.get('auto_start', False) else "❌"
    kb.add(InlineKeyboardButton(
        f"{auto_start} Автостарт",
        callback_data='settings_auto_start'
    ))
    
    # События
    events = "✅" if settings.get('events_enabled', True) else "❌"
    kb.add(InlineKeyboardButton(
        f"{events} События",
        callback_data='settings_events'
    ))
    
    # Показывать роли
    show_roles = "✅" if settings.get('show_roles_on_end', True) else "❌"
    kb.add(InlineKeyboardButton(
        f"{show_roles} Роли в конце",
        callback_data='settings_show_roles'
    ))
    
    kb.add(InlineKeyboardButton("🔄 Сбросить", callback_data='settings_reset'))
    kb.add(InlineKeyboardButton("❌ Закрыть", callback_data='settings_close'))
    
    return kb

def get_discussion_time_keyboard(chat_id):
    """Клавиатура для выбора времени обсуждения"""
    kb = InlineKeyboardMarkup(row_width=3)
    times = [1, 2, 3, 5, 7, 10]  # минуты
    for t in times:
        kb.add(InlineKeyboardButton(
            f"{t} мин",
            callback_data=f'settings_set_discussion_{t * 60}'
        ))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data='settings_back'))
    return kb

def get_vote_time_keyboard(chat_id):
    """Клавиатура для выбора времени голосования"""
    kb = InlineKeyboardMarkup(row_width=3)
    times = [15, 30, 45, 60, 90, 120]  # секунды
    for t in times:
        kb.add(InlineKeyboardButton(
            f"{t} сек",
            callback_data=f'settings_set_vote_{t}'
        ))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data='settings_back'))
    return kb

def get_night_time_keyboard(chat_id):
    """Клавиатура для выбора времени ночи"""
    kb = InlineKeyboardMarkup(row_width=3)
    times = [15, 20, 30, 45, 60]  # секунды
    for t in times:
        kb.add(InlineKeyboardButton(
            f"{t} сек",
            callback_data=f'settings_set_night_{t}'
        ))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data='settings_back'))
    return kb

def get_min_players_keyboard(chat_id):
    """Клавиатура для выбора минимума игроков"""
    kb = InlineKeyboardMarkup(row_width=3)
    for n in range(3, 8):
        kb.add(InlineKeyboardButton(
            f"{n}",
            callback_data=f'settings_set_min_players_{n}'
        ))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data='settings_back'))
    return kb

def get_max_players_keyboard(chat_id):
    """Клавиатура для выбора максимума игроков"""
    kb = InlineKeyboardMarkup(row_width=3)
    for n in range(6, 16):
        kb.add(InlineKeyboardButton(
            f"{n}",
            callback_data=f'settings_set_max_players_{n}'
        ))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data='settings_back'))
    return kb

