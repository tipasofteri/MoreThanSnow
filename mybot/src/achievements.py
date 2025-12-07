# achievements.py
"""
Система достижений для игры в мафию
"""
import database
from datetime import datetime
from typing import Dict, List, Optional

# Определение всех достижений
ACHIEVEMENTS = {
    # Первые шаги
    'first_game': {
        'id': 'first_game',
        'name': 'Первая игра',
        'description': 'Сыграйте свою первую игру',
        'icon': '🎮',
        'rarity': 'common',
        'reward_candies': 5
    },
    'first_win': {
        'id': 'first_win',
        'name': 'Первая победа',
        'description': 'Выиграйте свою первую игру',
        'icon': '🏆',
        'rarity': 'common',
        'reward_candies': 10
    },
    'first_mafia_win': {
        'id': 'first_mafia_win',
        'name': 'Победа зла',
        'description': 'Выиграйте впервые за мафию',
        'icon': '😈',
        'rarity': 'uncommon',
        'reward_candies': 15
    },
    'first_maniac_win': {
        'id': 'first_maniac_win',
        'name': 'Один против всех',
        'description': 'Выиграйте впервые за маньяка',
        'icon': '💀',
        'rarity': 'rare',
        'reward_candies': 25
    },
    
    # Количество игр
    'games_10': {
        'id': 'games_10',
        'name': 'Опытный игрок',
        'description': 'Сыграйте 10 игр',
        'icon': '📊',
        'rarity': 'common',
        'reward_candies': 20
    },
    'games_50': {
        'id': 'games_50',
        'name': 'Ветеран',
        'description': 'Сыграйте 50 игр',
        'icon': '🎯',
        'rarity': 'uncommon',
        'reward_candies': 50
    },
    'games_100': {
        'id': 'games_100',
        'name': 'Мастер игры',
        'description': 'Сыграйте 100 игр',
        'icon': '⭐',
        'rarity': 'rare',
        'reward_candies': 100
    },
    'games_500': {
        'id': 'games_500',
        'name': 'Легенда',
        'description': 'Сыграйте 500 игр',
        'icon': '👑',
        'rarity': 'legendary',
        'reward_candies': 500
    },
    
    # Победы
    'wins_10': {
        'id': 'wins_10',
        'name': 'Победитель',
        'description': 'Выиграйте 10 игр',
        'icon': '✅',
        'rarity': 'common',
        'reward_candies': 30
    },
    'wins_50': {
        'id': 'wins_50',
        'name': 'Чемпион',
        'description': 'Выиграйте 50 игр',
        'icon': '🏅',
        'rarity': 'uncommon',
        'reward_candies': 75
    },
    'wins_100': {
        'id': 'wins_100',
        'name': 'Непобедимый',
        'description': 'Выиграйте 100 игр',
        'icon': '💎',
        'rarity': 'rare',
        'reward_candies': 150
    },
    
    # Роли
    'all_roles': {
        'id': 'all_roles',
        'name': 'Мастер перевоплощений',
        'description': 'Сыграйте всеми 13 ролями',
        'icon': '🎭',
        'rarity': 'rare',
        'reward_candies': 200
    },
    'role_mafia_10': {
        'id': 'role_mafia_10',
        'name': 'Гринч',
        'description': 'Сыграйте 10 раз за мафию',
        'icon': '🎩',
        'rarity': 'uncommon',
        'reward_candies': 40
    },
    'role_don_10': {
        'id': 'role_don_10',
        'name': 'Тёмный Эльф',
        'description': 'Сыграйте 10 раз за Дона',
        'icon': '🕯',
        'rarity': 'uncommon',
        'reward_candies': 40
    },
    'role_commissar_10': {
        'id': 'role_commissar_10',
        'name': 'Санта-Комиссар',
        'description': 'Сыграйте 10 раз за Комиссара',
        'icon': '🎅',
        'rarity': 'uncommon',
        'reward_candies': 40
    },
    'role_doctor_10': {
        'id': 'role_doctor_10',
        'name': 'Эльф-лекарь',
        'description': 'Сыграйте 10 раз за Доктора',
        'icon': '🧦',
        'rarity': 'uncommon',
        'reward_candies': 40
    },
    'role_maniac_10': {
        'id': 'role_maniac_10',
        'name': 'Крампус',
        'description': 'Сыграйте 10 раз за Маньяка',
        'icon': '💀',
        'rarity': 'rare',
        'reward_candies': 60
    },
    
    # Специальные достижения
    'win_streak_5': {
        'id': 'win_streak_5',
        'name': 'Горячая серия',
        'description': 'Выиграйте 5 игр подряд',
        'icon': '🔥',
        'rarity': 'rare',
        'reward_candies': 100
    },
    'survive_5_nights': {
        'id': 'survive_5_nights',
        'name': 'Неуязвимый',
        'description': 'Выживите 5 ночей подряд',
        'icon': '🛡️',
        'rarity': 'rare',
        'reward_candies': 80
    },
    'elo_1500': {
        'id': 'elo_1500',
        'name': 'Опытный',
        'description': 'Достигните рейтинга 1500',
        'icon': '📈',
        'rarity': 'uncommon',
        'reward_candies': 50
    },
    'elo_1800': {
        'id': 'elo_1800',
        'name': 'Мастер',
        'description': 'Достигните рейтинга 1800',
        'icon': '💎',
        'rarity': 'rare',
        'reward_candies': 150
    },
    'elo_2000': {
        'id': 'elo_2000',
        'name': 'Легенда',
        'description': 'Достигните рейтинга 2000',
        'icon': '👑',
        'rarity': 'legendary',
        'reward_candies': 500
    },
    'win_all_teams': {
        'id': 'win_all_teams',
        'name': 'Универсал',
        'description': 'Выиграйте за все команды (мирные, мафия, маньяк)',
        'icon': '🎯',
        'rarity': 'rare',
        'reward_candies': 100
    },
    'perfect_game': {
        'id': 'perfect_game',
        'name': 'Идеальная игра',
        'description': 'Выиграйте игру, не потеряв ни одного союзника',
        'icon': '✨',
        'rarity': 'epic',
        'reward_candies': 200
    },
    'kamikaze_boom': {
        'id': 'kamikaze_boom',
        'name': 'Камикадзе',
        'description': 'Заберите кого-то с собой как Камикадзе',
        'icon': '🧨',
        'rarity': 'uncommon',
        'reward_candies': 30
    },
    'doctor_save_self': {
        'id': 'doctor_save_self',
        'name': 'Самолечение',
        'description': 'Спасите себя как Доктор',
        'icon': '💊',
        'rarity': 'uncommon',
        'reward_candies': 25
    },
    'commissar_find_mafia': {
        'id': 'commissar_find_mafia',
        'name': 'Сыщик',
        'description': 'Найдите мафию как Комиссар',
        'icon': '🔍',
        'rarity': 'uncommon',
        'reward_candies': 20
    },
    'don_find_commissar': {
        'id': 'don_find_commissar',
        'name': 'Охотник',
        'description': 'Найдите Комиссара как Дон',
        'icon': '🎯',
        'rarity': 'uncommon',
        'reward_candies': 20
    },
    'bum_witness': {
        'id': 'bum_witness',
        'name': 'Свидетель',
        'description': 'Станьте свидетелем действия как Бомж',
        'icon': '👁️',
        'rarity': 'uncommon',
        'reward_candies': 15
    },
    'mistress_block': {
        'id': 'mistress_block',
        'name': 'Соблазнительница',
        'description': 'Заблокируйте игрока как Любовница',
        'icon': '💃',
        'rarity': 'uncommon',
        'reward_candies': 15
    },
    'lawyer_protect': {
        'id': 'lawyer_protect',
        'name': 'Защитник',
        'description': 'Защитите подзащитного как Адвокат',
        'icon': '⚖️',
        'rarity': 'uncommon',
        'reward_candies': 15
    },
    'sergeant_promote': {
        'id': 'sergeant_promote',
        'name': 'Повышение',
        'description': 'Станьте Комиссаром как Сержант',
        'icon': '👮',
        'rarity': 'rare',
        'reward_candies': 50
    },
    'mafia_become_don': {
        'id': 'mafia_become_don',
        'name': 'Новый босс',
        'description': 'Станьте Доном как Мафия',
        'icon': '🎩',
        'rarity': 'rare',
        'reward_candies': 50
    },
    'lucky_survive': {
        'id': 'lucky_survive',
        'name': 'Счастливчик',
        'description': 'Выживите при покушении как Счастливчик',
        'icon': '🍀',
        'rarity': 'uncommon',
        'reward_candies': 20
    },
    'suicide_win': {
        'id': 'suicide_win',
        'name': 'Снегодуй',
        'description': 'Выиграйте как Самоубийца',
        'icon': '❄️',
        'rarity': 'epic',
        'reward_candies': 300
    },
    'candies_1000': {
        'id': 'candies_1000',
        'name': 'Сладкоежка',
        'description': 'Накопите 1000 конфет',
        'icon': '🍭',
        'rarity': 'uncommon',
        'reward_candies': 50
    },
    'candies_5000': {
        'id': 'candies_5000',
        'name': 'Конфетный магнат',
        'description': 'Накопите 5000 конфет',
        'icon': '🍬',
        'rarity': 'rare',
        'reward_candies': 200
    },
}

