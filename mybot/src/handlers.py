import config
import database
import lang
import logging
import os
from logging.handlers import RotatingFileHandler
from game import role_titles, stop_game, start_game
from stages import stages, go_to_next_stage, format_roles, get_votes, send_player_message
from bot import bot

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from telebot.apihelper import ApiException
try:
    from settings import (
        get_settings, update_setting, get_settings_keyboard,
        get_discussion_time_keyboard, get_vote_time_keyboard, get_night_time_keyboard,
        get_min_players_keyboard, get_max_players_keyboard, clear_settings_cache
    )
except ImportError:
    # Если модуль settings не найден, создаем заглушки
    def get_settings(chat_id):
        return {'discussion_time': 300, 'vote_time': 30, 'night_time': 30, 
                'min_players': 4, 'max_players': 12, 'auto_start': False,
                'events_enabled': True, 'show_roles_on_end': True}
    def update_setting(chat_id, key, value): pass
    def get_settings_keyboard(chat_id): return InlineKeyboardMarkup()
    def get_discussion_time_keyboard(chat_id): return InlineKeyboardMarkup()
    def get_vote_time_keyboard(chat_id): return InlineKeyboardMarkup()
    def get_night_time_keyboard(chat_id): return InlineKeyboardMarkup()
    def get_min_players_keyboard(chat_id): return InlineKeyboardMarkup()
    def get_max_players_keyboard(chat_id): return InlineKeyboardMarkup()
    def clear_settings_cache(chat_id=None): pass

import html
from time import time
from uuid import uuid4

# Настройка логирования
def setup_logging():
    os.makedirs('logs', exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    file_handler = RotatingFileHandler('logs/mafia_game.log', maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

logger = setup_logging()

def get_name(user):
    username = ('@' + user.username) if user.username else user.first_name
    return html.escape(username)

def get_full_name(user):
    result = user.first_name
    if user.last_name: result += ' ' + user.last_name
    return html.escape(result)

def user_object(user):
    return {'id': user.id, 'name': get_name(user), 'full_name': get_full_name(user)}

# Кэшируем username бота, чтобы не делать запрос каждый раз
_bot_username = None

def get_bot_username():
    """Получить username бота (с кэшированием)"""
    global _bot_username
    if _bot_username is None:
        try:
            _bot_username = bot.get_me().username
        except:
            _bot_username = ''  # Если не удалось получить, используем пустую строку
    return _bot_username

def command_regexp(command):
    username = get_bot_username()
    return f'^/{command}(@{username})?$' if username else f'^/{command}$'

def safe_answer_callback(call_id, text=None, show_alert=False):
    try:
        if text is not None:
            bot.answer_callback_query(callback_query_id=call_id, text=text, show_alert=show_alert)
        else:
            bot.answer_callback_query(callback_query_id=call_id)
    except ApiException as e:
        error_code = e.result.get('error_code', 0) if hasattr(e, 'result') and isinstance(e.result, dict) else 0
        if error_code == 429:
            retry_after = e.result.get('parameters', {}).get('retry_after', 1) if hasattr(e, 'result') and isinstance(e.result, dict) else 1
            from time import sleep
            sleep(retry_after)
            try:
                if text is not None:
                    bot.answer_callback_query(callback_query_id=call_id, text=text, show_alert=show_alert)
                else:
                    bot.answer_callback_query(callback_query_id=call_id)
            except:
                pass
        # Для других ошибок (например, 400 - query is too old) просто игнорируем
        pass

def safe_send_message(chat_id, text, **kwargs):
    """Безопасная отправка сообщения с обработкой ошибок 429"""
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except ApiException as e:
        error_code = e.result.get('error_code', 0) if hasattr(e, 'result') and isinstance(e.result, dict) else 0
        if error_code == 429:
            retry_after = e.result.get('parameters', {}).get('retry_after', 1) if hasattr(e, 'result') and isinstance(e.result, dict) else 1
            from time import sleep
            sleep(retry_after)
            try:
                return bot.send_message(chat_id, text, **kwargs)
            except:
                return None
        return None

def get_time_str(timestamp):
    remaining = int(timestamp - time())
    if remaining < 0: remaining = 0
    m = remaining // 60
    s = remaining % 60
    return f"{m:02}:{s:02}"

def can_act(game, user_id):
    if user_id in game.get('blocks', []):
        return False, lang.action_blocked
    if user_id in game.get('played', []):
        return False, "Ты уже сделал ход."
    return True, None

# --- ХЕНДЛЕРЫ ---

@bot.message_handler(commands=['help', 'start'])
def start_command(message, *args, **kwargs):
    # Создаем клавиатуру с inline кнопками для всех команд
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📜 Правила", callback_data='help_rules'),
        InlineKeyboardButton("⚙️ Настройки", callback_data='help_settings')
    )
    kb.add(
        InlineKeyboardButton("🎮 Создать игру", callback_data='help_create'),
        InlineKeyboardButton("📊 Статистика", callback_data='help_stats')
    )
    kb.add(
        InlineKeyboardButton("🏆 Топ игроков", callback_data='help_leaderboard'),
        InlineKeyboardButton("🎖 Достижения", callback_data='help_achievements')
    )
    kb.add(
        InlineKeyboardButton("👥 Команды", callback_data='help_team'),
        InlineKeyboardButton("🛒 Магазин", callback_data='help_shop')
    )
    
    # Добавляем кнопку WebApp если доступна
    try:
        from config import SET_WEBHOOK, SERVER_IP
        if SET_WEBHOOK and SERVER_IP:
            webapp_url = f"https://morethansnow.pythonanywhere.com"
            kb.add(InlineKeyboardButton('🌐 Открыть сайт', web_app={'url': webapp_url}))
    except:
        pass
    
    if message.text and message.text.startswith('/start'):
        start_text = (
            f'🎉 <b>Мафия: Новогодний Переполох</b> 🎉\n\n'
            '🎄 Добавь меня в группу и нажми /create\n'
            '🔔 Здесь ты будешь получать свою роль и делать ночные ходы.\n\n'
            '🎮 <b>Используйте кнопки ниже для навигации:</b>'
        )
        bot.send_message(message.chat.id, start_text, parse_mode='HTML', reply_markup=kb)
    else:
        help_text = (
            '🎮 <b>Команды:</b>\n\n'
            '📜 <code>/rules</code> - Правила игры\n'
            '⚙️ <code>/settings</code> - Настройки (в группе)\n'
            '🎮 <code>/create</code> - Создать игру (в группе)\n'
            '📊 <code>/stats</code> - Статистика игрока\n'
            '🏆 <code>/leaderboard</code> - Топ игроков\n'
            '🎖 <code>/achievements</code> - Достижения\n'
            '👥 <code>/team</code> - Команды\n'
            '🎨 <code>/customize</code> - Кастомизация ролей\n'
            '🛒 <code>/shop</code> - Магазин\n'
            '🎁 <code>/events</code> - Магазин событий\n'
            '📝 <code>/report</code> - Пожаловаться на игрока\n\n'
            '💡 <b>Используйте кнопки ниже для быстрого доступа:</b>'
        )
        bot.send_message(message.chat.id, help_text, parse_mode='HTML', reply_markup=kb)

def get_user_stats(user_id, user=None, detailed=False):
    """Получить статистику пользователя"""
        
    stats = database.find_one('player_stats', {'user_id': user_id})
    
    if not stats:
        user_name = user.first_name if user else "Игрок"
        return (
            f'📊 <b>Статистика игрока {user_name}</b>\n\n'
            '🎮 Игр сыграно: 0\n'
            '✅ Побед: 0\n'
            '❌ Поражений: 0\n'
            '🍭 Конфет: 0\n\n'
            '💡 Сыграй свою первую игру, чтобы увидеть статистику!'
        )
    
    games_played = stats.get('games_played', 0)
    games_won = stats.get('games_won', 0)
    games_lost = stats.get('games_lost', 0)
    win_rate = (games_won / games_played * 100) if games_played > 0 else 0
    candies = stats.get('candies', 0)
    elo_rating = stats.get('elo_rating', 1000)  # Начальный рейтинг 1000
    elo_change = stats.get('elo_change', 0)  # Изменение рейтинга в последней игре
    avg_opponent_rating = stats.get('avg_opponent_rating', 1000)
    
    # Топ роли
    roles_played = stats.get('roles_played', {})
    wins_by_role = stats.get('wins_by_role', {})
    top_role = max(roles_played.items(), key=lambda x: x[1]) if roles_played else None
    
    # Победы по командам
    wins_by_team = stats.get('wins_by_team', {})
    peaceful_wins = wins_by_team.get('peaceful', 0)
    mafia_wins = wins_by_team.get('mafia', 0)
    maniac_wins = wins_by_team.get('maniac', 0)
    
    # Определяем ранг на основе рейтинга
    if elo_rating >= 2000:
        rank_emoji = "👑"
        rank_name = "Легенда"
    elif elo_rating >= 1800:
        rank_emoji = "💎"
        rank_name = "Мастер"
    elif elo_rating >= 1600:
        rank_emoji = "⭐"
        rank_name = "Эксперт"
    elif elo_rating >= 1400:
        rank_emoji = "🎯"
        rank_name = "Продвинутый"
    elif elo_rating >= 1200:
        rank_emoji = "📈"
        rank_name = "Опытный"
    else:
        rank_emoji = "🌱"
        rank_name = "Новичок"
    
    # Форматируем изменение рейтинга
    elo_change_str = ""
    if elo_change != 0:
        sign = "+" if elo_change > 0 else ""
        elo_change_str = f" ({sign}{elo_change})"
    
    text = (
        f'📊 <b>Статистика игрока {stats.get("name", "Игрок")}</b>\n\n'
        f'{rank_emoji} <b>Рейтинг: {elo_rating}{elo_change_str}</b> ({rank_name})\n'
        f'📊 Средний рейтинг соперников: {int(avg_opponent_rating)}\n\n'
        f'🎮 Игр сыграно: {games_played}\n'
        f'✅ Побед: {games_won}\n'
        f'❌ Поражений: {games_lost}\n'
        f'📈 Винрейт: {win_rate:.1f}%\n'
        f'🍭 Конфет: {candies}\n\n'
    )
    
    # Винрейт по ролям (топ-5)
    if roles_played:
        text += '🎭 <b>Винрейт по ролям:</b>\n'
        role_winrates = []
        for role_code, played_count in roles_played.items():
            wins = wins_by_role.get(role_code, 0)
            winrate = (wins / played_count * 100) if played_count > 0 else 0
            role_winrates.append((role_code, played_count, wins, winrate))
        
        # Сортируем по винрейту (убывание)
        role_winrates.sort(key=lambda x: x[3], reverse=True)
        
        for role_code, played, wins, wr in role_winrates[:5]:  # Топ-5
            role_name = role_titles.get(role_code, role_code)
            # Сокращаем длинные названия
            if len(role_name) > 20:
                role_name = role_name[:17] + "..."
            text += f'  {role_name}: {wr:.1f}% ({wins}/{played})\n'
        text += '\n'
    
    if top_role:
        role_name = role_titles.get(top_role[0], top_role[0])
        text += f'⭐ Любимая роль: {role_name} ({top_role[1]} игр)\n\n'
    
    if peaceful_wins > 0 or mafia_wins > 0 or maniac_wins > 0:
        text += '🏆 <b>Победы по командам:</b>\n'
        if peaceful_wins > 0:
            peaceful_rate = (peaceful_wins / games_won * 100) if games_won > 0 else 0
            text += f'  🎅 Мирные: {peaceful_wins} ({peaceful_rate:.1f}% побед)\n'
        if mafia_wins > 0:
            mafia_rate = (mafia_wins / games_won * 100) if games_won > 0 else 0
            text += f'  😈 Мафия: {mafia_wins} ({mafia_rate:.1f}% побед)\n'
        if maniac_wins > 0:
            maniac_rate = (maniac_wins / games_won * 100) if games_won > 0 else 0
            text += f'  💀 Маньяк: {maniac_wins} ({maniac_rate:.1f}% побед)\n'
        text += '\n'
    
    # Детальная статистика по времени
    if detailed:
        games_by_hour = stats.get('games_by_hour', {})
        wins_by_hour = stats.get('wins_by_hour', {})
        games_by_day = stats.get('games_by_day', {})
        wins_by_day = stats.get('wins_by_day', {})
        
        if games_by_hour:
            text += '⏰ <b>Статистика по времени суток:</b>\n'
            # Находим лучший час
            best_hour = None
            best_wr = 0
            for hour in range(24):
                games = games_by_hour.get(hour, 0)
                wins = wins_by_hour.get(hour, 0)
                if games > 0:
                    wr = (wins / games * 100)
                    if wr > best_wr and games >= 3:  # Минимум 3 игры для статистики
                        best_wr = wr
                        best_hour = hour
            
            if best_hour is not None:
                text += f'  🕐 Лучший час: {best_hour}:00 ({best_wr:.1f}% побед, {games_by_hour[best_hour]} игр)\n'
            
            # Находим самый активный час
            most_active_hour = max(games_by_hour.items(), key=lambda x: x[1])[0] if games_by_hour else None
            if most_active_hour is not None:
                active_games = games_by_hour[most_active_hour]
                active_wins = wins_by_hour.get(most_active_hour, 0)
                active_wr = (active_wins / active_games * 100) if active_games > 0 else 0
                text += f'  📊 Самый активный: {most_active_hour}:00 ({active_games} игр, {active_wr:.1f}% побед)\n'
            text += '\n'
        
        if games_by_day:
            text += '📅 <b>Статистика по дням недели:</b>\n'
            day_names = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
            day_stats = []
            for day in range(7):
                games = games_by_day.get(day, 0)
                wins = wins_by_day.get(day, 0)
                if games > 0:
                    wr = (wins / games * 100)
                    day_stats.append((day, games, wins, wr))
            
            # Сортируем по винрейту
            day_stats.sort(key=lambda x: x[3], reverse=True)
            for day, games, wins, wr in day_stats[:3]:  # Топ-3 дня
                text += f'  {day_names[day]}: {wr:.1f}% ({wins}/{games})\n'
            text += '\n'
        
        # История рейтинга (последние изменения)
        elo_history = stats.get('elo_history', [])
        if len(elo_history) >= 2:
            text += '📈 <b>Динамика рейтинга:</b>\n'
            recent = elo_history[-5:]  # Последние 5 игр
            first_rating = recent[0]['rating']
            last_rating = recent[-1]['rating']
            change = last_rating - first_rating
            change_str = f"+{change}" if change >= 0 else str(change)
            text += f'  За последние {len(recent)} игр: {change_str} ({first_rating} → {last_rating})\n'
            
            # Показываем тренд
            if len(recent) >= 3:
                mid_rating = recent[len(recent)//2]['rating']
                if last_rating > mid_rating > first_rating:
                    text += '  📈 Тренд: Растет\n'
                elif last_rating < mid_rating < first_rating:
                    text += '  📉 Тренд: Падает\n'
                else:
                    text += '  ➡️ Тренд: Стабильный\n'
            text += '\n'
    
    return text

@bot.message_handler(commands=['stats'])
def show_stats(message, *args, **kwargs):
    """Показать статистику игрока"""
    # Проверяем, запрошена ли детальная статистика
    args = message.text.split() if message.text else []
    detailed = 'detailed' in args or 'детально' in args or 'полная' in args
    
    stats_text = get_user_stats(message.from_user.id, message.from_user, detailed=detailed)
    
    # Добавляем кнопку для переключения между обычной и детальной статистикой
    kb = InlineKeyboardMarkup(row_width=1)
    if detailed:
        kb.add(InlineKeyboardButton("📊 Обычная статистика", callback_data='stats_normal'))
    else:
        kb.add(InlineKeyboardButton("📈 Детальная статистика", callback_data='stats_detailed'))
    
    bot.send_message(message.chat.id, stats_text, parse_mode='HTML', reply_markup=kb if not detailed else None)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stats_'))
def stats_toggle_handler(call):
    """Обработчик переключения между обычной и детальной статистикой"""
    user_id = call.from_user.id
    detailed = call.data == 'stats_detailed'
    
    stats_text = get_user_stats(user_id, call.from_user, detailed=detailed)
    
    kb = InlineKeyboardMarkup(row_width=1)
    if detailed:
        kb.add(InlineKeyboardButton("📊 Обычная статистика", callback_data='stats_normal'))
    else:
        kb.add(InlineKeyboardButton("📈 Детальная статистика", callback_data='stats_detailed'))
    
    try:
        bot.edit_message_text(stats_text, call.message.chat.id, call.message.message_id, 
                            parse_mode='HTML', reply_markup=kb)
    except:
        pass
    safe_answer_callback(call.id)

@bot.message_handler(commands=['achievements', 'ach'])
def show_achievements(message, *args, **kwargs):
    """Показать достижения игрока"""
    try:
        from achievements import get_player_achievements, get_achievements_by_rarity, get_achievement_progress, ACHIEVEMENTS
    except ImportError:
        bot.send_message(message.chat.id, "❌ Система достижений временно недоступна.")
        return
    
    user_id = message.from_user.id
    stats = database.find_one('player_stats', {'user_id': user_id})
    
    if not stats:
        bot.send_message(message.chat.id, 
            "📊 <b>Достижения</b>\n\n"
            "У вас пока нет достижений.\n"
            "Сыграйте первую игру, чтобы начать зарабатывать достижения!",
            parse_mode='HTML')
        return
    
    # Получаем достижения игрока
    player_achievements = get_player_achievements(user_id)
    all_achievements = list(ACHIEVEMENTS.values())
    total_count = len(all_achievements)
    unlocked_count = len(player_achievements)
    
    # Группируем по редкости
    rarity_groups = {
        'common': [],
        'uncommon': [],
        'rare': [],
        'epic': [],
        'legendary': []
    }
    
    for ach in all_achievements:
        rarity = ach.get('rarity', 'common')
        if rarity in rarity_groups:
            rarity_groups[rarity].append(ach)
    
    # Формируем текст
    text = f"🏆 <b>ДОСТИЖЕНИЯ</b> 🏆\n\n"
    text += f"📊 Прогресс: {unlocked_count}/{total_count} ({unlocked_count*100//total_count}%)\n\n"
    
    # Показываем по редкости
    rarity_names = {
        'common': '🟢 Обычные',
        'uncommon': '🔵 Необычные',
        'rare': '🟣 Редкие',
        'epic': '🟠 Эпические',
        'legendary': '🟡 Легендарные'
    }
    
    for rarity, name in rarity_names.items():
        achievements = rarity_groups[rarity]
        if not achievements:
            continue
        
        text += f"{name}:\n"
        for ach in achievements[:5]:  # Показываем первые 5 каждого типа
            is_unlocked = ach['id'] in [a['id'] for a in player_achievements]
            icon = "✅" if is_unlocked else "🔒"
            text += f"  {icon} {ach['icon']} {ach['name']}\n"
        
        if len(achievements) > 5:
            unlocked_in_group = sum(1 for a in achievements if a['id'] in [p['id'] for p in player_achievements])
            text += f"  ... и еще {len(achievements) - 5} ({unlocked_in_group}/{len(achievements)} разблокировано)\n"
        text += "\n"
    
    # Показываем последние полученные достижения
    if player_achievements:
        text += f"🎉 <b>Последние достижения:</b>\n"
        for ach in player_achievements[-5:]:  # Последние 5
            text += f"  {ach['icon']} {ach['name']}\n"
    
    # Кнопки для фильтрации
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🟢 Обычные", callback_data='ach_filter common'),
        InlineKeyboardButton("🔵 Необычные", callback_data='ach_filter uncommon')
    )
    kb.add(
        InlineKeyboardButton("🟣 Редкие", callback_data='ach_filter rare'),
        InlineKeyboardButton("🟠 Эпические", callback_data='ach_filter epic')
    )
    kb.add(
        InlineKeyboardButton("🟡 Легендарные", callback_data='ach_filter legendary'),
        InlineKeyboardButton("📊 Все", callback_data='ach_filter all')
    )
    
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=kb)

