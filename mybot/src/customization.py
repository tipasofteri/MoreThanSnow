# customization.py
import database
import logging

logger = logging.getLogger(__name__)

def get_customization(user_id, chat_id=None):
    """Получить кастомизацию для пользователя"""
    query = {'user_id': user_id}
    if chat_id:
        query['chat_id'] = chat_id
    
    customization = database.find_one('customizations', query)
    if not customization:
        # Возвращаем дефолтную кастомизацию
        return {
            'user_id': user_id,
            'chat_id': chat_id,
            'role_prefix': '',
            'role_suffix': '',
            'name_formatting': 'normal'  # normal, bold, italic
        }
    return customization

def set_role_prefix(user_id, prefix, chat_id=None):
    """Установить префикс для роли"""
    query = {'user_id': user_id}
    if chat_id:
        query['chat_id'] = chat_id
    
    customization = database.find_one('customizations', query)
    if customization:
        database.update_one('customizations', {'_id': customization['_id']}, {
            '$set': {'role_prefix': prefix}
        })
    else:
        customization = {
            'user_id': user_id,
            'chat_id': chat_id,
            'role_prefix': prefix,
            'role_suffix': '',
            'name_formatting': 'normal'
        }
        database.insert_one('customizations', customization)
    return True

def set_role_suffix(user_id, suffix, chat_id=None):
    """Установить суффикс для роли"""
    query = {'user_id': user_id}
    if chat_id:
        query['chat_id'] = chat_id
    
    customization = database.find_one('customizations', query)
    if customization:
        database.update_one('customizations', {'_id': customization['_id']}, {
            '$set': {'role_suffix': suffix}
        })
    else:
        customization = {
            'user_id': user_id,
            'chat_id': chat_id,
            'role_prefix': '',
            'role_suffix': suffix,
            'name_formatting': 'normal'
        }
        database.insert_one('customizations', customization)
    return True

def set_name_formatting(user_id, formatting, chat_id=None):
    """Установить форматирование имени (normal, bold, italic)"""
    if formatting not in ('normal', 'bold', 'italic'):
        return False
    
    query = {'user_id': user_id}
    if chat_id:
        query['chat_id'] = chat_id
    
    customization = database.find_one('customizations', query)
    if customization:
        database.update_one('customizations', {'_id': customization['_id']}, {
            '$set': {'name_formatting': formatting}
        })
    else:
        customization = {
            'user_id': user_id,
            'chat_id': chat_id,
            'role_prefix': '',
            'role_suffix': '',
            'name_formatting': formatting
        }
        database.insert_one('customizations', customization)
    return True

def format_role_name(role_name, user_id, chat_id=None):
    """Форматировать имя роли с учетом кастомизации"""
    customization = get_customization(user_id, chat_id)
    
    prefix = customization.get('role_prefix', '')
    suffix = customization.get('role_suffix', '')
    formatting = customization.get('name_formatting', 'normal')
    
    # Применяем форматирование
    if formatting == 'bold':
        role_name = f'<b>{role_name}</b>'
    elif formatting == 'italic':
        role_name = f'<i>{role_name}</i>'
    
    # Добавляем префикс и суффикс
    if prefix:
        role_name = f'{prefix} {role_name}'
    if suffix:
        role_name = f'{role_name} {suffix}'
    
    return role_name

def award_customization_from_achievement(user_id, achievement_id):
    """Выдать кастомизацию за достижение"""
    # Определяем, какая кастомизация выдается за достижение
    achievement_rewards = {
        'first_win': {'prefix': '🏆', 'suffix': ''},
        'win_streak_5': {'prefix': '🔥', 'suffix': ''},
        'win_streak_10': {'prefix': '💎', 'suffix': ''},
        'games_100': {'prefix': '⭐', 'suffix': ''},
        'games_500': {'prefix': '👑', 'suffix': ''},
        'elo_2000': {'prefix': '', 'suffix': '👑'},
        'elo_1800': {'prefix': '', 'suffix': '💎'},
        'elo_1600': {'prefix': '', 'suffix': '⭐'},
        'perfect_game': {'prefix': '✨', 'suffix': '✨'},
        'mafia_master': {'prefix': '😈', 'suffix': ''},
        'peaceful_guardian': {'prefix': '🛡️', 'suffix': ''},
    }
    
    reward = achievement_rewards.get(achievement_id)
    if not reward:
        return False
    
    # Применяем награду
    if reward.get('prefix'):
        set_role_prefix(user_id, reward['prefix'])
    if reward.get('suffix'):
        set_role_suffix(user_id, reward['suffix'])
    
    return True

def clear_customization(user_id, chat_id=None):
    """Очистить кастомизацию"""
    query = {'user_id': user_id}
    if chat_id:
        query['chat_id'] = chat_id
    
    database.delete_one('customizations', query)
    return True