def get_achievement(achievement_id: str) -> Optional[Dict]:
    """Получить информацию о достижении"""
    return ACHIEVEMENTS.get(achievement_id)

def check_achievements(user_id: int, game_result: Dict, stats: Dict) -> List[Dict]:
    """
    Проверить и выдать достижения игроку после игры
    
    Args:
        user_id: ID игрока
        game_result: Результат игры (role, won, alive, etc.)
        stats: Текущая статистика игрока
    
    Returns:
        Список новых достижений
    """
    new_achievements = []
    games_played = stats.get('games_played', 0)
    games_won = stats.get('games_won', 0)
    games_lost = stats.get('games_lost', 0)
    roles_played = stats.get('roles_played', {})
    wins_by_role = stats.get('wins_by_role', {})
    wins_by_team = stats.get('wins_by_team', {})
    elo_rating = stats.get('elo_rating', 1000)
    candies = stats.get('candies', 0)
    
    # Получаем уже полученные достижения
    player_achievements = stats.get('achievements', [])
    achieved_ids = set(player_achievements)
    
    role = game_result.get('role', 'peace')
    won = game_result.get('won', False)
    is_alive = game_result.get('alive', False)
    
    # Первая игра
    if 'first_game' not in achieved_ids and games_played == 1:
        new_achievements.append(ACHIEVEMENTS['first_game'])
    
    # Первая победа
    if 'first_win' not in achieved_ids and games_won == 1:
        new_achievements.append(ACHIEVEMENTS['first_win'])
    
    # Первая победа за мафию
    if 'first_mafia_win' not in achieved_ids and won and role in ('mafia', 'don') and wins_by_team.get('mafia', 0) == 1:
        new_achievements.append(ACHIEVEMENTS['first_mafia_win'])
    
    # Первая победа за маньяка
    if 'first_maniac_win' not in achieved_ids and won and role == 'maniac' and wins_by_team.get('maniac', 0) == 1:
        new_achievements.append(ACHIEVEMENTS['first_maniac_win'])
    
    # Количество игр
    if 'games_10' not in achieved_ids and games_played >= 10:
        new_achievements.append(ACHIEVEMENTS['games_10'])
    if 'games_50' not in achieved_ids and games_played >= 50:
        new_achievements.append(ACHIEVEMENTS['games_50'])
    if 'games_100' not in achieved_ids and games_played >= 100:
        new_achievements.append(ACHIEVEMENTS['games_100'])
    if 'games_500' not in achieved_ids and games_played >= 500:
        new_achievements.append(ACHIEVEMENTS['games_500'])
    
    # Количество побед
    if 'wins_10' not in achieved_ids and games_won >= 10:
        new_achievements.append(ACHIEVEMENTS['wins_10'])
    if 'wins_50' not in achieved_ids and games_won >= 50:
        new_achievements.append(ACHIEVEMENTS['wins_50'])
    if 'wins_100' not in achieved_ids and games_won >= 100:
        new_achievements.append(ACHIEVEMENTS['wins_100'])
    
    # Все роли
    if 'all_roles' not in achieved_ids:
        all_roles = {'peace', 'mafia', 'don', 'commissar', 'sergeant', 'doctor', 'maniac', 
                     'mistress', 'lawyer', 'suicide', 'bum', 'lucky', 'kamikaze'}
        played_roles = set(roles_played.keys())
        if all_roles.issubset(played_roles):
            new_achievements.append(ACHIEVEMENTS['all_roles'])
    
    # Роли по 10 раз
    if 'role_mafia_10' not in achieved_ids and roles_played.get('mafia', 0) >= 10:
        new_achievements.append(ACHIEVEMENTS['role_mafia_10'])
    if 'role_don_10' not in achieved_ids and roles_played.get('don', 0) >= 10:
        new_achievements.append(ACHIEVEMENTS['role_don_10'])
    if 'role_commissar_10' not in achieved_ids and roles_played.get('commissar', 0) >= 10:
        new_achievements.append(ACHIEVEMENTS['role_commissar_10'])
    if 'role_doctor_10' not in achieved_ids and roles_played.get('doctor', 0) >= 10:
        new_achievements.append(ACHIEVEMENTS['role_doctor_10'])
    if 'role_maniac_10' not in achieved_ids and roles_played.get('maniac', 0) >= 10:
        new_achievements.append(ACHIEVEMENTS['role_maniac_10'])
    
    # Рейтинг
    if 'elo_1500' not in achieved_ids and elo_rating >= 1500:
        new_achievements.append(ACHIEVEMENTS['elo_1500'])
    if 'elo_1800' not in achieved_ids and elo_rating >= 1800:
        new_achievements.append(ACHIEVEMENTS['elo_1800'])
    if 'elo_2000' not in achieved_ids and elo_rating >= 2000:
        new_achievements.append(ACHIEVEMENTS['elo_2000'])
    
    # Победы за все команды
    if 'win_all_teams' not in achieved_ids:
        if wins_by_team.get('peaceful', 0) > 0 and wins_by_team.get('mafia', 0) > 0 and wins_by_team.get('maniac', 0) > 0:
            new_achievements.append(ACHIEVEMENTS['win_all_teams'])
    
    # Конфеты
    if 'candies_1000' not in achieved_ids and candies >= 1000:
        new_achievements.append(ACHIEVEMENTS['candies_1000'])
    if 'candies_5000' not in achieved_ids and candies >= 5000:
        new_achievements.append(ACHIEVEMENTS['candies_5000'])
    
    return new_achievements