@bot.message_handler(commands=['leaderboard', 'top', 'lb'])
def show_leaderboard(message, *args, **kwargs):
    """Показать топ игроков по рейтингу"""
    # Проверяем, есть ли аргумент для рейтинга по ролям
    command_args = message.text.split() if message.text else []
    role_filter = None
    if len(command_args) > 1:
        # Пытаемся найти роль в аргументах
        role_arg = command_args[1].lower()
        role_map = {
            'мафия': 'mafia', 'гринч': 'mafia',
            'дон': 'don', 'темный': 'don',
            'комиссар': 'commissar', 'санта': 'commissar',
            'сержант': 'sergeant', 'олень': 'sergeant',
            'доктор': 'doctor', 'лекарь': 'doctor',
            'маньяк': 'maniac', 'крампус': 'maniac',
            'любовница': 'mistress', 'снегурочка': 'mistress',
            'адвокат': 'lawyer',
            'самоубийца': 'suicide', 'снегодуй': 'suicide',
            'бомж': 'bum', 'бродяга': 'bum',
            'счастливчик': 'lucky',
            'камикадзе': 'kamikaze', 'хлопушка': 'kamikaze',
            'мирный': 'peace', 'добряк': 'peace'
        }
        role_filter = role_map.get(role_arg)
    
    # Получаем всех игроков с рейтингом
    all_stats = database.find('player_stats', {})
    
    if not all_stats:
        bot.send_message(message.chat.id, "📊 <b>Рейтинг игроков</b>\n\nПока нет игроков в рейтинге. Сыграйте первую игру!", parse_mode='HTML')
        return
    
    # Фильтруем игроков с рейтингом и сортируем по убыванию
    players_with_rating = []
    for stats in all_stats:
        elo_rating = stats.get('elo_rating', 1000)
        games_played = stats.get('games_played', 0)
        
        # Если указан фильтр по роли, проверяем статистику по ролям
        if role_filter:
            roles_played = stats.get('roles_played', {})
            if role_filter not in roles_played or roles_played[role_filter] == 0:
                continue  # Пропускаем игроков, которые не играли эту роль
        
        if games_played > 0:  # Показываем только тех, кто сыграл хотя бы 1 игру
            # Если фильтр по роли, рассчитываем рейтинг только по этой роли
            if role_filter:
                roles_played = stats.get('roles_played', {})
                wins_by_role = stats.get('wins_by_role', {})
                role_games = roles_played.get(role_filter, 0)
                role_wins = wins_by_role.get(role_filter, 0)
                if role_games > 0:
                    role_win_rate = (role_wins / role_games * 100) if role_games > 0 else 0
                    # Используем общий рейтинг, но показываем статистику по роли
                    players_with_rating.append({
                        'name': stats.get('name', 'Игрок'),
                        'elo_rating': elo_rating,
                        'games_played': role_games,
                        'games_won': role_wins,
                        'win_rate': role_win_rate,
                        'role': role_filter
                    })
            else:
                players_with_rating.append({
                    'name': stats.get('name', 'Игрок'),
                    'elo_rating': elo_rating,
                    'games_played': games_played,
                    'games_won': stats.get('games_won', 0),
                    'win_rate': (stats.get('games_won', 0) / games_played * 100) if games_played > 0 else 0
                })
    
    if not players_with_rating:
        role_name = role_titles.get(role_filter, role_filter) if role_filter else ""
        bot.send_message(message.chat.id, f"📊 <b>Рейтинг игроков{(' по роли ' + role_name) if role_filter else ''}</b>\n\nПока нет игроков в рейтинге. Сыграйте первую игру!", parse_mode='HTML')
        return
    
    # Сортируем по рейтингу (по убыванию)
    players_with_rating.sort(key=lambda x: x['elo_rating'], reverse=True)
    
    # Берем топ 20
    top_players = players_with_rating[:20]
    
    # Формируем текст
    role_name = role_titles.get(role_filter, role_filter) if role_filter else ""
    title = f"🏆 <b>ТОП ИГРОКОВ{' ПО РОЛИ ' + role_name if role_filter else ''}</b> 🏆"
    text = f"{title}\n\n"
    
    # Медали для топ-3
    medals = ["🥇", "🥈", "🥉"]
    
    for i, player in enumerate(top_players):
        rank = i + 1
        medal = medals[i] if i < 3 else f"{rank}."
        
        # Определяем ранг
        elo = player['elo_rating']
        if elo >= 2000:
            rank_emoji = "👑"
        elif elo >= 1800:
            rank_emoji = "💎"
        elif elo >= 1600:
            rank_emoji = "⭐"
        elif elo >= 1400:
            rank_emoji = "🎯"
        elif elo >= 1200:
            rank_emoji = "📈"
        else:
            rank_emoji = "🌱"
        
        text += (
            f"{medal} {rank_emoji} <b>{player['name']}</b>\n"
            f"   Рейтинг: {player['elo_rating']} | "
            f"Игр: {player['games_played']} | "
            f"Винрейт: {player['win_rate']:.1f}%\n\n"
        )
    
    # Добавляем информацию о текущем игроке, если он не в топе
    user_id = message.from_user.id
    user_stats = database.find_one('player_stats', {'user_id': user_id})
    if user_stats:
        user_elo = user_stats.get('elo_rating', 1000)
        user_games = user_stats.get('games_played', 0)
        if user_games > 0:
            # Находим позицию игрока
            user_position = None
            for i, p in enumerate(players_with_rating):
                if p['name'] == user_stats.get('name', 'Игрок'):
                    user_position = i + 1
                    break
            
            if user_position and user_position > 20:
                text += f"\n────────────────\n"
                text += f"📍 <b>Ваша позиция: {user_position}</b>\n"
                text += f"Рейтинг: {user_elo} | Игр: {user_games}"
    
    # Добавляем подсказку о фильтрах
    if not role_filter:
        text += f"\n\n💡 <i>Используйте /leaderboard [роль] для рейтинга по конкретной роли</i>"
        text += f"\n<i>Например: /leaderboard мафия</i>"
    
    bot.send_message(message.chat.id, text, parse_mode='HTML')

@bot.message_handler(commands=['customize', 'custom'])
def customize_command(message, *args, **kwargs):
    """Команда для настройки кастомизации"""
    try:
        from customization import get_customization, set_name_formatting, clear_customization
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    except ImportError:
        bot.send_message(message.chat.id, "❌ Система кастомизации недоступна.")
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id if message.chat.type in ('group', 'supergroup') else None
    
    customization = get_customization(user_id, chat_id)
    
    text = (
        '🎨 <b>Кастомизация роли</b>\n\n'
        f'Префикс: {customization.get("role_prefix", "") or "нет"}\n'
        f'Суффикс: {customization.get("role_suffix", "") or "нет"}\n'
        f'Форматирование: {customization.get("name_formatting", "normal")}\n\n'
        '💡 Префиксы и суффиксы выдаются за достижения!\n'
        '💡 Используйте кнопки ниже для настройки форматирования.'
    )
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Обычный", callback_data='custom_format normal'),
        InlineKeyboardButton("📝 Жирный", callback_data='custom_format bold')
    )
    kb.add(
        InlineKeyboardButton("📝 Курсив", callback_data='custom_format italic'),
        InlineKeyboardButton("🗑️ Очистить", callback_data='custom_clear')
    )
    
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('custom_'))
def customize_callback(call):
    """Обработчик кастомизации"""
    try:
        from customization import get_customization, set_name_formatting, clear_customization
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    except ImportError:
        safe_answer_callback(call.id, "Система кастомизации недоступна", show_alert=True)
        return
    
    user_id = call.from_user.id
    chat_id = call.message.chat.id if call.message.chat.type in ('group', 'supergroup') else None
    
    if call.data.startswith('custom_format '):
        formatting = call.data.split()[1]
        set_name_formatting(user_id, formatting, chat_id)
        safe_answer_callback(call.id, f"✅ Форматирование установлено: {formatting}")
        
        # Обновляем сообщение
        customization = get_customization(user_id, chat_id)
        text = (
            '🎨 <b>Кастомизация роли</b>\n\n'
            f'Префикс: {customization.get("role_prefix", "") or "нет"}\n'
            f'Суффикс: {customization.get("role_suffix", "") or "нет"}\n'
            f'Форматирование: {customization.get("name_formatting", "normal")}\n\n'
            '💡 Префиксы и суффиксы выдаются за достижения!\n'
            '💡 Используйте кнопки ниже для настройки форматирования.'
        )
        
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📝 Обычный", callback_data='custom_format normal'),
            InlineKeyboardButton("📝 Жирный", callback_data='custom_format bold')
        )
        kb.add(
            InlineKeyboardButton("📝 Курсив", callback_data='custom_format italic'),
            InlineKeyboardButton("🗑️ Очистить", callback_data='custom_clear')
        )
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            pass
    
    elif call.data == 'custom_clear':
        clear_customization(user_id, chat_id)
        safe_answer_callback(call.id, "✅ Кастомизация очищена")
        
        # Обновляем сообщение
        customization = get_customization(user_id, chat_id)
        text = (
            '🎨 <b>Кастомизация роли</b>\n\n'
            f'Префикс: {customization.get("role_prefix", "") or "нет"}\n'
            f'Суффикс: {customization.get("role_suffix", "") or "нет"}\n'
            f'Форматирование: {customization.get("name_formatting", "normal")}\n\n'
            '💡 Префиксы и суффиксы выдаются за достижения!\n'
            '💡 Используйте кнопки ниже для настройки форматирования.'
        )
        
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📝 Обычный", callback_data='custom_format normal'),
            InlineKeyboardButton("📝 Жирный", callback_data='custom_format bold')
        )
        kb.add(
            InlineKeyboardButton("📝 Курсив", callback_data='custom_format italic'),
            InlineKeyboardButton("🗑️ Очистить", callback_data='custom_clear')
        )
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('daily_claim_'))
def claim_daily_drop_callback(call):
    """Обработчик получения ежедневного дропа через inline кнопку"""
    from datetime import datetime
    
    user_id = call.from_user.id
    chat_id = int(call.data.split('_')[-1])
    today = datetime.now().date().isoformat()
    
    # Ищем активный дроп в этой группе
    drop = database.find_one('daily_drops', {
        'chat_id': chat_id,
        'date': today,
        'claimed': False
    })
    
    if not drop:
        safe_answer_callback(call.id, "❌ Нет доступных конфет для получения. Попробуйте завтра!", show_alert=True)
        return
    
    # Проверяем, не забрал ли уже этот пользователь
    if drop.get('claimed_by') == user_id:
        safe_answer_callback(call.id, "❌ Вы уже забрали сегодняшние конфеты!", show_alert=True)
        return
    
    # Выдаем конфеты
    stats = database.find_one('player_stats', {'user_id': user_id})
    if not stats:
        stats = {
            'user_id': user_id,
            'name': call.from_user.first_name,
            'candies': 0
        }
        database.insert_one('player_stats', stats)
    
    candies_amount = drop.get('candies', 0)
    new_candies = stats.get('candies', 0) + candies_amount
    
    database.update_one('player_stats', {'user_id': user_id}, {'$set': {'candies': new_candies}})
    
    # Помечаем дроп как забранный
    database.update_one('daily_drops', {'_id': drop['_id']}, {
        '$set': {
            'claimed': True,
            'claimed_by': user_id,
            'claimed_at': datetime.now().isoformat()
        }
    })
    
    # Обновляем сообщение, убирая кнопку
    try:
        bot.edit_message_text(
            f"🎁 <b>Ежедневный подарок!</b>\n\n"
            f"🎉 <b>{call.from_user.first_name}</b> забрал {candies_amount} 🍭 конфет!\n\n"
            f"Теперь у него: {new_candies} 🍭",
            chat_id,
            call.message.message_id,
            parse_mode='HTML'
        )
    except:
        pass
    
    safe_answer_callback(call.id, f"✅ Вы получили {candies_amount} 🍭 конфет!")
    
    # Отправляем уведомление в группу
    try:
        bot.send_message(
            chat_id,
            f"🎉 <b>{call.from_user.first_name}</b> забрал ежедневный подарок: {candies_amount} 🍭 конфет!",
            parse_mode='HTML'
        )
    except:
        pass

@bot.message_handler(commands=['mafia'])
def mafia_chat_command(message, *args, **kwargs):
    """Общение мафии во время первой ночи"""
    user_id = message.from_user.id
    
    # Ищем активную игру, где игрок является мафией
    all_games = database.find('games', {'game': 'mafia'})
    game = None
    player = None
    
    for g in all_games:
        p = next((p for p in g.get('players', []) if p.get('id') == user_id), None)
        if p and p.get('role') in ('mafia', 'don'):
            # Проверяем, что это первая ночь (мафия еще не познакомилась или night_count == 0)
            if not g.get('mafia_met') or g.get('night_count', 0) == 0:
                game = g
                player = p
                break
    
    if not game or not player:
        bot.send_message(message.chat.id, "❌ Вы не можете использовать эту команду сейчас.")
        return
    
    # Получаем текст сообщения
    if not message.text or len(message.text.split()) < 2:
        bot.send_message(message.chat.id, "💬 <b>Общение мафии</b>\n\nИспользование: <code>/mafia &lt;сообщение&gt;</code>\n\nПример: <code>/mafia Привет, команда!</code>", parse_mode='HTML')
        return
    
    # Извлекаем сообщение (убираем команду)
    chat_message = ' '.join(message.text.split()[1:])
    if not chat_message:
        bot.send_message(message.chat.id, "❌ Сообщение не может быть пустым.")
        return
    
    # Получаем список мафии
    mafiosi = [p for p in game['players'] if p.get('role') in ('mafia', 'don')]
    
    # Отправляем сообщение всем мафии
    player_name = player.get('name', 'Игрок')
    player_pos = player.get('position', game['players'].index(player) + 1)
    
    # Проверяем, есть ли другие мафиози кроме отправителя
    other_mafiosi = [m for m in mafiosi if m['id'] != user_id]
    
    if not other_mafiosi:
        safe_send_message(message.chat.id, "💬 Вы единственный член мафии в этой игре. Некому отправлять сообщения.")
        return
    
    sent_count = 0
    failed_count = 0
    
    for mafioso in other_mafiosi:
        result = safe_send_message(
            mafioso['id'],
            f'💬 <b>Мафия чат</b>\n\n'
            f'<b>№{player_pos} {player_name}:</b>\n'
            f'{chat_message}',
            parse_mode='HTML'
        )
        if result:
            sent_count += 1
        else:
            failed_count += 1
    
    # Подтверждение отправителю
    if sent_count > 0:
        if failed_count > 0:
            safe_send_message(message.chat.id, f"✅ Сообщение отправлено {sent_count} из {len(other_mafiosi)} членам мафии. {failed_count} не получили сообщение (возможно, заблокировали бота).")
        else:
            safe_send_message(message.chat.id, f"✅ Сообщение отправлено {sent_count} членам мафии.")
    else:
        safe_send_message(message.chat.id, "❌ Не удалось отправить сообщение. Возможно, все члены мафии заблокировали бота.")

