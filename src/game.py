from bot import bot
import database
from html import escape 
import random

role_titles = {
    # --- Базовые роли ---
    'mafia': '🎩 Морозник (Мафия)',
    'don': '🕯 Тёмный Эльф (Дон)',
    'sheriff': '🎅 Санта (Шериф)',
    'doctor': '🧦 Эльф-лекарь (Доктор)',
    'peace': '🎁 Добряк (Мирный)',
    'civilian': '🎁 Добряк (Мирный)',
    
    # --- Новые роли (Классика/Расширенные) ---
    'mistress': '💃 Снегурочка (Любовница)',
    'drunkard': '🍷 Уставший Олень (Пьяница)',
    'kamikaze': '🧨 Хлопушка (Камикадзе)',
    'deputy': '👮 Младший Олень (Помощник Шерифа)',
    
    # --- Спецроли (Новогодние) ---
    'snowman': '🛷 Снеговик (Телохранитель)',
    'angel': '✨ Ангел (Спасатель)',
    'tracker': '🧊 Следопыт',
    'bell': '🔔 Колокольчик',
    
    # --- Новогодний режим (3 игрока) ---
    'xmas_santa': '🎅 Санта (Цель)',
    'xmas_elf': '🛡 Верный Эльф',
    'xmas_dark_elf': '🏹 Тёмный Эльф',
    
    # --- Спецроли зла ---
    'shadow': '🌑 Тень',
    'krampus': '💀 Крампус',
    'grinch': '🎄 Гринч'
}

def get_role_name(role_code):
    return role_titles.get(role_code, f'❓ Роль ({role_code})')

def stop_game(game, reason):
    winner_text = reason
    roles_list = []
    for i, p in enumerate(game['players']):
        safe_name = escape(p.get("full_name", p.get("name", "Игрок")))
        role_code = p.get("role", "civilian")
        role_title = get_role_name(role_code)
        status_icon = "💀" if not p.get('alive', True) else "👤"
        roles_list.append(f'{i+1}. {status_icon} <b>{safe_name}</b> — {role_title}')

    full_text = f'🎄 <b>Игра завершена!</b>\n\n{winner_text}\n\n🎭 <b>Маски сброшены:</b>\n' + '\n'.join(roles_list)
    bot.try_to_send_message(game['chat'], full_text, parse_mode='HTML')
    database.delete_one('games', {'_id': game['_id']})

def start_game(chat_id, players, mode='full'):
    players_count = len(players)
    cards = []
    
    # --- БАЛАНСИРОВКА ---
    if mode == 'xmas' or players_count == 3:
        cards = ['xmas_santa', 'xmas_elf', 'xmas_dark_elf']
    elif players_count <= 5:
        cards = ['mafia', 'sheriff', 'doctor', 'peace', 'peace'][:players_count]
    else:
        # Основа
        mafia_count = max(1, players_count // 3)
        cards = ['mafia'] * mafia_count
        cards.extend(['sheriff', 'doctor', 'don'])
        
        # Добавляем интересные роли
        optional_roles = ['mistress', 'drunkard', 'kamikaze', 'deputy', 'snowman', 'tracker']
        random.shuffle(optional_roles)
        
        while len(cards) < players_count and optional_roles:
            cards.append(optional_roles.pop(0))
            
        # Добиваем мирными
        while len(cards) < players_count:
            cards.append('peace')
            
    random.shuffle(cards)
    
    game_players = []
    for i, p in enumerate(players):
        p_obj = p.copy()
        p_obj['role'] = cards[i]
        p_obj['alive'] = True
        p_obj['pm_id'] = None # Для редактирования сообщений
        game_players.append(p_obj)

    game = {
        'game': 'mafia', 'mode': mode, 'chat': chat_id, 'stage': -4,
        'day_count': 0, 'players': game_players, 'cards': cards,
        'don': [], 'vote': {}, 'shots': [], 'heals': [], 'played': [], 'events': [], 
        'shields': [], 'blessings': [], 'tracks': [], 'stolen': [], 
        'blocks': [], 'silenced': [], # Для Любовницы и Пьяницы
        'current_event': None, 'caramel_mode': False
    }
    
    return database.insert_one('games', game), game