def check_special_achievements(user_id: int, game_result: Dict, stats: Dict, game_data: Dict) -> List[Dict]:
    """
    Проверить специальные достижения, связанные с конкретной игрой
    
    Args:
        user_id: ID игрока
        game_result: Результат игры (role, won, alive, etc.)
        stats: Текущая статистика игрока
        game_data: Данные игры (для проверки специальных условий)
    
    Returns:
        Список новых достижений
    """
    new_achievements = []
    player_achievements = stats.get('achievements', [])
    achieved_ids = set(player_achievements)
    
    role = game_result.get('role', 'peace')
    won = game_result.get('won', False)
    is_alive = game_result.get('alive', False)
    
    # Проверяем специальные достижения на основе данных игры
    # Это будет вызываться из game.py с дополнительной информацией
    
    return new_achievements

def award_achievement(user_id: int, achievement: Dict) -> bool:
    """
    Выдать достижение игроку и начислить награду
    
    Returns:
        True если достижение успешно выдано
    """
    try:
        stats = database.find_one('player_stats', {'user_id': user_id})
        if not stats:
            return False
        
        achievements = stats.get('achievements', [])
        if achievement['id'] in achievements:
            return False  # Уже получено
        
        # Добавляем достижение
        achievements.append(achievement['id'])
        
        # Начисляем конфеты
        candies = stats.get('candies', 0) + achievement.get('reward_candies', 0)
        
        # Сохраняем
        database.update_one('player_stats', {'user_id': user_id}, {
            '$set': {
                'achievements': achievements,
                'candies': candies
            }
        })
        
        # Выдаем кастомизацию за достижение (если есть)
        try:
            from customization import award_customization_from_achievement
            award_customization_from_achievement(user_id, achievement['id'])
        except ImportError:
            pass  # Модуль кастомизации не найден, пропускаем
        
        return True
    except Exception as e:
        print(f"Error awarding achievement: {e}")
        return False