@bot.message_handler(commands=['events', 'event'])
def show_events_shop(message, *args, **kwargs):
    """Показать магазин событий"""
    from game_events import get_available_events
    
    user_id = message.from_user.id
    stats = database.find_one('player_stats', {'user_id': user_id})
    candies = stats.get('candies', 0) if stats else 0
    
    # Проверяем, есть ли активная игра
    game = None
    if message.chat.type in ('group', 'supergroup'):
        game = database.find_one('games', {'chat': message.chat.id, 'game': 'mafia'})
    else:
        # Ищем игру по игроку
        all_games = database.find('games', {'game': 'mafia'})
        for g in all_games:
            if any(p.get('id') == user_id for p in g.get('players', [])):
                game = g
                break
    
    if not game:
        bot.send_message(message.chat.id, 
            f'🍭 <b>Магазин событий</b>\n\n'
            f'У тебя: {candies} 🍭\n\n'
            '❌ События можно активировать только во время активной игры!\n\n'
            '💡 Присоединись к игре и используй /events для покупки событий.',
            parse_mode='HTML')
        return
    
    # Проверяем, что игрок в игре
    player = next((p for p in game.get('players', []) if p.get('id') == user_id), None)
    if not player:
        bot.send_message(message.chat.id, '❌ Ты не участвуешь в текущей игре.')
        return
    
    # Показываем доступные события
    from game_events import get_current_season
    events = get_available_events()
    current_season = get_current_season()
    season_names = {'winter': '❄️ Зима', 'spring': '🌸 Весна', 'summer': '☀️ Лето', 'autumn': '🍂 Осень'}
    
    text = f'🍭 <b>Магазин событий</b>\n\n'
    text += f'У тебя: {candies} 🍭\n'
    text += f'Сезон: {season_names.get(current_season, current_season)}\n\n'
    
    # Группируем по редкости
    common_events = [e for e in events if e.get('rarity') == 'common']
    rare_events = [e for e in events if e.get('rarity') == 'rare']
    legendary_events = [e for e in events if e.get('rarity') == 'legendary']
    
    rarity_icons = {'common': '🟢', 'rare': '🟣', 'legendary': '🟡'}
    rarity_names = {'common': 'Обычные', 'rare': 'Редкие', 'legendary': 'Легендарные'}
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    # Легендарные события
    if legendary_events:
        text += f'<b>{rarity_icons["legendary"]} {rarity_names["legendary"]}:</b>\n'
        for event in legendary_events:
            can_afford = candies >= event['cost']
            status = '✅' if can_afford else '❌'
            text += f'{status} {event["description"]}\n'
            text += f'   💰 {event["cost"]} 🍭\n\n'
            if can_afford:
                kb.add(InlineKeyboardButton(
                    f'🟡 Купить {event["name"]} ({event["cost"]} 🍭)',
                    callback_data=f'buy_event_{event["name"]}'
                ))
    
    # Редкие события
    if rare_events:
        text += f'<b>{rarity_icons["rare"]} {rarity_names["rare"]}:</b>\n'
        for event in rare_events[:5]:  # Показываем первые 5
            can_afford = candies >= event['cost']
            status = '✅' if can_afford else '❌'
            text += f'{status} {event["description"]}\n'
            text += f'   💰 {event["cost"]} 🍭\n\n'
            if can_afford:
                kb.add(InlineKeyboardButton(
                    f'🟣 Купить {event["name"]} ({event["cost"]} 🍭)',
                    callback_data=f'buy_event_{event["name"]}'
                ))
        if len(rare_events) > 5:
            text += f'... и еще {len(rare_events) - 5} редких событий\n\n'
    
    # Обычные события
    if common_events:
        text += f'<b>{rarity_icons["common"]} {rarity_names["common"]}:</b>\n'
        for event in common_events[:5]:  # Показываем первые 5
            can_afford = candies >= event['cost']
            status = '✅' if can_afford else '❌'
            text += f'{status} {event["description"]}\n'
            text += f'   💰 {event["cost"]} 🍭\n\n'
            if can_afford:
                kb.add(InlineKeyboardButton(
                    f'🟢 Купить {event["name"]} ({event["cost"]} 🍭)',
                    callback_data=f'buy_event_{event["name"]}'
                ))
        if len(common_events) > 5:
            text += f'... и еще {len(common_events) - 5} обычных событий\n\n'
    
    if candies == 0:
        text += '\n💡 Выиграй игру, чтобы получить 10 🍭!'
    
    # Добавляем кнопки фильтрации
    filter_kb = InlineKeyboardMarkup(row_width=3)
    filter_kb.add(
        InlineKeyboardButton("🟢 Обычные", callback_data='events_filter common'),
        InlineKeyboardButton("🟣 Редкие", callback_data='events_filter rare'),
        InlineKeyboardButton("🟡 Легендарные", callback_data='events_filter legendary')
    )
    filter_kb.add(InlineKeyboardButton("📊 Все", callback_data='events_filter all'))
    
    # Объединяем клавиатуры
    if kb.keyboard:
        for row in filter_kb.keyboard:
            kb.keyboard.append(row)
    
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=kb if kb.keyboard else filter_kb)

@bot.message_handler(commands=['shop', 'магазин'])
def show_shop(message, *args, **kwargs):
    """Показать магазин или купить товар"""
    try:
        from shop import get_shop_items, get_active_limited_offers, get_user_inventory, find_item_by_name, purchase_item
    except ImportError as e:
        logging.error(f"Error importing shop module: {e}", exc_info=True)
        bot.send_message(message.chat.id, f"❌ Магазин временно недоступен.\nОшибка импорта: {str(e)}")
        return
    except Exception as e:
        logging.error(f"Error in shop command (import): {e}", exc_info=True)
        bot.send_message(message.chat.id, f"❌ Ошибка при загрузке магазина: {str(e)}")
        return
    
    try:
        user_id = message.from_user.id
        stats = database.find_one('player_stats', {'user_id': user_id})
        candies = stats.get('candies', 0) if stats else 0
        
        # Проверяем, есть ли аргумент (название товара для покупки)
        command_text = message.text or ''
        parts = command_text.split(maxsplit=1)
        if len(parts) > 1:
            item_name = parts[1].strip()
            item = find_item_by_name(item_name)
            
            if not item:
                bot.send_message(
                    message.chat.id,
                    f"❌ Товар '{item_name}' не найден.\n\n"
                    "💡 Используйте /shop для просмотра всех товаров.",
                    parse_mode='HTML'
                )
                return
            
            # Покупаем товар
            payment_type = 'candies' if item.get('cost_candies') else 'stars'
            
            # Если покупка за звезды - отправляем invoice
            if payment_type == 'stars' and item.get('cost_stars'):
                send_stars_invoice(message.chat.id, user_id, item)
                return
            
            # Если покупка за конфеты - обычная логика
            success, msg, item_data = purchase_item(user_id, item['id'], payment_type)
            
            if success:
                bot.send_message(message.chat.id, f"✅ {msg}", parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, f"❌ {msg}", parse_mode='HTML')
            return
        
        # Показываем магазин
        badges = get_shop_items('badge')
        titles = get_shop_items('title')
        cases = get_shop_items('case')
        candies_packs = get_shop_items('candies')
        limited_offers = get_active_limited_offers()
        
        # Красивый дизайн магазина
        text = "━━━━━━━━━━━━━━━━━━━━\n"
        text += "🎄 <b>МАГАЗИН СЕВЕРНОГО ПОЛЮСА</b> 🎄\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        text += f"💰 <b>Ваш баланс:</b> <code>{candies:,}</code> 🍭\n\n"
        
        # Ограниченные предложения
        if limited_offers:
            text += "🔥 <b>🔥 ОГРАНИЧЕННЫЕ ПРЕДЛОЖЕНИЯ 🔥</b>\n"
            for offer in limited_offers:
                text += f"   • {offer.get('name', 'Предложение')}\n"
            text += "\n"
        
        # Бейджи
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "🎖️ <b>БЕЙДЖИ</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        for badge in badges:
            rarity_emoji = {'common': '🟢', 'rare': '🟣', 'legendary': '🟡'}.get(badge.get('rarity', 'common'), '⚪')
            text += f"\n{rarity_emoji} {badge['icon']} <b>{badge['name']}</b>\n"
            text += f"   {badge.get('description', '')}\n"
            text += f"   💰 <code>{badge.get('cost_candies', 0)}</code> 🍭\n"
            text += f"   📝 <code>/shop {badge['name']}</code>\n"
        
        # Титулы
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "🎩 <b>ТИТУЛЫ</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        for title in titles:
            rarity_emoji = {'common': '🟢', 'uncommon': '🔵', 'rare': '🟣', 'legendary': '🟡'}.get(title.get('rarity', 'common'), '⚪')
            text += f"\n{rarity_emoji} {title['icon']} <b>{title['name']}</b>\n"
            text += f"   {title.get('description', '')}\n"
            text += f"   💰 <code>{title.get('cost_candies', 0)}</code> 🍭\n"
            text += f"   📝 <code>/shop {title['name']}</code>\n"
        
        # Кейсы
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "📦 <b>КЕЙСЫ</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        for case in cases:
            rarity_emoji = {'common': '🟢', 'rare': '🟣', 'legendary': '🟡'}.get(case.get('rarity', 'common'), '⚪')
            text += f"\n{rarity_emoji} {case['icon']} <b>{case['name']}</b>\n"
            text += f"   {case.get('description', '')}\n"
            text += f"   💰 <code>{case.get('cost_candies', 0)}</code> 🍭\n"
            text += f"   📝 <code>/shop {case['name']}</code>\n"
        
        # Покупка конфет за Звезды
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "⭐ <b>КОНФЕТЫ ЗА ЗВЕЗДЫ</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        for pack in candies_packs:
            rarity_emoji = {'common': '🟢', 'uncommon': '🔵', 'rare': '🟣'}.get(pack.get('rarity', 'common'), '⚪')
            text += f"\n{rarity_emoji} {pack['icon']} <b>{pack['name']}</b>\n"
            text += f"   {pack.get('description', '')}\n"
            text += f"   💰 <code>{pack.get('cost_stars', 0)}</code> ⭐\n"
            text += f"   📝 <code>/shop {pack['name']}</code>\n"
        
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "💡 <i>Для покупки используйте:</i>\n"
        text += "<code>/shop [название товара]</code>\n"
        text += "━━━━━━━━━━━━━━━━━━━━"
        
        # Кнопки фильтрации и инвентаря
        filter_kb = InlineKeyboardMarkup(row_width=3)
        filter_kb.add(
            InlineKeyboardButton("🎖️ Бейджи", callback_data='shop_filter badge'),
            InlineKeyboardButton("🎩 Титулы", callback_data='shop_filter title'),
            InlineKeyboardButton("📦 Кейсы", callback_data='shop_filter case')
        )
        filter_kb.add(
            InlineKeyboardButton("🍭 Конфеты", callback_data='shop_filter candies'),
            InlineKeyboardButton("📦 Инвентарь", callback_data='shop_inventory'),
            InlineKeyboardButton("📊 Все", callback_data='shop_filter all')
        )
        
        # Добавляем быстрые кнопки для покупки конфет за звезды в основную клавиатуру
        if candies_packs:
            for pack in candies_packs[:3]:  # Показываем первые 3 пакета
                filter_kb.add(
                    InlineKeyboardButton(
                        f"⭐ {pack['name']} ({pack.get('cost_stars', 0)}⭐)",
                        callback_data=f'buy_stars_{pack["id"]}'
                    )
                )
        
        bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=filter_kb)
    except Exception as e:
        logging.error(f"Error in shop command (execution): {e}", exc_info=True)
        bot.send_message(message.chat.id, f"❌ Ошибка при выполнении команды магазина: {str(e)}")

@bot.message_handler(commands=['rules'])
def show_rules(message, *args, **kwargs):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
    rules = (
        '🎄 <b>КОДЕКС СЕВЕРНОГО ПОЛЮСА</b> 📜\n\n'
        '🎅 <b>Мирные:</b> Добряк, Счастливчик, Хлопушка (Камикадзе)\n'
        '🎅 <b>Порядок:</b> Санта-Комиссар, Младший Олень (Сержант)\n'
        '🧦 <b>Защита:</b> Эльф-лекарь (Доктор)\n'
        '😈 <b>Злодеи:</b> Гринч (Мафия), Тёмный Эльф (Дон)\n'
        '🍷 <b>Нейтралы:</b> Снегурочка (Любовница), Крампус-Маньяк, Адвокат Рождества, Снегодуй (Самоубийца), Бродяга (Бомж)\n\n'
        '🏆 <b>ПОБЕДА:</b>\n'
        '✅ Мирные — изгнать всех злодеев\n'
        '✅ Мафия — уравнять количество с мирными\n'
        '✅ Маньяк — остаться одному\n\n'
        '💡 <b>Особенности:</b>\n'
        '• Свободное обсуждение (5 минут)\n'
        '• Любой может выставить кандидата на голосование\n'
        '• Первая ночь: знакомство мафии (1 минута)\n'
        '• Ночные действия: проверки, убийства, лечение\n'
        '• События: метель, костёр, фейерверк и др.'
    )
    bot.send_message(message.chat.id, rules, parse_mode='HTML', reply_markup=kb)

@bot.message_handler(commands=['team', 'команда'])
def team_command(message, *args, **kwargs):
    """Обработка команд для работы с командами"""
    try:
        from teams import (
            create_team, get_user_team, invite_player, get_team_stats,
            get_user_invitations, accept_invitation, reject_invitation,
            leave_team, kick_member
        )
    except ImportError:
        bot.send_message(message.chat.id, "❌ Система команд временно недоступна.")
        return
    
    args_list = message.text.split() if message.text else []
    if len(args_list) < 2:
        # Показываем справку с inline кнопками
        user_id = message.from_user.id
        team = get_user_team(user_id)
        
        text = "👥 <b>Команды для работы с командами:</b>\n\n"
        
        if team:
            text += f"✅ Вы состоите в команде: <b>{team.get('name', 'Без названия')}</b>\n\n"
        else:
            text += "❌ Вы не состоите в команде\n\n"
        
        text += (
            "📝 <code>/team create &lt;название&gt;</code> - создать команду\n"
            "➕ <code>/team invite @username</code> - пригласить игрока\n"
            "✅ <code>/team accept &lt;ID&gt;</code> - принять приглашение\n"
            "❌ <code>/team reject &lt;ID&gt;</code> - отклонить приглашение\n"
        )
        
        # Создаем inline кнопки
        kb = InlineKeyboardMarkup(row_width=2)
        if team:
            kb.add(
                InlineKeyboardButton("ℹ️ Информация", callback_data='team_info'),
                InlineKeyboardButton("📊 Статистика", callback_data='team_stats')
            )
            kb.add(
                InlineKeyboardButton("📨 Приглашения", callback_data='team_invitations'),
                InlineKeyboardButton("🚪 Покинуть", callback_data='team_leave')
            )
        else:
            kb.add(
                InlineKeyboardButton("📨 Мои приглашения", callback_data='team_invitations')
            )
        
        bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        return
    
    subcommand = args_list[1].lower()
    user_id = message.from_user.id
    
    if subcommand == 'create':
        if len(args_list) < 3:
            bot.send_message(message.chat.id, "❌ Укажите название команды: /team create <название>")
            return
        
        team_name = ' '.join(args_list[2:])
        if len(team_name) > 50:
            bot.send_message(message.chat.id, "❌ Название команды не должно превышать 50 символов")
            return
        
        team = create_team(user_id, team_name)
        if team:
            text = (
                f"✅ <b>Команда создана!</b>\n\n"
                f"📛 Название: {team['name']}\n"
                f"🆔 ID: <code>{team['team_id']}</code>\n\n"
                f"💡 Поделитесь ID команды с друзьями, чтобы они могли присоединиться!"
            )
            bot.send_message(message.chat.id, text, parse_mode='HTML')
        else:
            existing_team = get_user_team(user_id)
            if existing_team:
                bot.send_message(message.chat.id, f"❌ Вы уже состоите в команде: {existing_team['name']}")
            else:
                bot.send_message(message.chat.id, "❌ Ошибка создания команды. Сыграйте хотя бы одну игру.")
    
    elif subcommand == 'invite':
        if len(args_list) < 3:
            bot.send_message(message.chat.id, "❌ Укажите пользователя: /team invite @username")
            return
        
        team = get_user_team(user_id)
        if not team:
            bot.send_message(message.chat.id, "❌ Вы не состоите в команде. Создайте её: /team create <название>")
            return
        
        # Пытаемся найти пользователя
        username = args_list[2].replace('@', '')
        invitee_id = None
        
        # Если это ответ на сообщение, берем user_id из reply
        if message.reply_to_message:
            invitee_id = message.reply_to_message.from_user.id
        else:
            # Ищем в базе по username или имени
            all_stats = database.find('player_stats', {})
            for stats in all_stats:
                # Проверяем имя (может содержать username)
                name = stats.get('name', '')
                if username.lower() in name.lower() or name.lower().startswith('@' + username.lower()):
                    invitee_id = stats['user_id']
                    break
        
        if not invitee_id:
            bot.send_message(message.chat.id, 
                f"❌ Пользователь @{username} не найден.\n\n"
                f"💡 <b>Способы приглашения:</b>\n"
                f"1. Ответьте на сообщение пользователя командой /team invite\n"
                f"2. Укажите точный username: /team invite @username",
                parse_mode='HTML')
            return
        
        success, msg = invite_player(team['team_id'], user_id, invitee_id)
        if success:
            bot.send_message(message.chat.id, f"✅ {msg}")
            # Отправляем уведомление приглашенному
            try:
                from teams import get_team
                team_info = get_team(team['team_id'])
                inv_text = (
                    f"📨 <b>Приглашение в команду!</b>\n\n"
                    f"👥 Команда: {team_info['name']}\n"
                    f"🆔 ID: <code>{team_info['team_id']}</code>\n\n"
                    f"✅ Принять: /team accept {team_info['team_id']}\n"
                    f"❌ Отклонить: /team reject {team_info['team_id']}"
                )
                bot.send_message(invitee_id, inv_text, parse_mode='HTML')
            except:
                pass
        else:
            bot.send_message(message.chat.id, f"❌ {msg}")
    
    elif subcommand == 'info':
        team = get_user_team(user_id)
        if not team:
            bot.send_message(message.chat.id, "❌ Вы не состоите в команде")
            return
        
        text = (
            f"👥 <b>Команда: {team['name']}</b>\n\n"
            f"🆔 ID: <code>{team['team_id']}</code>\n"
            f"👤 Создатель: {team['creator_name']}\n"
            f"👥 Участников: {len(team['members'])}\n"
            f"📨 Приглашений: {len(team.get('invitations', []))}\n\n"
            f"<b>Участники:</b>\n"
        )
        
        for member in team['members']:
            role_icon = "👑" if member.get('role') == 'leader' else "👤"
            text += f"{role_icon} {member['name']}\n"
        
        if team.get('invitations'):
            text += "\n<b>Приглашенные:</b>\n"
            for inv in team['invitations']:
                text += f"📨 {inv['name']}\n"
        
        bot.send_message(message.chat.id, text, parse_mode='HTML')
    
    elif subcommand == 'stats':
        team = get_user_team(user_id)
        if not team:
            bot.send_message(message.chat.id, "❌ Вы не состоите в команде")
            return
        
        stats = get_team_stats(team['team_id'])
        text = (
            f"📊 <b>Статистика команды {team['name']}</b>\n\n"
            f"🎮 Игр сыграно: {stats['total_games']}\n"
            f"✅ Побед: {stats['total_wins']}\n"
            f"❌ Поражений: {stats['total_losses']}\n"
            f"📈 Винрейт: {stats['win_rate']:.1f}%\n"
            f"⭐ Средний ELO: {int(stats['avg_elo'])}\n"
            f"🍭 Всего конфет: {stats['total_candies']}\n"
            f"👥 Участников: {stats['members_count']}"
        )
        bot.send_message(message.chat.id, text, parse_mode='HTML')
    
    elif subcommand == 'invitations':
        invitations = get_user_invitations(user_id)
        if not invitations:
            bot.send_message(message.chat.id, "📭 У вас нет приглашений")
            return
        
        text = "📨 <b>Ваши приглашения:</b>\n\n"
        for inv in invitations:
            text += (
                f"👥 {inv['team_name']}\n"
                f"🆔 ID: <code>{inv['team_id']}</code>\n"
                f"👤 Пригласил: {inv.get('inviter_name', 'Игрок')}\n"
                f"✅ /team accept {inv['team_id']}\n"
                f"❌ /team reject {inv['team_id']}\n\n"
            )
        bot.send_message(message.chat.id, text, parse_mode='HTML')
    
    elif subcommand == 'accept':
        if len(args_list) < 3:
            bot.send_message(message.chat.id, "❌ Укажите ID команды: /team accept <ID>")
            return
        
        team_id = args_list[2].upper()
        success, msg = accept_invitation(team_id, user_id)
        if success:
            bot.send_message(message.chat.id, f"✅ {msg}")
        else:
            bot.send_message(message.chat.id, f"❌ {msg}")
    
    elif subcommand == 'reject':
        if len(args_list) < 3:
            bot.send_message(message.chat.id, "❌ Укажите ID команды: /team reject <ID>")
            return
        
        team_id = args_list[2].upper()
        success, msg = reject_invitation(team_id, user_id)
        if success:
            bot.send_message(message.chat.id, f"✅ {msg}")
        else:
            bot.send_message(message.chat.id, f"❌ {msg}")
    
    elif subcommand == 'leave':
        success, msg = leave_team(user_id)
        if success:
            bot.send_message(message.chat.id, f"✅ {msg}")
        else:
            bot.send_message(message.chat.id, f"❌ {msg}")
    
    else:
        bot.send_message(message.chat.id, "❌ Неизвестная команда. Используйте /team для справки")

@bot.message_handler(commands=['report'])
def report_command(message, *args, **kwargs):
    """Пожаловаться на игрока"""
    try:
        from moderation import report_player, is_banned
    except ImportError:
        bot.send_message(message.chat.id, "❌ Система жалоб временно недоступна.")
        return
    
    args_list = message.text.split() if message.text else []
    if len(args_list) < 3:
        bot.send_message(message.chat.id, 
            "📝 <b>Как пожаловаться:</b>\n\n"
            "📋 <code>/report @username &lt;причина&gt;</code>\n"
            "📋 <code>/report &lt;ID&gt; &lt;причина&gt;</code>\n\n"
            "💡 <b>Примеры:</b>\n"
            "/report @user читерство\n"
            "/report @user токсичное поведение\n\n"
            "⚠️ При 3+ жалобах игрок автоматически банится на 24 часа",
            parse_mode='HTML')
        return
    
    reporter_id = message.from_user.id
    
    # Проверяем, не забанен ли сам жалобщик
    if is_banned(reporter_id):
        bot.send_message(message.chat.id, "❌ Вы забанены и не можете подавать жалобы")
        return
    
    # Пытаемся найти пользователя
    target = args_list[1].replace('@', '')
    reported_id = None
    
    # Если это ответ на сообщение
    if message.reply_to_message:
        reported_id = message.reply_to_message.from_user.id
    else:
        # Ищем в базе
        all_stats = database.find('player_stats', {})
        for stats in all_stats:
            name = stats.get('name', '')
            if target.lower() in name.lower() or name.lower().startswith('@' + target.lower()):
                reported_id = stats['user_id']
                break
    
    if not reported_id:
        bot.send_message(message.chat.id, 
            f"❌ Пользователь @{target} не найден.\n\n"
            f"💡 Ответьте на сообщение пользователя командой /report",
            parse_mode='HTML')
        return
    
    reason = ' '.join(args_list[2:])
    if len(reason) > 500:
        bot.send_message(message.chat.id, "❌ Причина не должна превышать 500 символов")
        return
    
    success, msg = report_player(reporter_id, reported_id, reason)
    bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {msg}")

@bot.message_handler(commands=['ban'])
def ban_command(message, *args, **kwargs):
    """Забанить игрока (только для модераторов)"""
    try:
        from moderation import ban_player, is_moderator, is_banned
        from datetime import datetime, timedelta
    except ImportError:
        bot.send_message(message.chat.id, "❌ Система модерации временно недоступна.")
        return
    
    if not is_moderator(message.from_user.id):
        bot.send_message(message.chat.id, "❌ Только модераторы могут использовать эту команду")
        return
    
    args_list = message.text.split() if message.text else []
    if len(args_list) < 3:
        bot.send_message(message.chat.id,
            "🔨 <b>Забанить игрока:</b>\n\n"
            "📋 <code>/ban @username &lt;причина&gt; [время]</code>\n\n"
            "💡 <b>Примеры:</b>\n"
            "/ban @user читерство\n"
            "/ban @user токсичность 24h\n"
            "/ban @user нарушение 7d\n\n"
            "⏰ Время: 1h, 24h, 7d, 30d (по умолчанию - постоянный бан)",
            parse_mode='HTML')
        return
    
    target = args_list[1].replace('@', '')
    reported_id = None
    
    # Ищем пользователя
    if message.reply_to_message:
        reported_id = message.reply_to_message.from_user.id
    else:
        all_stats = database.find('player_stats', {})
        for stats in all_stats:
            name = stats.get('name', '')
            if target.lower() in name.lower():
                reported_id = stats['user_id']
                break
    
    if not reported_id:
        bot.send_message(message.chat.id, f"❌ Пользователь @{target} не найден")
        return
    
    if is_banned(reported_id):
        bot.send_message(message.chat.id, "❌ Игрок уже забанен")
        return
    
    reason = ' '.join(args_list[2:-1]) if len(args_list) > 3 else ' '.join(args_list[2:])
    ban_until = None
    
    # Парсим время бана (если указано)
    if len(args_list) > 3:
        time_str = args_list[-1].lower()
        try:
            if time_str.endswith('h'):
                hours = int(time_str[:-1])
                ban_until = datetime.now() + timedelta(hours=hours)
            elif time_str.endswith('d'):
                days = int(time_str[:-1])
                ban_until = datetime.now() + timedelta(days=days)
            elif time_str.endswith('m'):
                minutes = int(time_str[:-1])
                ban_until = datetime.now() + timedelta(minutes=minutes)
        except:
            pass
    
    success, msg = ban_player(reported_id, message.from_user.id, reason, ban_until)
    bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {msg}")

@bot.message_handler(commands=['unban'])
def unban_command(message, *args, **kwargs):
    """Разбанить игрока (только для модераторов)"""
    try:
        from moderation import unban_player, is_moderator, is_banned
    except ImportError:
        bot.send_message(message.chat.id, "❌ Система модерации временно недоступна.")
        return
    
    if not is_moderator(message.from_user.id):
        bot.send_message(message.chat.id, "❌ Только модераторы могут использовать эту команду")
        return
    
    args_list = message.text.split() if message.text else []
    if len(args_list) < 2:
        bot.send_message(message.chat.id, "❌ Укажите пользователя: /unban @username")
        return
    
    target = args_list[1].replace('@', '')
    reported_id = None
    
    # Ищем пользователя
    all_stats = database.find('player_stats', {})
    for stats in all_stats:
        name = stats.get('name', '')
        if target.lower() in name.lower():
            reported_id = stats['user_id']
            break
    
    if not reported_id:
        bot.send_message(message.chat.id, f"❌ Пользователь @{target} не найден")
        return
    
    if not is_banned(reported_id):
        bot.send_message(message.chat.id, "❌ Игрок не забанен")
        return
    
    success, msg = unban_player(reported_id, message.from_user.id)
    bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {msg}")

@bot.message_handler(commands=['mod'])
def mod_command(message, *args, **kwargs):
    """Управление модераторами (только для админа)"""
    try:
        from moderation import add_moderator, remove_moderator, get_moderators, is_moderator, ADMIN_ID
        from moderation import get_reports, get_bans, resolve_report
    except ImportError:
        bot.send_message(message.chat.id, "❌ Система модерации временно недоступна.")
        return
    
    user_id = message.from_user.id
    
    # Проверяем, что это админ
    if user_id != ADMIN_ID:
        bot.send_message(message.chat.id, "❌ Только администратор может управлять модераторами")
        return
    
    args_list = message.text.split() if message.text else []
    if len(args_list) < 2:
        text = "👮 <b>Управление модерацией:</b>\n\n"
        text += "➕ <code>/mod add @username</code> - добавить модератора\n"
        text += "➖ <code>/mod remove @username</code> - удалить модератора\n"
        text += "📋 <code>/mod list</code> - список модераторов\n"
        text += "📨 <code>/mod reports</code> - список жалоб\n"
        text += "🔨 <code>/mod bans</code> - список банов\n"
        bot.send_message(message.chat.id, text, parse_mode='HTML')
        return
    
    subcommand = args_list[1].lower()
    
    if subcommand == 'add':
        if len(args_list) < 3:
            bot.send_message(message.chat.id, "❌ Укажите пользователя: /mod add @username")
            return
        
        target = args_list[2].replace('@', '')
        target_id = None
        
        if message.reply_to_message:
            target_id = message.reply_to_message.from_user.id
        else:
            all_stats = database.find('player_stats', {})
            for stats in all_stats:
                name = stats.get('name', '')
                if target.lower() in name.lower():
                    target_id = stats['user_id']
                    break
        
        if not target_id:
            bot.send_message(message.chat.id, f"❌ Пользователь @{target} не найден")
            return
        
        success, msg = add_moderator(target_id, user_id)
        bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {msg}")
    
    elif subcommand == 'remove':
        if len(args_list) < 3:
            bot.send_message(message.chat.id, "❌ Укажите пользователя: /mod remove @username")
            return
        
        target = args_list[2].replace('@', '')
        target_id = None
        
        all_stats = database.find('player_stats', {})
        for stats in all_stats:
            name = stats.get('name', '')
            if target.lower() in name.lower():
                target_id = stats['user_id']
                break
        
        if not target_id:
            bot.send_message(message.chat.id, f"❌ Пользователь @{target} не найден")
            return
        
        success, msg = remove_moderator(target_id, user_id)
        bot.send_message(message.chat.id, f"{'✅' if success else '❌'} {msg}")
    
    elif subcommand == 'list':
        moderators = get_moderators()
        if not moderators:
            bot.send_message(message.chat.id, "📋 Модераторов нет")
            return
        
        text = "👮 <b>Модераторы:</b>\n\n"
        for mod in moderators:
            text += f"👤 {mod.get('name', 'Игрок')}\n"
        bot.send_message(message.chat.id, text, parse_mode='HTML')
    
    elif subcommand == 'reports':
        reports = get_reports('pending', limit=10)
        if not reports:
            bot.send_message(message.chat.id, "📨 Нет новых жалоб")
            return
        
        text = "📨 <b>Последние жалобы:</b>\n\n"
        for i, report in enumerate(reports[:10], 1):
            text += (
                f"{i}. {report.get('reported_name', 'Игрок')}\n"
                f"   От: {report.get('reporter_name', 'Игрок')}\n"
                f"   Причина: {report.get('reason', 'Не указана')[:50]}\n"
                f"   ID: <code>{report.get('created_at', '')}</code>\n\n"
            )
        bot.send_message(message.chat.id, text, parse_mode='HTML')
    
    elif subcommand == 'bans':
        bans = get_bans(limit=20)
        if not bans:
            bot.send_message(message.chat.id, "🔨 Нет активных банов")
            return
        
        text = "🔨 <b>Активные баны:</b>\n\n"
        for ban in bans[:20]:
            ban_type = "Постоянный" if ban.get('is_permanent') else "Временный"
            ban_until = ban.get('ban_until', '')
            if ban_until:
                try:
                    from datetime import datetime
                    until = datetime.fromisoformat(ban_until)
                    ban_type += f" (до {until.strftime('%d.%m.%Y %H:%M')})"
                except:
                    pass
            text += (
                f"👤 {ban.get('user_name', 'Игрок')}\n"
                f"   Тип: {ban_type}\n"
                f"   Причина: {ban.get('reason', 'Не указана')[:50]}\n\n"
            )
        bot.send_message(message.chat.id, text, parse_mode='HTML')
    
    else:
        bot.send_message(message.chat.id, "❌ Неизвестная команда. Используйте /mod для справки")

@bot.message_handler(commands=['settings'])
def show_settings(message, *args, **kwargs):
    """Показать настройки игры"""
    if message.chat.type == 'private':
        bot.send_message(message.chat.id, '⚙️ Настройки доступны только в группах.')
        return
    
    settings = get_settings(message.chat.id)
    kb = get_settings_keyboard(message.chat.id)
    
    text = (
        '⚙️ <b>Настройки игры</b>\n\n'
        f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
        f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
        f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
        f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
        f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
        f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
        f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
        '💡 Нажми на кнопку, чтобы изменить настройку'
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data == 'request interact')
def request_interact(call):
    message_id = call.message.message_id
    required_request = database.find_one('requests', {'message_id': message_id})

    if not required_request:
        safe_answer_callback(call.id, text='Заявка истекла.', show_alert=True)
        return

    user_id = call.from_user.id
    current_players = required_request.get('players', [])
    
    # Поиск игрока для удаления/добавления
    player_found = next((p for p in current_players if p['id'] == user_id), None)
    
    if player_found:
        # Выход - удаляем по id для надежности
        action = '$pull'
        update_data = {'players': {'id': user_id}}  # Удаляем по id, а не по всему объекту
        inc_val = -1
        alert_text = "Ты вышел."
    else:
        # Проверяем, не забанен ли игрок
        try:
            from moderation import is_banned
            if is_banned(user_id):
                safe_answer_callback(call.id, text='❌ Вы забанены и не можете участвовать в играх', show_alert=True)
                return
        except:
            pass  # Если модуль модерации недоступен, пропускаем проверку
        
        # Вход
        if len(current_players) >= config.PLAYERS_COUNT_LIMIT:
            safe_answer_callback(call.id, text='Нет мест!', show_alert=True)
            return
        action = '$push'
        update_data = {'players': user_object(call.from_user)}
        inc_val = 1
        alert_text = "Ты в игре!"

    updates = {
        action: update_data,
        '$inc': {'players_count': inc_val},
        '$set': {'time': time() + config.REQUEST_OVERDUE_TIME}
    }
    
    updated_doc = database.find_one_and_update('requests', {'_id': required_request['_id']}, updates)

    if updated_doc:
        players_list = updated_doc['players']
        formatted_list = '\n'.join([f'{i + 1}. {p["name"]}' for i, p in enumerate(players_list)])
        time_str = get_time_str(updated_doc['time'])
        
        text = lang.game_created.format(
            owner=updated_doc['owner']['name'],
            time=time_str,
            order=f'Игроки ({len(players_list)}/{config.PLAYERS_COUNT_LIMIT}):\n{formatted_list}'
        )
        
        keyboard = InlineKeyboardMarkup()
        # Кнопка меняется в зависимости от статуса
        btn_text = '🚪 Выйти' if next((p for p in players_list if p['id'] == user_id), None) else '🎮 Вступить'
        keyboard.add(InlineKeyboardButton(text=btn_text, callback_data='request interact'))
        
        # Кнопка старта для создателя
        if updated_doc['owner']['id'] == user_id and len(players_list) >= config.PLAYERS_COUNT_TO_START:
            keyboard.add(InlineKeyboardButton(text='▶️ Начать игру', callback_data='start game'))
        
        try:
            bot.edit_message_text(text=text, chat_id=call.message.chat.id, message_id=message_id, reply_markup=keyboard, parse_mode='HTML')
        except: pass

    safe_answer_callback(call.id, alert_text)

@bot.group_message_handler(regexp=command_regexp('create'))
def create(message, *args, **kwargs):
    if database.find_one('requests', {'chat': message.chat.id}) or database.find_one('games', {'chat': message.chat.id, 'game': 'mafia'}):
        bot.send_message(message.chat.id, 'Игра/заявка уже есть!')
        return

    player_object = user_object(message.from_user)
    request_time = time() + config.REQUEST_OVERDUE_TIME
    time_str = get_time_str(request_time)

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text='🎮 Вступить', callback_data='request interact'))

    answer = lang.game_created.format(
        owner=player_object["name"],
        time=time_str,
        order=f'Игроки (1/{config.PLAYERS_COUNT_LIMIT}):\n1. {player_object["name"]}'
    )
    sent = bot.send_message(message.chat.id, answer, reply_markup=kb, parse_mode='HTML')

    database.insert_one('requests', {
        'id': str(uuid4())[:8], 'owner': player_object, 'players': [player_object],
        'time': request_time, 'chat': message.chat.id, 'message_id': sent.message_id, 'players_count': 1
    })

@bot.callback_query_handler(func=lambda call: call.data == 'start game')
def start_game_button(call):
    req = database.find_one('requests', {'chat': call.message.chat.id})
    if req and req['owner']['id'] == call.from_user.id:
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except: pass
        start_game_logic(call.message)
    else:
        safe_answer_callback(call.id, "Только создатель может начать!", show_alert=True)

@bot.group_message_handler(regexp=command_regexp('start'))
def start_game_command(message, *args, **kwargs):
    start_game_logic(message)