def get_player_achievements(user_id: int) -> List[Dict]:
    """Получить все достижения игрока"""
    stats = database.find_one('player_stats', {'user_id': user_id})
    if not stats:
        return []
    
    achievement_ids = stats.get('achievements', [])
    achievements = []
    for ach_id in achievement_ids:
        if ach_id in ACHIEVEMENTS:
            achievements.append(ACHIEVEMENTS[ach_id])
    
    return achievements

def get_achievements_by_rarity(rarity: str = None) -> List[Dict]:
    """Получить все достижения, опционально отфильтрованные по редкости"""
    if rarity:
        return [ach for ach in ACHIEVEMENTS.values() if ach['rarity'] == rarity]
    return list(ACHIEVEMENTS.values())

def get_achievement_progress(user_id: int, achievement_id: str) -> Dict:
    """Получить прогресс игрока по конкретному достижению"""
    stats = database.find_one('player_stats', {'user_id': user_id})
    if not stats:
        return {'completed': False, 'progress': 0, 'total': 0}
    
    achievement = ACHIEVEMENTS.get(achievement_id)
    if not achievement:
        return {'completed': False, 'progress': 0, 'total': 0}
    
    # Проверяем, получено ли достижение
    achievements = stats.get('achievements', [])
    if achievement_id in achievements:
        return {'completed': True, 'progress': 100, 'total': 100}
    
    # Рассчитываем прогресс в зависимости от типа достижения
    progress = 0
    total = 100
    
    if achievement_id == 'games_10':
        progress = min(100, (stats.get('games_played', 0) / 10) * 100)
    elif achievement_id == 'games_50':
        progress = min(100, (stats.get('games_played', 0) / 50) * 100)
    elif achievement_id == 'games_100':
        progress = min(100, (stats.get('games_played', 0) / 100) * 100)
    elif achievement_id == 'wins_10':
        progress = min(100, (stats.get('games_won', 0) / 10) * 100)
    elif achievement_id == 'wins_50':
        progress = min(100, (stats.get('games_won', 0) / 50) * 100)
    elif achievement_id == 'elo_1500':
        current_elo = stats.get('elo_rating', 1000)
        progress = min(100, ((current_elo - 1000) / 500) * 100)
    elif achievement_id == 'elo_1800':
        current_elo = stats.get('elo_rating', 1000)
        progress = min(100, ((current_elo - 1000) / 800) * 100)
    elif achievement_id == 'elo_2000':
        current_elo = stats.get('elo_rating', 1000)
        progress = min(100, ((current_elo - 1000) / 1000) * 100)
    # Добавить больше типов прогресса по необходимости
    
    return {'completed': False, 'progress': int(progress), 'total': total}