def start_game_logic(message):
    req = database.find_one('requests', {'chat': message.chat.id})
    if req and req['players_count'] >= config.PLAYERS_COUNT_TO_START:
        database.delete_one('requests', {'_id': req['_id']})
        
        msg_id, game = start_game(message.chat.id, req['players'], mode='full')
        
        # Рассылка ролей с описанием
        for p in game['players']:
            # Получаем описание роли из lang
            role_desc = getattr(lang, f"{p['role']}_role", "Описание отсутствует")
            role_goal = getattr(lang, f"goal_{p['role']}", "Победить")
            
            # Применяем кастомизацию к имени роли
            try:
                from customization import format_role_name
                role_display = format_role_name(role_titles[p['role']], p['id'], game.get('chat'))
            except ImportError:
                role_display = role_titles[p['role']]
            
            text = lang.role_card.format(role=role_display, goal=role_goal, description=role_desc)
            send_player_message(p, game, text)
            
        bot.send_message(message.chat.id, lang.game_started.format(order="\n".join([p['name'] for p in game['players']])), parse_mode='HTML')
        
        game_w_id = database.find_one('games', {'chat': message.chat.id})
        # Переходим к первой ночи (стадия -3)
        go_to_next_stage(game_w_id, inc=1)
    else:
        bot.send_message(message.chat.id, f'Нужно минимум {config.PLAYERS_COUNT_TO_START} игрока!')

@bot.group_message_handler(regexp=command_regexp('cancel'))
def cancel(message, *args, **kwargs):
    req = database.find_one('requests', {'chat': message.chat.id})
    if req:
        if req['owner']['id'] == message.from_user.id or message.from_user.id == config.ADMIN_ID:
            database.delete_one('requests', {'_id': req['_id']})
            bot.send_message(message.chat.id, 'Заявка отменена.')
    else:
        bot.send_message(message.chat.id, 'Нет заявки.')

def is_chat_admin(chat_id, user_id):
    """Проверяет, является ли пользователь админом группы"""
    try:
        # Проверяем глобального админа
        if user_id == config.ADMIN_ID:
            return True
        
        # Проверяем админов группы
        admins = bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.user.id == user_id:
                return True
        return False
    except Exception as e:
        # В случае ошибки разрешаем только глобальному админу
        if user_id == config.ADMIN_ID:
            return True
        return False

@bot.group_message_handler(regexp=command_regexp('stopgame'))
def stopgame_command(message, *args, **kwargs):
    """Команда для завершения игры (только для админов группы)"""
    # Проверяем права админа
    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, '❌ Эта команда доступна только администраторам группы.')
        return
    
    # Ищем активную игру
    game = database.find_one('games', {'chat': message.chat.id})
    if not game:
        bot.send_message(message.chat.id, '❌ В этом чате нет активной игры.')
        return
    
    # Завершаем игру
    stop_game(game, f'🎮 Игра принудительно завершена администратором {message.from_user.first_name or "Админ"}.')
    bot.send_message(message.chat.id, '✅ Игра успешно завершена.')

@bot.callback_query_handler(func=lambda call: call.data.startswith('help_'))
def help_callback(call):
    """Обработка кнопок помощи"""
    chat_id = call.message.chat.id
    
    if call.data == 'help_rules':
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
        rules = (
            '🎄 <b>КОДЕКС СЕВЕРНОГО ПОЛЮСА</b> 📜\n\n'
            '🎅 <b>Мирные:</b> Добряк, Счастливчик, Хлопушка (Камикадзе)\n'
            '🎅 <b>Порядок:</b> Санта-Комиссар, Младший Олень (Сержант)\n'
            '🧦 <b>Защита:</b> Эльф-лекарь (Доктор)\n'
            '😈 <b>Злодеи:</b> Гринч (Мафия), Тёмный Эльф (Дон)\n'
            '🍷 <b>Нейтралы:</b> Снегурочка (Любовница), Крампус-Маньяк, Адвокат Рождества, Снегодуй (Самоубийца), Бродяга (Бомж)\n\n'
            '🏆 <b>ПОБЕДА:</b>\n'
            '✅ Мирные — изгнать всех злодеев\n'
            '✅ Мафия — уравнять количество с мирными\n'
            '✅ Маньяк — остаться одному\n\n'
            '💡 <b>Особенности:</b>\n'
            '• Свободное обсуждение (5 минут)\n'
            '• Любой может выставить кандидата на голосование\n'
            '• Первая ночь: знакомство мафии (1 минута)\n'
            '• Ночные действия: проверки, убийства, лечение\n'
            '• События: метель, костёр, фейерверк и др.'
        )
        try:
            bot.edit_message_text(rules, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(chat_id, rules, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
        return
    
    elif call.data == 'help_settings':
        if call.message.chat.type == 'private':
            bot.answer_callback_query(call.id, "Настройки доступны только в группах", show_alert=True)
            return
        try:
            settings = get_settings(chat_id)
            kb = get_settings_keyboard(chat_id)
            text = (
                '⚙️ <b>Настройки игры</b>\n\n'
                f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                '💡 Нажми на кнопку, чтобы изменить настройку'
            )
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(chat_id, '⚙️ Настройки доступны только в группах.')
        safe_answer_callback(call.id)
        return
    
    elif call.data == 'help_back':
        # Возвращаемся к главному меню с кнопками
        chat_id = call.message.chat.id
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📜 Правила", callback_data='help_rules'),
            InlineKeyboardButton("⚙️ Настройки", callback_data='help_settings')
        )
        kb.add(
            InlineKeyboardButton("🎮 Создать игру", callback_data='help_create'),
            InlineKeyboardButton("📊 Статистика", callback_data='help_stats')
        )
        kb.add(
            InlineKeyboardButton("🏆 Топ игроков", callback_data='help_leaderboard'),
            InlineKeyboardButton("🎖 Достижения", callback_data='help_achievements')
        )
        kb.add(
            InlineKeyboardButton("👥 Команды", callback_data='help_team'),
            InlineKeyboardButton("🛒 Магазин", callback_data='help_shop')
        )
        
        # Добавляем кнопку WebApp если доступна
        try:
            from config import SET_WEBHOOK, SERVER_IP
            if SET_WEBHOOK and SERVER_IP:
                webapp_url = f"https://morethansnow.pythonanywhere.com"
                kb.add(InlineKeyboardButton('🌐 Открыть сайт', web_app={'url': webapp_url}))
        except:
            pass
        
        text = (
            '🎮 <b>Команды:</b>\n\n'
            '📜 <code>/rules</code> - Правила игры\n'
            '⚙️ <code>/settings</code> - Настройки (в группе)\n'
            '🎮 <code>/create</code> - Создать игру (в группе)\n'
            '📊 <code>/stats</code> - Статистика игрока\n'
            '🏆 <code>/leaderboard</code> - Топ игроков\n'
            '🎖 <code>/achievements</code> - Достижения\n'
            '👥 <code>/team</code> - Команды\n'
            '🎨 <code>/customize</code> - Кастомизация ролей\n'
            '🛒 <code>/shop</code> - Магазин\n'
            '🎁 <code>/events</code> - Магазин событий\n'
            '📝 <code>/report</code> - Пожаловаться на игрока\n\n'
            '💡 <b>Используйте кнопки ниже для быстрого доступа:</b>'
        )
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
        return
    
    elif call.data == 'help_create':
        bot.answer_callback_query(call.id, "Используйте /create в группе", show_alert=True)
        return
    
    elif call.data == 'help_stats':
        # Показываем статистику через команду
        stats_text = get_user_stats(call.from_user.id, call.from_user)
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
        try:
            bot.edit_message_text(stats_text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, stats_text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
        return
    
    elif call.data == 'help_leaderboard':
        # Показываем топ игроков
        all_stats = database.find('player_stats', {})
        if not all_stats:
            text = "Таблица лидеров пуста. Сыграйте свою первую игру!"
        else:
            leaderboard_data = sorted(all_stats, key=lambda x: x.get('elo_rating', 1000), reverse=True)
            text = '🏆 <b>ТАБЛИЦА ЛИДЕРОВ</b>\n\n'
            medals = ['🥇', '🥈', '🥉']
            for i, stats in enumerate(leaderboard_data[:20]):
                name = html.escape(stats.get('name', 'Игрок'))
                elo = stats.get('elo_rating', 1000)
                if i < 3:
                    text += f'{medals[i]} <b>{name}</b>: {elo}\n'
                else:
                    text += f'{i+1}. {name}: {elo}\n'
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
        return
    
    elif call.data == 'help_achievements':
        # Показываем достижения
        from achievements import get_player_achievements, get_achievements_by_rarity
        user_id = call.from_user.id
        player_achievements = get_player_achievements(user_id)
        all_achievements = get_achievements_by_rarity()
        
        text = '🎖 <b>ДОСТИЖЕНИЯ</b>\n\n'
        text += f'Получено: {len(player_achievements)}/{len(all_achievements)}\n\n'
        
        # Показываем последние полученные достижения
        if player_achievements:
            text += '<b>Ваши достижения:</b>\n'
            for ach in player_achievements[:10]:
                text += f"{ach.get('icon', '🏆')} {ach.get('name', 'Достижение')}\n"
        else:
            text += 'У вас пока нет достижений. Играйте, чтобы получить их!'
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
        return
    
    elif call.data == 'help_shop':
        # Показываем информацию о магазине
        try:
            from shop import get_shop_items
        except ImportError:
            text = '🛒 <b>МАГАЗИН</b>\n\nМагазин временно недоступен.'
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
            try:
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except:
                bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=kb)
            safe_answer_callback(call.id)
            return
        
        text = (
            '🛒 <b>МАГАЗИН</b>\n\n'
            'В магазине вы можете купить:\n'
            '🎖️ Бейджи - особые иконки\n'
            '🎩 Титулы - особые звания\n'
            '📦 Кейсы - случайные события\n'
            '🍭 Конфеты - за Звезды Telegram\n\n'
            'Используйте команду /shop для просмотра товаров.'
        )
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
        return
    
    elif call.data == 'help_team':
        # Показываем информацию о командах
        from teams import get_user_team
        user_id = call.from_user.id
        team = get_user_team(user_id)
        
        if team:
            text = f'👥 <b>Ваша команда: {team.get("name", "Без названия")}</b>\n\n'
            text += f'Участников: {len(team.get("members", []))}\n'
            text += f'ID команды: <code>{team.get("team_id", "")}</code>\n\n'
            text += 'Используйте /team для управления командой.'
        else:
            text = (
                '👥 <b>КОМАНДЫ</b>\n\n'
                'Создайте команду или присоединитесь к существующей!\n\n'
                'Команды:\n'
                '/team create - Создать команду\n'
                '/team invite - Пригласить игрока\n'
                '/team info - Информация о команде\n'
                '/team stats - Статистика команды\n'
                '/team invitations - Ваши приглашения\n'
                '/team accept - Принять приглашение\n'
                '/team reject - Отклонить приглашение\n'
                '/team leave - Покинуть команду'
            )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='help_back'))
        try:
            bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
        return
    
@bot.callback_query_handler(func=lambda call: call.data.startswith('settings_'))
def settings_callback_handler(call):
    """Обработка настроек"""
    try:
        chat_id = call.message.chat.id
        data = call.data
        
        logger.debug(f"Settings callback: {data} from chat {chat_id}")
        
        if data == 'settings_close':
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            safe_answer_callback(call.id, "Настройки закрыты")
            return
        
        if data == 'settings_reset':
            try:
                from settings import DEFAULT_SETTINGS
                for key, value in DEFAULT_SETTINGS.items():
                    update_setting(chat_id, key, value)
                safe_answer_callback(call.id, "✅ Настройки сброшены")
                # Обновляем сообщение
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        if data == 'settings_back':
            try:
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except:
                pass
            safe_answer_callback(call.id)
            return
        
        if data == 'settings_discussion':
            try:
                kb = get_discussion_time_keyboard(chat_id)
                bot.edit_message_text(
                    '⏱ <b>Выберите время обсуждения</b>',
                    chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb
                )
            except:
                pass
            safe_answer_callback(call.id)
            return
        
        if data == 'settings_vote':
            try:
                kb = get_vote_time_keyboard(chat_id)
                bot.edit_message_text(
                    '🗳 <b>Выберите время голосования</b>',
                    chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb
                )
            except:
                pass
            safe_answer_callback(call.id)
            return
        
        if data == 'settings_night':
            try:
                kb = get_night_time_keyboard(chat_id)
                bot.edit_message_text(
                    '🌙 <b>Выберите время на ночные действия</b>',
                    chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb
                )
            except:
                pass
            safe_answer_callback(call.id)
            return
        
        if data == 'settings_min_players':
            try:
                kb = get_min_players_keyboard(chat_id)
                bot.edit_message_text(
                    '👥 <b>Выберите минимальное количество игроков</b>',
                    chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb
                )
            except:
                pass
            safe_answer_callback(call.id)
            return
        
        if data == 'settings_max_players':
            try:
                kb = get_max_players_keyboard(chat_id)
                bot.edit_message_text(
                    '👥 <b>Выберите максимальное количество игроков</b>',
                    chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb
                )
            except:
                pass
            safe_answer_callback(call.id)
            return
        
        if data == 'settings_auto_start':
            try:
                settings = get_settings(chat_id)
                new_value = not settings.get('auto_start', False)
                update_setting(chat_id, 'auto_start', new_value)
                safe_answer_callback(call.id, f"Автостарт: {'✅' if new_value else '❌'}")
                # Обновляем сообщение
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        if data == 'settings_events':
            try:
                settings = get_settings(chat_id)
                new_value = not settings.get('events_enabled', True)
                update_setting(chat_id, 'events_enabled', new_value)
                safe_answer_callback(call.id, f"События: {'✅' if new_value else '❌'}")
                # Обновляем сообщение
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        if data == 'settings_show_roles':
            try:
                settings = get_settings(chat_id)
                new_value = not settings.get('show_roles_on_end', True)
                update_setting(chat_id, 'show_roles_on_end', new_value)
                safe_answer_callback(call.id, f"Роли в конце: {'✅' if new_value else '❌'}")
                # Обновляем сообщение
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        # Обработка установки значений
        if data.startswith('settings_set_discussion_'):
            try:
                value = int(data.split('_')[-1])
                update_setting(chat_id, 'discussion_time', value)
                safe_answer_callback(call.id, f"✅ Обсуждение: {value // 60} мин")
                # Возвращаемся к главному меню
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        if data.startswith('settings_set_vote_'):
            try:
                value = int(data.split('_')[-1])
                update_setting(chat_id, 'vote_time', value)
                safe_answer_callback(call.id, f"✅ Голосование: {value} сек")
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        if data.startswith('settings_set_night_'):
            try:
                value = int(data.split('_')[-1])
                update_setting(chat_id, 'night_time', value)
                safe_answer_callback(call.id, f"✅ Ночь: {value} сек")
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        if data.startswith('settings_set_min_players_'):
            try:
                value = int(data.split('_')[-1])
                update_setting(chat_id, 'min_players', value)
                safe_answer_callback(call.id, f"✅ Мин. игроков: {value}")
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
        
        if data.startswith('settings_set_max_players_'):
            try:
                value = int(data.split('_')[-1])
                update_setting(chat_id, 'max_players', value)
                safe_answer_callback(call.id, f"✅ Макс. игроков: {value}")
                settings = get_settings(chat_id)
                kb = get_settings_keyboard(chat_id)
                text = (
                    '⚙️ <b>Настройки игры</b>\n\n'
                    f'⏱ Обсуждение: {settings.get("discussion_time", 300) // 60} мин\n'
                    f'🗳 Голосование: {settings.get("vote_time", 30)} сек\n'
                    f'🌙 Ночь: {settings.get("night_time", 30)} сек\n'
                    f'👥 Игроков: {settings.get("min_players", 4)}-{settings.get("max_players", 12)}\n'
                    f'🚀 Автостарт: {"✅" if settings.get("auto_start", False) else "❌"}\n'
                    f'🎲 События: {"✅" if settings.get("events_enabled", True) else "❌"}\n'
                    f'👁 Роли в конце: {"✅" if settings.get("show_roles_on_end", True) else "❌"}\n\n'
                    '💡 Нажми на кнопку, чтобы изменить настройку'
                )
                bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
            except Exception as e:
                safe_answer_callback(call.id, f"Ошибка: {e}", show_alert=True)
            return
    except Exception as e:
        logger.error(f"Error in settings_callback_handler: {e}", exc_info=True)
        safe_answer_callback(call.id, "Произошла ошибка", show_alert=True)

def candidate_callback_action(call, game):
    """Обработка выбора кандидата через callback (из ЛС)"""
    user_id = call.from_user.id
    player = next((p for p in game['players'] if p['id'] == user_id and p['alive']), None)
    
    if not player:
        safe_answer_callback(call.id, "Ты не участвуешь в игре", show_alert=True)
        return
    
    # Проверяем, что это стадия обсуждения
    if game.get('stage') != 0:
        safe_answer_callback(call.id, "Сейчас не время для выставления кандидатов", show_alert=True)
        return
    
    try:
        target_idx = int(call.data.split()[1])
        if target_idx < 0 or target_idx >= len(game['players']):
            safe_answer_callback(call.id, "Неверный индекс игрока", show_alert=True)
            return
    except:
        safe_answer_callback(call.id, "Ошибка обработки", show_alert=True)
        return
    
    target = game['players'][target_idx]
    player_idx = game['players'].index(player)
    
    # Проверяем, что цель жива
    if not target.get('alive'):
        safe_answer_callback(call.id, "Этот игрок уже мертв", show_alert=True)
        return
    
    # Нельзя выставить самого себя
    if target_idx == player_idx:
        safe_answer_callback(call.id, "Нельзя выставить самого себя", show_alert=True)
        return
    
    # Добавляем в кандидаты, если ещё не добавлен
    candidates = game.get('candidates', [])
    if target_idx not in candidates:
        candidates.append(target_idx)
        database.update_one('games', {'_id': game['_id']}, {'$set': {'candidates': candidates}})
        
        # Отправляем сообщение в группу
        bot.send_message(game['chat'], lang.vote_candidate.format(
            player_num=player.get('position', player_idx + 1),
            player_name=player['name'],
            target_num=target.get('position', target_idx + 1),
            target_name=target['name']
        ), parse_mode='HTML')
        
        safe_answer_callback(call.id, f"✅ Игрок №{target.get('position', target_idx + 1)} выставлен на голосование")
    else:
        safe_answer_callback(call.id, "Этот игрок уже выставлен на голосование", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('ach_filter'))
def achievement_filter_handler(call):
    """Обработчик фильтрации достижений"""
    try:
        from achievements import get_player_achievements, get_achievements_by_rarity, ACHIEVEMENTS
    except ImportError:
        safe_answer_callback(call.id, "Система достижений недоступна", show_alert=True)
        return
    
    user_id = call.from_user.id
    filter_type = call.data.split()[1] if len(call.data.split()) > 1 else 'all'
    
    stats = database.find_one('player_stats', {'user_id': user_id})
    if not stats:
        safe_answer_callback(call.id, "У вас нет достижений", show_alert=True)
        return
    
    player_achievements = get_player_achievements(user_id)
    player_ach_ids = {a['id'] for a in player_achievements}
    
    # Фильтруем достижения
    if filter_type == 'all':
        achievements_to_show = list(ACHIEVEMENTS.values())
    else:
        achievements_to_show = get_achievements_by_rarity(filter_type)
    
    # Сортируем: сначала разблокированные, потом заблокированные
    achievements_to_show.sort(key=lambda x: (x['id'] not in player_ach_ids, x['rarity']))
    
    # Формируем текст
    rarity_names = {
        'common': '🟢 Обычные',
        'uncommon': '🔵 Необычные',
        'rare': '🟣 Редкие',
        'epic': '🟠 Эпические',
        'legendary': '🟡 Легендарные',
        'all': '📊 Все достижения'
    }
    
    text = f"🏆 <b>{rarity_names.get(filter_type, 'Достижения')}</b>\n\n"
    
    for ach in achievements_to_show[:20]:  # Показываем до 20
        is_unlocked = ach['id'] in player_ach_ids
        icon = "✅" if is_unlocked else "🔒"
        reward = f" (+{ach.get('reward_candies', 0)}🍭)" if not is_unlocked else ""
        text += f"{icon} {ach['icon']} <b>{ach['name']}</b>{reward}\n"
        text += f"   {ach['description']}\n\n"
    
    if len(achievements_to_show) > 20:
        text += f"\n... и еще {len(achievements_to_show) - 20} достижений"
    
    # Кнопки для фильтрации
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🟢 Обычные", callback_data='ach_filter common'),
        InlineKeyboardButton("🔵 Необычные", callback_data='ach_filter uncommon')
    )
    kb.add(
        InlineKeyboardButton("🟣 Редкие", callback_data='ach_filter rare'),
        InlineKeyboardButton("🟠 Эпические", callback_data='ach_filter epic')
    )
    kb.add(
        InlineKeyboardButton("🟡 Легендарные", callback_data='ach_filter legendary'),
        InlineKeyboardButton("📊 Все", callback_data='ach_filter all')
    )
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
    except:
        pass
    safe_answer_callback(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('team_'))
def team_callback_handler(call):
    """Обработчик inline кнопок для команды /team"""
    try:
        from teams import (
            get_user_team, get_team_stats, get_user_invitations, leave_team
        )
    except ImportError:
        safe_answer_callback(call.id, "Система команд недоступна", show_alert=True)
        return
    
    user_id = call.from_user.id
    action = call.data
    
    if action == 'team_info':
        team = get_user_team(user_id)
        if not team:
            safe_answer_callback(call.id, "❌ Вы не состоите в команде", show_alert=True)
            return
        
        text = (
            f"👥 <b>Команда: {team['name']}</b>\n\n"
            f"🆔 ID: <code>{team['team_id']}</code>\n"
            f"👤 Создатель: {team['creator_name']}\n"
            f"👥 Участников: {len(team['members'])}\n"
            f"📨 Приглашений: {len(team.get('invitations', []))}\n\n"
            f"<b>Участники:</b>\n"
        )
        
        for member in team['members']:
            role_icon = "👑" if member.get('role') == 'leader' else "👤"
            text += f"{role_icon} {member['name']}\n"
        
        if team.get('invitations'):
            text += "\n<b>Приглашенные:</b>\n"
            for inv in team['invitations']:
                text += f"📨 {inv['name']}\n"
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='team_back'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
    
    elif action == 'team_stats':
        team = get_user_team(user_id)
        if not team:
            safe_answer_callback(call.id, "❌ Вы не состоите в команде", show_alert=True)
            return
        
        stats = get_team_stats(team['team_id'])
        text = (
            f"📊 <b>Статистика команды {team['name']}</b>\n\n"
            f"🎮 Игр сыграно: {stats['total_games']}\n"
            f"✅ Побед: {stats['total_wins']}\n"
            f"❌ Поражений: {stats['total_losses']}\n"
            f"📈 Винрейт: {stats['win_rate']:.1f}%\n"
            f"⭐ Средний ELO: {int(stats['avg_elo'])}\n"
            f"🍭 Всего конфет: {stats['total_candies']}\n"
            f"👥 Участников: {stats['members_count']}"
        )
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='team_back'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
    
    elif action == 'team_invitations':
        invitations = get_user_invitations(user_id)
        if not invitations:
            safe_answer_callback(call.id, "📭 У вас нет приглашений", show_alert=True)
            return
        
        text = "📨 <b>Ваши приглашения:</b>\n\n"
        kb = InlineKeyboardMarkup(row_width=2)
        
        for inv in invitations:
            text += (
                f"👥 {inv['team_name']}\n"
                f"🆔 ID: <code>{inv['team_id']}</code>\n"
                f"👤 Пригласил: {inv.get('inviter_name', 'Игрок')}\n\n"
            )
            kb.add(
                InlineKeyboardButton(f"✅ {inv['team_id']}", callback_data=f'team_accept_{inv["team_id"]}'),
                InlineKeyboardButton(f"❌ {inv['team_id']}", callback_data=f'team_reject_{inv["team_id"]}')
            )
        
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='team_back'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
    
    elif action == 'team_leave':
        # Подтверждение выхода
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Да", callback_data='team_leave_confirm'),
            InlineKeyboardButton("❌ Нет", callback_data='team_back')
        )
        
        try:
            bot.edit_message_text(
                "⚠️ <b>Вы уверены, что хотите покинуть команду?</b>",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=kb
            )
        except:
            bot.send_message(
                call.message.chat.id,
                "⚠️ <b>Вы уверены, что хотите покинуть команду?</b>",
                parse_mode='HTML',
                reply_markup=kb
            )
        safe_answer_callback(call.id)
    
    elif action == 'team_leave_confirm':
        success, msg = leave_team(user_id)
        if success:
            text = f"✅ {msg}"
        else:
            text = f"❌ {msg}"
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='team_back'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
    
    elif action.startswith('team_accept_'):
        team_id = action.replace('team_accept_', '').upper()
        try:
            from teams import accept_invitation
            success, msg = accept_invitation(team_id, user_id)
            if success:
                text = f"✅ {msg}"
            else:
                text = f"❌ {msg}"
        except:
            text = "❌ Ошибка при принятии приглашения"
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='team_back'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
    
    elif action.startswith('team_reject_'):
        team_id = action.replace('team_reject_', '').upper()
        try:
            from teams import reject_invitation
            success, msg = reject_invitation(team_id, user_id)
            if success:
                text = f"✅ {msg}"
            else:
                text = f"❌ {msg}"
        except:
            text = "❌ Ошибка при отклонении приглашения"
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data='team_back'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)
    
    elif action == 'team_back':
        # Возвращаемся к главному меню /team
        from teams import get_user_team
        team = get_user_team(user_id)
        
        text = "👥 <b>Команды для работы с командами:</b>\n\n"
        
        if team:
            text += f"✅ Вы состоите в команде: <b>{team.get('name', 'Без названия')}</b>\n\n"
        else:
            text += "❌ Вы не состоите в команде\n\n"
        
        text += (
            "📝 <code>/team create &lt;название&gt;</code> - создать команду\n"
            "➕ <code>/team invite @username</code> - пригласить игрока\n"
            "✅ <code>/team accept &lt;ID&gt;</code> - принять приглашение\n"
            "❌ <code>/team reject &lt;ID&gt;</code> - отклонить приглашение\n"
        )
        
        kb = InlineKeyboardMarkup(row_width=2)
        if team:
            kb.add(
                InlineKeyboardButton("ℹ️ Информация", callback_data='team_info'),
                InlineKeyboardButton("📊 Статистика", callback_data='team_stats')
            )
            kb.add(
                InlineKeyboardButton("📨 Приглашения", callback_data='team_invitations'),
                InlineKeyboardButton("🚪 Покинуть", callback_data='team_leave')
            )
        else:
            kb.add(
                InlineKeyboardButton("📨 Мои приглашения", callback_data='team_invitations')
            )
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_stars_'))
def buy_stars_callback_handler(call):
    """Обработчик быстрой покупки конфет за звезды"""
    try:
        from shop import SHOP_ITEMS
    except ImportError:
        safe_answer_callback(call.id, "Магазин недоступен", show_alert=True)
        return
    
    user_id = call.from_user.id
    item_id = call.data.replace('buy_stars_', '')
    
    if item_id not in SHOP_ITEMS:
        safe_answer_callback(call.id, "❌ Товар не найден", show_alert=True)
        return
    
    item = SHOP_ITEMS[item_id]
    if item.get('type') != 'candies' or not item.get('cost_stars'):
        safe_answer_callback(call.id, "❌ Этот товар нельзя купить за звезды", show_alert=True)
        return
    
    # Отправляем invoice
    send_stars_invoice(call.message.chat.id, user_id, item)
    safe_answer_callback(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('shop_'))
def shop_callback_handler(call):
    """Обработчик callback-запросов для магазина"""
    try:
        from shop import purchase_item, get_shop_items, get_user_inventory, SHOP_ITEMS
    except ImportError:
        safe_answer_callback(call.id, "Магазин недоступен", show_alert=True)
        return
    
    user_id = call.from_user.id
    action = call.data
    
    if action.startswith('shop_buy_'):
        # Устаревший способ покупки - теперь используется /shop [название]
        safe_answer_callback(call.id, "💡 Используйте команду /shop [название товара] для покупки", show_alert=True)
    
    elif action.startswith('shop_filter'):
        # Фильтрация по категории
        filter_type = action.split()[-1] if ' ' in action else 'all'
        
        stats = database.find_one('player_stats', {'user_id': user_id})
        candies = stats.get('candies', 0) if stats else 0
        
        if filter_type == 'all':
            items = get_shop_items()
        else:
            items = get_shop_items(filter_type)
        
        category_names = {
            'badge': '🎖️ БЕЙДЖИ',
            'title': '🎩 ТИТУЛЫ',
            'case': '📦 КЕЙСЫ',
            'candies': '🍭 КОНФЕТЫ',
            'all': '📊 ВСЕ ТОВАРЫ'
        }
        
        text = "━━━━━━━━━━━━━━━━━━━━\n"
        text += f"🎄 <b>{category_names.get(filter_type, 'МАГАЗИН')}</b> 🎄\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"💰 <b>Ваш баланс:</b> <code>{candies:,}</code> 🍭\n\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        
        # Добавляем товары
        for item in items[:15]:
            cost = item.get('cost_candies') or item.get('cost_stars', 0)
            currency = "🍭" if item.get('cost_candies') else "⭐"
            rarity_emoji = {'common': '🟢', 'uncommon': '🔵', 'rare': '🟣', 'legendary': '🟡'}.get(item.get('rarity', 'common'), '⚪')
            
            text += f"\n{rarity_emoji} {item['icon']} <b>{item['name']}</b>\n"
            text += f"   {item.get('description', '')}\n"
            text += f"   💰 <code>{cost}</code> {currency}\n"
            text += f"   📝 <code>/shop {item['name']}</code>\n"
        
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "💡 <i>Для покупки используйте:</i>\n"
        text += "<code>/shop [название товара]</code>\n"
        text += "━━━━━━━━━━━━━━━━━━━━"
        
        filter_kb = InlineKeyboardMarkup(row_width=3)
        filter_kb.add(
            InlineKeyboardButton("🎖️ Бейджи", callback_data='shop_filter badge'),
            InlineKeyboardButton("🎩 Титулы", callback_data='shop_filter title'),
            InlineKeyboardButton("📦 Кейсы", callback_data='shop_filter case')
        )
        filter_kb.add(
            InlineKeyboardButton("🍭 Конфеты", callback_data='shop_filter candies'),
            InlineKeyboardButton("📦 Инвентарь", callback_data='shop_inventory'),
            InlineKeyboardButton("📊 Все", callback_data='shop_filter all')
        )
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=filter_kb)
        except:
            pass
        safe_answer_callback(call.id)
    
    elif action == 'shop_inventory':
        # Показываем инвентарь
        inventory = get_user_inventory(user_id)
        
        text = "━━━━━━━━━━━━━━━━━━━━\n"
        text += "📦 <b>ВАШ ИНВЕНТАРЬ</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Бейджи
        badges = inventory.get('badges', [])
        if badges:
            text += "🎖️ <b>Бейджи:</b>\n"
            for badge_id in badges:
                if badge_id in SHOP_ITEMS:
                    badge = SHOP_ITEMS[badge_id]
                    text += f"   {badge['icon']} {badge['name']}\n"
            text += "\n"
        else:
            text += "🎖️ <b>Бейджи:</b> <i>Нет</i>\n\n"
        
        # Титулы
        titles = inventory.get('titles', [])
        if titles:
            text += "🎩 <b>Титулы:</b>\n"
            for title_id in titles:
                if title_id in SHOP_ITEMS:
                    title = SHOP_ITEMS[title_id]
                    text += f"   {title['icon']} {title['name']}\n"
            text += "\n"
        else:
            text += "🎩 <b>Титулы:</b> <i>Нет</i>\n\n"
        
        # События
        events = inventory.get('events', [])
        if events:
            text += "🎁 <b>Купленные события:</b>\n"
            for event in events[-10:]:  # Последние 10
                text += f"   {event.get('event_name', 'Событие')}\n"
        else:
            text += "🎁 <b>Купленные события:</b> <i>Нет</i>\n"
        
        text += "\n━━━━━━━━━━━━━━━━━━━━"
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад в магазин", callback_data='shop_filter all'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_stars_'))
def buy_stars_callback_handler(call):
    """Обработчик быстрой покупки конфет за звезды"""
    try:
        from shop import SHOP_ITEMS
    except ImportError:
        safe_answer_callback(call.id, "Магазин недоступен", show_alert=True)
        return
    
    user_id = call.from_user.id
    item_id = call.data.replace('buy_stars_', '')
    
    if item_id not in SHOP_ITEMS:
        safe_answer_callback(call.id, "❌ Товар не найден", show_alert=True)
        return
    
    item = SHOP_ITEMS[item_id]
    if item.get('type') != 'candies' or not item.get('cost_stars'):
        safe_answer_callback(call.id, "❌ Этот товар нельзя купить за звезды", show_alert=True)
        return
    
    # Отправляем invoice
    send_stars_invoice(call.message.chat.id, user_id, item)
    safe_answer_callback(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('shop_'))
def shop_callback_handler(call):
    """Обработчик callback-запросов для магазина"""
    try:
        from shop import purchase_item, get_shop_items, get_user_inventory, SHOP_ITEMS
    except ImportError:
        safe_answer_callback(call.id, "Магазин недоступен", show_alert=True)
        return
    
    user_id = call.from_user.id
    action = call.data
    
    if action.startswith('shop_buy_'):
        # Устаревший способ покупки - теперь используется /shop [название]
        safe_answer_callback(call.id, "💡 Используйте команду /shop [название товара] для покупки", show_alert=True)
    
    elif action.startswith('shop_filter'):
        # Фильтрация по категории
        filter_type = action.split()[-1] if ' ' in action else 'all'
        
        stats = database.find_one('player_stats', {'user_id': user_id})
        candies = stats.get('candies', 0) if stats else 0
        
        if filter_type == 'all':
            items = get_shop_items()
        else:
            items = get_shop_items(filter_type)
        
        category_names = {
            'badge': '🎖️ БЕЙДЖИ',
            'title': '🎩 ТИТУЛЫ',
            'case': '📦 КЕЙСЫ',
            'candies': '🍭 КОНФЕТЫ',
            'all': '📊 ВСЕ ТОВАРЫ'
        }
        
        text = "━━━━━━━━━━━━━━━━━━━━\n"
        text += f"🎄 <b>{category_names.get(filter_type, 'МАГАЗИН')}</b> 🎄\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"💰 <b>Ваш баланс:</b> <code>{candies:,}</code> 🍭\n\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        
        # Добавляем товары в текст
        for item in items[:15]:  # Показываем до 15 товаров
            cost = item.get('cost_candies') or item.get('cost_stars', 0)
            currency = "🍭" if item.get('cost_candies') else "⭐"
            rarity_emoji = {'common': '🟢', 'uncommon': '🔵', 'rare': '🟣', 'legendary': '🟡'}.get(item.get('rarity', 'common'), '⚪')
            
            text += f"\n{rarity_emoji} {item['icon']} <b>{item['name']}</b>\n"
            text += f"   {item.get('description', '')}\n"
            text += f"   💰 <code>{cost}</code> {currency}\n"
            text += f"   📝 <code>/shop {item['name']}</code>\n"
        
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "💡 <i>Для покупки используйте:</i>\n"
        text += "<code>/shop [название товара]</code>\n"
        text += "━━━━━━━━━━━━━━━━━━━━"
        
        filter_kb = InlineKeyboardMarkup(row_width=3)
        filter_kb.add(
            InlineKeyboardButton("🎖️ Бейджи", callback_data='shop_filter badge'),
            InlineKeyboardButton("🎩 Титулы", callback_data='shop_filter title'),
            InlineKeyboardButton("📦 Кейсы", callback_data='shop_filter case')
        )
        filter_kb.add(
            InlineKeyboardButton("🍭 Конфеты", callback_data='shop_filter candies'),
            InlineKeyboardButton("📦 Инвентарь", callback_data='shop_inventory'),
            InlineKeyboardButton("📊 Все", callback_data='shop_filter all')
        )
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=filter_kb)
        except:
            pass
        safe_answer_callback(call.id)
    
    elif action == 'shop_inventory':
        # Показываем инвентарь
        inventory = get_user_inventory(user_id)
        
        text = "━━━━━━━━━━━━━━━━━━━━\n"
        text += "📦 <b>ВАШ ИНВЕНТАРЬ</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # Бейджи
        badges = inventory.get('badges', [])
        if badges:
            text += "🎖️ <b>Бейджи:</b>\n"
            for badge_id in badges:
                if badge_id in SHOP_ITEMS:
                    badge = SHOP_ITEMS[badge_id]
                    text += f"   {badge['icon']} {badge['name']}\n"
            text += "\n"
        else:
            text += "🎖️ <b>Бейджи:</b> <i>Нет</i>\n\n"
        
        # Титулы
        titles = inventory.get('titles', [])
        if titles:
            text += "🎩 <b>Титулы:</b>\n"
            for title_id in titles:
                if title_id in SHOP_ITEMS:
                    title = SHOP_ITEMS[title_id]
                    text += f"   {title['icon']} {title['name']}\n"
            text += "\n"
        else:
            text += "🎩 <b>Титулы:</b> <i>Нет</i>\n\n"
        
        # События
        events = inventory.get('events', [])
        if events:
            text += "🎁 <b>Купленные события:</b>\n"
            for event in events[-10:]:  # Последние 10
                text += f"   {event.get('event_name', 'Событие')}\n"
        else:
            text += "🎁 <b>Купленные события:</b> <i>Нет</i>\n"
        
        text += "\n━━━━━━━━━━━━━━━━━━━━"
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Назад в магазин", callback_data='shop_filter all'))
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=kb)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=kb)
        safe_answer_callback(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('events_filter'))
def events_filter_handler(call):
    """Обработчик фильтрации событий по редкости"""
    try:
        from game_events import get_available_events, get_current_season
    except ImportError:
        safe_answer_callback(call.id, "Система событий недоступна", show_alert=True)
        return
    
    filter_type = call.data.split()[1] if len(call.data.split()) > 1 else 'all'
    user_id = call.from_user.id
    
    stats = database.find_one('player_stats', {'user_id': user_id})
    candies = stats.get('candies', 0) if stats else 0
    
    events = get_available_events()
    current_season = get_current_season()
    season_names = {'winter': '❄️ Зима', 'spring': '🌸 Весна', 'summer': '☀️ Лето', 'autumn': '🍂 Осень'}
    
    # Фильтруем по редкости
    if filter_type == 'all':
        filtered_events = events
    else:
        filtered_events = [e for e in events if e.get('rarity') == filter_type]
    
    rarity_icons = {'common': '🟢', 'rare': '🟣', 'legendary': '🟡'}
    rarity_names = {'common': 'Обычные', 'rare': 'Редкие', 'legendary': 'Легендарные'}
    
    text = f'🍭 <b>Магазин событий</b>\n\n'
    text += f'У тебя: {candies} 🍭\n'
    text += f'Сезон: {season_names.get(current_season, current_season)}\n'
    if filter_type != 'all':
        text += f'Фильтр: {rarity_icons.get(filter_type, "")} {rarity_names.get(filter_type, filter_type)}\n'
    text += '\n'
    
    kb = InlineKeyboardMarkup(row_width=1)
    
    for event in filtered_events[:15]:  # Показываем до 15 событий
        can_afford = candies >= event['cost']
        status = '✅' if can_afford else '❌'
        rarity_icon = rarity_icons.get(event.get('rarity', 'common'), '')
        seasonal_mark = f" ({event.get('seasonal', '')})" if event.get('seasonal') else ""
        text += f'{status} {rarity_icon} {event["description"]}{seasonal_mark}\n'
        text += f'   💰 {event["cost"]} 🍭\n\n'
        
        if can_afford:
            kb.add(InlineKeyboardButton(
                f'{rarity_icon} Купить {event["name"]} ({event["cost"]} 🍭)',
                callback_data=f'buy_event_{event["name"]}'
            ))
    
    if len(filtered_events) > 15:
        text += f'\n... и еще {len(filtered_events) - 15} событий\n'
    
    # Кнопки фильтрации
    filter_kb = InlineKeyboardMarkup(row_width=3)
    filter_kb.add(
        InlineKeyboardButton("🟢 Обычные", callback_data='events_filter common'),
        InlineKeyboardButton("🟣 Редкие", callback_data='events_filter rare'),
        InlineKeyboardButton("🟡 Легендарные", callback_data='events_filter legendary')
    )
    filter_kb.add(InlineKeyboardButton("📊 Все", callback_data='events_filter all'))
    
    # Объединяем клавиатуры
    if kb.keyboard:
        for row in filter_kb.keyboard:
            kb.keyboard.append(row)
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                            parse_mode='HTML', reply_markup=kb if kb.keyboard else filter_kb)
    except:
        pass
    safe_answer_callback(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_event_'))
def buy_event_handler(call):
    """Обработка покупки события"""
    from game_events import get_event_by_name, get_available_events
    
    user_id = call.from_user.id
    event_name = call.data.replace('buy_event_', '')
    
    # Получаем статистику игрока
    stats = database.find_one('player_stats', {'user_id': user_id})
    if not stats:
        stats = {'user_id': user_id, 'candies': 0}
        database.insert_one('player_stats', stats)
    
    candies = stats.get('candies', 0)
    
    # Находим событие
    events = get_available_events()
    event_info = next((e for e in events if e['name'] == event_name), None)
    if not event_info:
        safe_answer_callback(call.id, "Событие не найдено", show_alert=True)
        return
    
    # Проверяем баланс
    if candies < event_info['cost']:
        safe_answer_callback(call.id, f"Недостаточно конфет! Нужно {event_info['cost']} 🍭, у тебя {candies} 🍭", show_alert=True)
        return
    
    # Ищем активную игру
    game = None
    if call.message.chat.type in ('group', 'supergroup'):
        game = database.find_one('games', {'chat': call.message.chat.id, 'game': 'mafia'})
    else:
        all_games = database.find('games', {'game': 'mafia'})
        for g in all_games:
            if any(p.get('id') == user_id for p in g.get('players', [])):
                game = g
                break
    
    if not game:
        safe_answer_callback(call.id, "Нет активной игры", show_alert=True)
        return
    
    # Проверяем, что игрок в игре
    player = next((p for p in game.get('players', []) if p.get('id') == user_id), None)
    if not player:
        safe_answer_callback(call.id, "Ты не участвуешь в игре", show_alert=True)
        return
    
    # Создаём и применяем событие
    event = get_event_by_name(event_name)
    if not event:
        safe_answer_callback(call.id, "Ошибка создания события", show_alert=True)
        return
    
    # Применяем событие
    effect_result = event.apply_effect(game)
    
    # Списываем конфеты
    new_candies = candies - event_info['cost']
    database.update_one('player_stats', {'user_id': user_id}, {'$set': {'candies': new_candies}})
    
    # Сохраняем событие в игру
    if 'purchased_events' not in game:
        game['purchased_events'] = []
    game['purchased_events'].append({
        'name': event_name,
        'player_id': user_id,
        'player_name': player.get('name', 'Игрок'),
        'timestamp': time()
    })
    database.update_one('games', {'_id': game['_id']}, {'$set': {'purchased_events': game['purchased_events']}})
    
    # Отправляем сообщение в группу
    try:
        bot.send_message(
            game['chat'],
            f'🎁 <b>{player.get("name", "Игрок")}</b> активировал событие!\n\n{event.description}',
            parse_mode='HTML'
        )
    except:
        pass
    
    safe_answer_callback(call.id, f"✅ Событие активировано! Потрачено {event_info['cost']} 🍭")
    
    # Обновляем сообщение магазина
    try:
        new_candies_text = f'🍭 <b>Магазин событий</b>\n\nУ тебя: {new_candies} 🍭\n\n'
        new_candies_text += f'✅ Событие "{event.description}" активировано!\n\n'
        new_candies_text += '💡 Используй /events для покупки других событий.'
        bot.edit_message_text(new_candies_text, call.message.chat.id, call.message.message_id, parse_mode='HTML')
    except:
        pass

@bot.callback_query_handler(func=lambda call: True)
def callback_router(call):
    if call.data in ['request interact', 'start game']: return
    if call.data.startswith('help_') or call.data.startswith('settings_') or call.data.startswith('buy_event_'): return

    # Для callback из ЛС нужно искать игру по всем чатам
    game = None
    if call.message.chat.type in ('group', 'supergroup'):
        game = database.find_one('games', {'chat': call.message.chat.id})
    else:
        # Это ЛС, ищем игру по игроку
        user_id = call.from_user.id
        # Ищем все игры и проверяем, есть ли в них этот игрок
        try:
            all_games = database.find('games', {})
            for g in all_games:
                if any(p.get('id') == user_id for p in g.get('players', [])):
                    game = g
                    break
        except:
            pass
    
    if not game: 
        safe_answer_callback(call.id, "Игра не найдена", show_alert=True)
        return

    action = call.data.split()[0]
    
    if action == 'candidate':
        candidate_callback_action(call, game)
    elif action == 'vote_discussion':
        vote_discussion_action(call, game)
    elif action in ['mistress', 'don', 'doctor', 'commissar', 'maniac', 'lawyer', 'bum']:
        role_action(call, game, action)
    elif action == 'shot':
        mafia_shot(call, game)
    elif action == 'vote':
        vote_action(call, game)
    elif action == 'don_check':
        don_check_action(call, game)
    elif action == 'commissar_check':
        commissar_check_action(call, game)
    elif action == 'commissar_kill':
        commissar_kill_action(call, game)

def role_action(call, game, role_key):
    user_id = call.from_user.id
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    
    if not player or player['role'] != role_key: return
    
    # Быстрая проверка перед атомарной операцией
    if user_id in game.get('blocks', []):
        safe_answer_callback(call.id, lang.action_blocked, show_alert=True)
        return
    if user_id in game.get('played', []):
        safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
        # Удаляем кнопки, если они еще есть
        try: bot.edit_message_reply_markup(player['id'], player.get('pm_id'), reply_markup=None)
        except: pass
        return

    # Тень действует на себя (скрывается)
    if role_key == 'shadow':
        # Атомарная операция: добавляем в played только если еще не там
        result = database.find_one_and_update(
            'games',
            {'_id': game['_id'], 'played': {'$ne': user_id}},
            {'$addToSet': {'played': user_id}, '$set': {'hidden_shadows': [user_id]}},
            return_document=True
        )
        if not result:
            safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
            return
        safe_answer_callback(call.id, lang.shadow_active)
        try: bot.edit_message_text(lang.shadow_active, chat_id=player['id'], message_id=player.get('pm_id'))
        except: pass
        return

    try: 
        target_idx = int(call.data.split()[1])  # Индекс уже правильный из stages.py
        if target_idx >= len(game['players']) or target_idx < 0:
            safe_answer_callback(call.id, "Неверный индекс", show_alert=True)
            return
    except: 
        safe_answer_callback(call.id, "Ошибка обработки", show_alert=True)
        return
    
    # Формируем обновление в зависимости от роли
    update = {}
    resp = "Действие принято"
    target_id = game['players'][target_idx]['id']
    
    if role_key == 'mistress':
        update['$push'] = {'blocks': target_id}
        resp = "Заблокирован!"
    elif role_key == 'drunkard':
        update['$push'] = {'silenced': target_id}
        resp = "Напоен!"
    elif role_key == 'grinch':
        update['$push'] = {'stolen': target_id}
        resp = "Украдено!"
        # Можно отправить уведомление жертве, что ее обокрали
    elif role_key == 'doctor':
        update['$push'] = {'heals': target_idx}
        resp = "Вылечен!"
        # Проверяем самолечение
        if target_idx == game['players'].index(player):
            player_idx = game['players'].index(player)
            if game['players'][player_idx].get('self_heal_used', False):
                safe_answer_callback(call.id, "Ты уже использовал самолечение!", show_alert=True)
                return
            database.update_one('games', {'_id': game['_id']}, {
                '$set': {f'players.{player_idx}.self_heal_used': True}
            })
    elif role_key == 'snowman':
        update['$push'] = {'shields': target_idx}
        resp = "Укрыт!"
    elif role_key == 'angel':
        update['$push'] = {'blessings': target_idx}
        resp = "Благословлен!"
    elif role_key == 'tracker':
        # Проверяем, ходил ли игрок (есть ли в played)
        # Внимание: played наполняется по ходу ночи. Если следопыт ходит первым, он ничего не увидит.
        # Обычно следопыт получает результат в конце ночи (stage 11).
        update['$push'] = {'tracks': target_idx}
        resp = "Слежка начата"
        bot.send_message(player['id'], "Результат слежки будет утром.")
    elif role_key == 'maniac':
        update['$set'] = {'maniac_shot': target_idx}
        resp = "Выстрел принят"
    elif role_key == 'lawyer':
        # Адвокат выбирает подзащитного один раз
        player_idx = next(i for i, p in enumerate(game['players']) if p['id'] == user_id)
        update['$set'] = {f'players.{player_idx}.lawyer_client': target_idx}
        resp = "Подзащитный выбран"
    elif role_key == 'bum':
        # Бомж следит за игроком
        source_idx = next(i for i, p in enumerate(game['players']) if p['id'] == user_id)
        update['$set'] = {'bum_witness': {'source': source_idx, 'target': target_idx}}
        resp = "Слежка начата"
    elif role_key == 'don':
        # Пурга блокирует проверки детектива
        if role_key == 'sheriff' and game.get('current_event') == 'blizzard':
            msg = "❄️ Пурга! Ты ничего не видишь."
        else:
            t_role = game['players'][target_idx]['role']
            # Тень проверяется как мирный, если скрылась
            is_hidden = game['players'][target_idx]['id'] in game.get('hidden_shadows', [])
            
            if role_key == 'don':
                msg = "ЭТО ШЕРИФ!" if t_role == 'sheriff' and not is_hidden else "Не шериф."
            else:
                msg = "ЭТО МАФИЯ!" if t_role in ['mafia', 'don', 'krampus'] and not is_hidden else "Мирный."
        
        try: bot.edit_message_text(msg, chat_id=player['id'], message_id=player.get('pm_id'))
        except: bot.send_message(player['id'], msg)
        resp = "Проверено"

    # Атомарная операция: добавляем в played только если еще не там
    # Это предотвращает повторные действия при быстрых нажатиях
    update['$addToSet'] = {'played': user_id}
    result = database.find_one_and_update(
        'games',
        {'_id': game['_id'], 'played': {'$ne': user_id}},  # Условие: user_id еще не в played
        update,
        return_document=True
    )
    
    if not result:
        # Игрок уже сделал ход (race condition)
        safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
        # Удаляем кнопки
        try: bot.edit_message_reply_markup(player['id'], player.get('pm_id'), reply_markup=None)
        except: pass
        return
    
    safe_answer_callback(call.id, resp)
    
    # Удаляем сообщение с кнопками сразу после действия
    pm_id = player.get('pm_id')
    if pm_id:
        try:
            bot.delete_message(player['id'], pm_id)
        except:
            # Если не удалось удалить, хотя бы убираем кнопки
            try:
                bot.edit_message_reply_markup(player['id'], pm_id, reply_markup=None)
            except:
                pass
    
    # Отправляем сообщение в группу о завершении действия (только для некоторых ролей)
    if role_key in ['doctor', 'maniac', 'mistress', 'lawyer', 'bum']:
        player_pos = player.get('position', game['players'].index(player) + 1)
        role_titles_dict = {
            'doctor': 'Доктор',
            'maniac': 'Маньяк',
            'mistress': 'Любовница',
            'lawyer': 'Адвокат',
            'bum': 'Бомж'
        }
        role_display = role_titles_dict.get(role_key, 'Игрок')
        try:
            bot.send_message(
                game['chat'],
                f'✅ {role_display} №{player_pos} {player["name"]} выполнил действие.',
                parse_mode='HTML'
            )
        except:
            pass
    
    # Проверяем, все ли действия выполнены - если да, переходим к следующей стадии
    # Только для ночных ролей (doctor, maniac, mistress, lawyer, bum)
    if role_key in ['doctor', 'maniac', 'mistress', 'lawyer', 'bum']:
        from stages import check_night_stage_complete
        updated_game = database.find_one('games', {'_id': game['_id']})
        if updated_game:
            check_night_stage_complete(updated_game)

def mafia_shot(call, game):
    user_id = call.from_user.id
    if not any(p['id'] == user_id and p['role'] in ['mafia', 'don'] for p in game['players']): 
        safe_answer_callback(call.id, "Ты не мафия!", show_alert=True)
        return
    
    # Быстрая проверка перед атомарной операцией
    if user_id in game.get('blocks', []):
        safe_answer_callback(call.id, lang.action_blocked, show_alert=True)
        return
    if user_id in game.get('played', []):
        safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
        # Удаляем кнопки
        player = next((p for p in game['players'] if p['id'] == user_id), None)
        if player:
            try: bot.edit_message_reply_markup(player['id'], player.get('pm_id'), reply_markup=None)
            except: pass
        return

    try: 
        target_idx = int(call.data.split()[1])  # Индекс уже правильный, не нужно -1
        if target_idx >= len(game['players']) or target_idx < 0:
            safe_answer_callback(call.id, "Неверный индекс", show_alert=True)
            return
    except: 
        safe_answer_callback(call.id, "Ошибка обработки", show_alert=True)
        return

    # Атомарная операция: добавляем в played только если еще не там
    result = database.find_one_and_update(
        'games',
        {'_id': game['_id'], 'played': {'$ne': user_id}},
        {'$addToSet': {'played': user_id}, '$push': {'shots': target_idx}},
        return_document=True
    )
    
    if not result:
        safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
        player = next((p for p in game['players'] if p['id'] == user_id), None)
        if player:
            try: bot.edit_message_reply_markup(player['id'], player.get('pm_id'), reply_markup=None)
            except: pass
        return
    
    safe_answer_callback(call.id, "Выстрел принят")
    
    # Удаляем сообщение с кнопками сразу после действия
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if player:
        pm_id = player.get('pm_id')
        if pm_id:
            try:
                bot.delete_message(player['id'], pm_id)
            except:
                try:
                    bot.edit_message_reply_markup(player['id'], pm_id, reply_markup=None)
                except:
                    pass
    
    # Проверяем, все ли мафия выстрелили - если да, переходим к следующей стадии
    from stages import check_night_stage_complete
    updated_game = database.find_one('games', {'_id': game['_id']})
    if updated_game:
        check_night_stage_complete(updated_game)

def vote_action(call, game):
    user_id = call.from_user.id
    if user_id in game.get('silenced', []):
        safe_answer_callback(call.id, lang.action_silenced, show_alert=True)
        return
        
    try: 
        target_idx = int(call.data.split()[1])  # Индекс уже правильный из stages.py
        if target_idx < 0 or target_idx >= len(game['players']):
            safe_answer_callback(call.id, "Неверный индекс", show_alert=True)
            return
    except: 
        safe_answer_callback(call.id, "Ошибка обработки", show_alert=True)
        return
    
    voter_idx = next(i for i, p in enumerate(game['players']) if p['id'] == user_id)
    
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {f'vote.{voter_idx}': target_idx, f'vote_map_ids.{user_id}': target_idx}
    })
    
    try:
        kb = InlineKeyboardMarkup(row_width=5)
        targets = [p for p in enumerate(game['players']) if p[1]['alive']]
        kb.add(*[InlineKeyboardButton(f'{i+1}', callback_data=f'vote {i+1}') for i, p in targets])
        kb.add(InlineKeyboardButton('🤐', callback_data='vote 0'))
        
        # Конкурс печенек - скрытое голосование
        updated_game = database.find_one('games', {'_id': game['_id']})
        vote_text = lang.vote_start.format(vote_list="🍪 Голосование скрыто (Конкурс печенек)") if updated_game.get('current_event') == 'cookies' else lang.vote_start.format(vote_list=get_votes(updated_game))
        
        bot.edit_message_text(
            vote_text,
            chat_id=game['chat'],
            message_id=game['message_id'],
            reply_markup=kb,
            parse_mode='HTML'
        )
    except: pass
    
    safe_answer_callback(call.id, "Голос принят")

def vote_discussion_action(call, game):
    """Голосование во время обсуждения - можно голосовать за любого живого игрока"""
    user_id = call.from_user.id
    
    # Проверяем, что игрок жив
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    if not player or not player.get('alive', True):
        safe_answer_callback(call.id, "Ты не можешь голосовать", show_alert=True)
        return
    
    try: 
        target_idx = int(call.data.split()[1])
        if target_idx < 0 or target_idx >= len(game['players']):
            safe_answer_callback(call.id, "Неверный индекс", show_alert=True)
            return
    except: 
        safe_answer_callback(call.id, "Ошибка обработки", show_alert=True)
        return
    
    # Проверяем, что цель жива
    target = game['players'][target_idx]
    if not target.get('alive', True):
        safe_answer_callback(call.id, "Этот игрок уже мертв", show_alert=True)
        return
    
    # Нельзя голосовать за себя
    if target_idx == game['players'].index(player):
        safe_answer_callback(call.id, "Нельзя голосовать за себя", show_alert=True)
        return
    
    # Обновляем голос
    voter_idx = game['players'].index(player)
    database.find_one_and_update('games', {'_id': game['_id']}, {
        '$set': {f'vote.{voter_idx}': target_idx, f'vote_map_ids.{user_id}': target_idx}
    })
    
    # Обновляем сообщение обсуждения с новыми голосами
    try:
        from stages import update_timer
        updated_game = database.find_one('games', {'_id': game['_id']})
        if updated_game:
            update_timer(updated_game)
    except: 
        pass
    
    safe_answer_callback(call.id, f"✅ Голос за {target.get('name', 'игрока')} принят")

def don_check_action(call, game):
    """Дон проверяет, является ли игрок комиссаром"""
    user_id = call.from_user.id
    don = next((p for p in game['players'] if p['id'] == user_id and p['role'] == 'don'), None)
    if not don: return
    
    # Быстрая проверка перед атомарной операцией
    if user_id in game.get('blocks', []):
        safe_answer_callback(call.id, lang.action_blocked, show_alert=True)
        return
    if user_id in game.get('played', []):
        safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
        try: bot.edit_message_reply_markup(don['id'], don.get('pm_id'), reply_markup=None)
        except: pass
        return
    
    try:
        target_idx = int(call.data.split()[1])
        target = game['players'][target_idx]
        
        is_commissar = target['role'] == 'commissar'
        msg = "ЭТО КОМИССАР!" if is_commissar else "Не комиссар."
        
        # Атомарная операция
        result = database.find_one_and_update(
            'games',
            {'_id': game['_id'], 'played': {'$ne': user_id}},
            {
                '$set': {'don_check': target_idx},
                '$addToSet': {'played': user_id}
            },
            return_document=True
        )
        
        if not result:
            safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
            try: bot.edit_message_reply_markup(don['id'], don.get('pm_id'), reply_markup=None)
            except: pass
            return
        
        bot.send_message(don['id'], msg, parse_mode='HTML')
        safe_answer_callback(call.id, "Проверено")
        try: bot.edit_message_reply_markup(don['id'], don.get('pm_id'), reply_markup=None)
        except: pass
        
        # Проверяем, все ли действия выполнены - если да, переходим к следующей стадии
        from stages import check_night_stage_complete
        updated_game = database.find_one('games', {'_id': game['_id']})
        if updated_game:
            check_night_stage_complete(updated_game)
    except:
        pass

def commissar_check_action(call, game):
    """Комиссар проверяет роль игрока"""
    user_id = call.from_user.id
    commissar = next((p for p in game['players'] if p['id'] == user_id and p['role'] == 'commissar'), None)
    if not commissar: return
    
    # Быстрая проверка перед атомарной операцией
    if user_id in game.get('blocks', []):
        safe_answer_callback(call.id, lang.action_blocked, show_alert=True)
        return
    if user_id in game.get('played', []):
        safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
        try: bot.edit_message_reply_markup(commissar['id'], commissar.get('pm_id'), reply_markup=None)
        except: pass
        return
    
    try:
        target_idx = int(call.data.split()[1])
        target = game['players'][target_idx]
        
        # Атомарная операция
        result = database.find_one_and_update(
            'games',
            {'_id': game['_id'], 'played': {'$ne': user_id}},
            {
                '$set': {'commissar_action': 'check', 'commissar_target': target_idx},
                '$addToSet': {'played': user_id}
            },
            return_document=True
        )
        
        if not result:
            safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
            try: bot.edit_message_reply_markup(commissar['id'], commissar.get('pm_id'), reply_markup=None)
            except: pass
            return
        
        # Проверка защиты адвоката
        lawyer = next((p for p in game['players'] if p.get('lawyer_client') == target_idx), None)
        if lawyer:
            msg = "Мирный житель"  # Адвокат защищает
            bot.send_message(game['chat'], lang.lawyer_protection, parse_mode='HTML')
        else:
            is_mafia = target['role'] in ('mafia', 'don')
            msg = "ЭТО МАФИЯ!" if is_mafia else "Мирный житель"
        
        bot.send_message(commissar['id'], msg, parse_mode='HTML')
        
        # Сержант узнаёт о проверке
        sergeant = next((p for p in game['players'] if p['role'] == 'sergeant' and p['alive']), None)
        if sergeant:
            target_pos = target.get('position', target_idx + 1)
            bot.send_message(sergeant['id'], lang.sergeant_info.format(target_num=target_pos), parse_mode='HTML')
        
        safe_answer_callback(call.id, "Проверено")
        
        # Удаляем сообщение с кнопками
        pm_id = commissar.get('pm_id')
        if pm_id:
            try:
                bot.delete_message(commissar['id'], pm_id)
            except:
                try:
                    bot.edit_message_reply_markup(commissar['id'], pm_id, reply_markup=None)
                except:
                    pass
        
        # Отправляем сообщение в группу о завершении действия
        commissar_pos = commissar.get('position', game['players'].index(commissar) + 1)
        try:
            bot.send_message(
                game['chat'],
                f'✅ Комиссар №{commissar_pos} {commissar["name"]} выполнил действие.',
                parse_mode='HTML'
            )
        except:
            pass
        
        # Проверяем, все ли действия выполнены - если да, переходим к следующей стадии
        from stages import check_night_stage_complete
        updated_game = database.find_one('games', {'_id': game['_id']})
        if updated_game:
            check_night_stage_complete(updated_game)
    except:
        pass

def commissar_kill_action(call, game):
    """Комиссар убивает игрока"""
    user_id = call.from_user.id
    commissar = next((p for p in game['players'] if p['id'] == user_id and p['role'] == 'commissar'), None)
    if not commissar: return
    
    # Быстрая проверка перед атомарной операцией
    if user_id in game.get('blocks', []):
        safe_answer_callback(call.id, lang.action_blocked, show_alert=True)
        return
    if user_id in game.get('played', []):
        safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
        try: bot.edit_message_reply_markup(commissar['id'], commissar.get('pm_id'), reply_markup=None)
        except: pass
        return
    
    try:
        target_idx = int(call.data.split()[1])
        if target_idx >= len(game['players']) or target_idx < 0:
            safe_answer_callback(call.id, "Неверный индекс", show_alert=True)
            return
        target = game['players'][target_idx]
        
        # Атомарная операция
        result = database.find_one_and_update(
            'games',
            {'_id': game['_id'], 'played': {'$ne': user_id}},
            {
                '$set': {'commissar_action': 'kill', 'commissar_target': target_idx},
                '$addToSet': {'played': user_id}
            },
            return_document=True
        )
        
        if not result:
            safe_answer_callback(call.id, "Ты уже сделал ход.", show_alert=True)
            try: bot.edit_message_reply_markup(commissar['id'], commissar.get('pm_id'), reply_markup=None)
            except: pass
            return
        
        target_pos = target.get('position', target_idx + 1)
        bot.send_message(commissar['id'], f"Ты убил игрока №{target_pos} {target['name']}", parse_mode='HTML')
        safe_answer_callback(call.id, "Убийство выполнено")
        
        # Удаляем сообщение с кнопками
        pm_id = commissar.get('pm_id')
        if pm_id:
            try:
                bot.delete_message(commissar['id'], pm_id)
            except:
                try:
                    bot.edit_message_reply_markup(commissar['id'], pm_id, reply_markup=None)
                except:
                    pass
        
        # Отправляем сообщение в группу о завершении действия
        commissar_pos = commissar.get('position', game['players'].index(commissar) + 1)
        try:
            bot.send_message(
                game['chat'],
                f'✅ Комиссар №{commissar_pos} {commissar["name"]} выполнил действие.',
                parse_mode='HTML'
            )
        except:
            pass
        
        # Проверяем, все ли действия выполнены - если да, переходим к следующей стадии
        from stages import check_night_stage_complete
        updated_game = database.find_one('games', {'_id': game['_id']})
        if updated_game:
            check_night_stage_complete(updated_game)
    except:
        pass

# --- MINI GAMES ---

@bot.message_handler(func=lambda message: message.from_user.id == config.ADMIN_ID, regexp=command_regexp('reset'))
def reset(message, *args, **kwargs):
    database.delete_many('games', {})
    bot.send_message(message.chat.id, 'База игр очищена!')

@bot.group_message_handler(content_types=['text'])
def game_suggestion(message, game, *args, **kwargs):
    if not game or not message.text: return
    
    # Обработка команд TrueMafia
    if game.get('game') == 'mafia':
        text = message.text.lower().strip()
        user_id = message.from_user.id
        
        # Лучший ход (для убитого ночью)
        if game.get('best_move_player') is not None:
            best_move_player_idx = game['best_move_player']
            best_move_player = game['players'][best_move_player_idx]
            if best_move_player['id'] == user_id:
                handle_best_move(message, game, text)
                return
    

# Функция pass_speech больше не нужна - убрана для свободного общения

def handle_best_move(message, game, text):
    """Обработка лучшего хода"""
    try:
        # Парсим номера игроков
        numbers = [int(n) for n in text.split() if n.isdigit()]
        
        if len(numbers) != 3:
            bot.send_message(message.chat.id, 'Нужно назвать ровно 3 номера игроков через пробел.')
            return
        
        # Проверяем, что номера валидны
        positions = [p['position'] for p in game['players'] if p['alive']]
        valid_numbers = [n for n in numbers if n in positions]
        
        if len(valid_numbers) != 3:
            bot.send_message(message.chat.id, 'Некоторые номера неверны. Назови 3 номера живых игроков.')
            return
        
        suspects = ' '.join([str(n) for n in valid_numbers])
        best_move_player_idx = game['best_move_player']
        best_move_player = game['players'][best_move_player_idx]
        
        bot.send_message(message.chat.id, lang.best_move_result.format(
            player_num=best_move_player['position'],
            suspects=suspects
        ), parse_mode='HTML')
        
        database.update_one('games', {'_id': game['_id']}, {'$set': {'best_move_player': None}})
        
    except Exception as e:
        bot.send_message(message.chat.id, f'Ошибка: {e}')

# ==================== ОБРАБОТЧИКИ ПЛАТЕЖЕЙ ЧЕРЕЗ TELEGRAM STARS ====================

def send_stars_invoice(chat_id: int, user_id: int, item: dict):
    """Отправка invoice для покупки конфет за Telegram Stars"""
    try:
        from shop import SHOP_ITEMS
        
        stars_cost = item.get('cost_stars', 0)
        candies_amount = item.get('amount', 0)
        
        if stars_cost == 0 or candies_amount == 0:
            bot.send_message(chat_id, "❌ Ошибка: неверные параметры товара.")
            return
        
        # Создаем invoice
        prices = [LabeledPrice(label=f"{candies_amount} конфет", amount=stars_cost)]
        
        invoice_payload = f"candies_{item['id']}_{user_id}"
        
        try:
            bot.send_invoice(
                chat_id,
                title=f"Покупка {item['name']}",
                description=item.get('description', f'Покупка {candies_amount} конфет за {stars_cost} звезд'),
                invoice_payload=invoice_payload,
                provider_token="",  # Для Telegram Stars provider_token должен быть пустым
                currency="XTR",  # XTR - валюта Telegram Stars
                prices=prices,
                start_parameter=invoice_payload,  # Уникальный параметр для каждого платежа
                reply_markup=payment_keyboard()
            )
        except ApiException as e:
            # Если ошибка связана с неподдерживаемой платформой
            if "Bad Request" in str(e) or "not supported" in str(e).lower():
                bot.send_message(
                    chat_id,
                    f"⚠️ <b>Покупка за Telegram Stars</b>\n\n"
                    f"💰 Товар: {item['name']}\n"
                    f"⭐ Стоимость: {stars_cost} звезд\n"
                    f"🍭 Вы получите: {candies_amount} конфет\n\n"
                    f"📱 <i>Telegram Stars доступны только в мобильных приложениях Telegram.</i>\n"
                    f"💡 Пожалуйста, используйте Telegram на телефоне для покупки конфет за звезды.",
                    parse_mode='HTML'
                )
            else:
                raise
    except Exception as e:
        logging.error(f"Error sending invoice: {e}", exc_info=True)
        bot.send_message(chat_id, "❌ Ошибка при создании платежа. Попробуйте позже.")

def payment_keyboard():
    """Создание клавиатуры с кнопкой оплаты"""
    keyboard = InlineKeyboardMarkup()
    button = InlineKeyboardButton(text="Оплатить", pay=True)
    keyboard.add(button)
    return keyboard

@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout_query(pre_checkout_query):
    """Обработчик проверки платежа перед оплатой"""
    try:
        # Всегда подтверждаем платеж
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logging.error(f"Error in pre_checkout_query: {e}")
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Ошибка обработки платежа")

@bot.message_handler(content_types=['successful_payment'])
def handle_successful_payment(message):
    """Обработчик успешного платежа через Telegram Stars"""
    try:
        user_id = message.from_user.id
        payment = message.successful_payment
        
        # Извлекаем информацию о платеже
        invoice_payload = payment.invoice_payload
        total_amount = payment.total_amount
        currency = payment.currency
        
        # Парсим payload: candies_<item_id>_<user_id>
        if not invoice_payload.startswith('candies_'):
            bot.send_message(message.chat.id, "❌ Ошибка: неверный формат платежа.")
            return
        
        parts = invoice_payload.split('_')
        if len(parts) < 3:
            bot.send_message(message.chat.id, "❌ Ошибка: неверный формат платежа.")
            return
        
        item_id = '_'.join(parts[1:-1])  # Может быть несколько подчеркиваний в ID
        
        from shop import SHOP_ITEMS
        
        if item_id not in SHOP_ITEMS:
            bot.send_message(message.chat.id, "❌ Товар не найден.")
            return
        
        item = SHOP_ITEMS[item_id]
        candies_amount = item.get('amount', 0)
        
        # Сохраняем информацию о платеже
        payment_data = {
            'user_id': user_id,
            'item_id': item_id,
            'amount': total_amount,
            'currency': currency,
            'candies_received': candies_amount,
            'payment_date': message.date,
            'invoice_payload': invoice_payload
        }
        
        # Сохраняем в базу данных (можно создать коллекцию payments)
        try:
            database.insert_one('payments', payment_data)
        except:
            pass  # Если коллекция не существует, пропускаем
        
        # Начисляем конфеты
        stats = database.find_one('player_stats', {'user_id': user_id})
        if not stats:
            # Создаем новую запись статистики
            database.insert_one('player_stats', {
                'user_id': user_id,
                'candies': candies_amount,
                'games_played': 0,
                'games_won': 0
            })
        else:
            # Добавляем конфеты к существующим
            current_candies = stats.get('candies', 0)
            database.update_one('player_stats', {'user_id': user_id}, {
                '$set': {'candies': current_candies + candies_amount}
            })
        
        # Отправляем подтверждение
        bot.send_message(
            message.chat.id,
            f"✅ <b>Платеж принят!</b>\n\n"
            f"🎁 Вы получили: <b>{candies_amount:,}</b> 🍭\n"
            f"💰 Потрачено: <b>{total_amount}</b> {currency}\n\n"
            f"🥳 Спасибо за вашу покупку! 🤗",
            parse_mode='HTML'
        )
        
    except Exception as e:
        logging.error(f"Error handling successful payment: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка при обработке платежа. Обратитесь к администратору.")

@bot.group_message_handler()
def default_handler(message, *args, **kwargs): pass