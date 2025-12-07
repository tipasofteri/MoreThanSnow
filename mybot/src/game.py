from bot import bot
import database
from html import escape 
import random

role_titles = {
    # --- Базовые роли (TrueMafia стиль) ---
    'peace': '🎁 Добряк (Мирный)',
    'civilian': '🎁 Добряк (Мирный)',
    'mafia': '🎩 Гринч (Мафия)',
    'don': '🕯 Тёмный Эльф (Дон)',
    'commissar': '🎅 Санта-Комиссар (Комиссар)',
    'sergeant': '👮 Младший Олень (Сержант)',
    'doctor': '🧦 Эльф-лекарь (Доктор)',
    'maniac': '💀 Крампус-Маньяк (Маньяк)',
    'mistress': '💃 Снегурочка (Любовница)',
    'lawyer': '⚖️ Адвокат Рождества (Адвокат)',
    'suicide': '❄️ Снегодуй (Самоубийца)',
    'bum': '🧊 Бродяга (Бомж)',
    'lucky': '🍀 Счастливчик',
    'kamikaze': '🧨 Хлопушка (Камикадзе)'
}

def get_role_name(role_code):
    return role_titles.get(role_code, f'❓ Роль ({role_code})')

def calculate_expected_score(player_rating, opponent_rating):
    """Рассчитать ожидаемый результат (0-1) на основе рейтингов"""
    return 1 / (1 + 10 ** ((opponent_rating - player_rating) / 400))

def get_k_factor(games_played):
    """Определить K-фактор на основе количества сыгранных игр"""
    if games_played < 30:
        return 32  # Новички - больше изменений
    elif games_played < 100:
        return 24  # Средний опыт
    else:
        return 16  # Опытные игроки - меньше изменений

def update_elo_rating(game, reason):
    """Обновить ELO рейтинг игроков после завершения игры"""
    # Определяем победившую команду
    winner_team = None
    if 'Мирные победили' in reason or 'Победа Добра' in reason:
        winner_team = 'peaceful'
    elif 'Мафия победила' in reason or 'Победа Зла' in reason:
        winner_team = 'mafia'
    elif 'Маньяк победил' in reason:
        winner_team = 'maniac'
    
    if not winner_team:
        return  # Неизвестный результат, пропускаем
    
    # Получаем статистику всех игроков для расчета среднего рейтинга
    players_stats = {}
    for player in game['players']:
        user_id = player['id']
        stats = database.find_one('player_stats', {'user_id': user_id})
        if not stats:
            # Инициализируем рейтинг для новых игроков
            elo_rating = 1000  # Начальный рейтинг
        else:
            elo_rating = stats.get('elo_rating', 1000)
        players_stats[user_id] = {
            'stats': stats,
            'rating': elo_rating,
            'player': player
        }
    
    # Рассчитываем средний рейтинг всех игроков
    all_ratings = [p['rating'] for p in players_stats.values()]
    average_rating = sum(all_ratings) / len(all_ratings) if all_ratings else 1000
    
    # Обновляем рейтинг для каждого игрока
    for user_id, player_data in players_stats.items():
        player = player_data['player']
        role = player.get('role', 'peace')
        stats = player_data['stats']
        current_rating = player_data['rating']
        
        # Определяем, выиграл ли игрок
        won = False
        if winner_team == 'peaceful' and role in ('peace', 'civilian', 'commissar', 'sergeant', 'doctor', 'lucky', 'kamikaze'):
            won = True
        elif winner_team == 'mafia' and role in ('mafia', 'don'):
            won = True
        elif winner_team == 'maniac' and role == 'maniac':
            won = True
        
        # Фактический результат (1.0 за победу, 0.0 за поражение)
        actual_score = 1.0 if won else 0.0
        
        # Ожидаемый результат против среднего рейтинга соперников
        expected_score = calculate_expected_score(current_rating, average_rating)
        
        # K-фактор на основе опыта игрока
        games_played = stats.get('games_played', 0) if stats else 0
        k_factor = get_k_factor(games_played)
        
        # Рассчитываем изменение рейтинга
        rating_change = k_factor * (actual_score - expected_score)
        new_rating = max(0, int(current_rating + rating_change))  # Рейтинг не может быть отрицательным
        
        # Сохраняем новый рейтинг
        if stats:
            stats['elo_rating'] = new_rating
            stats['elo_change'] = int(rating_change)  # Изменение рейтинга для отображения
            database.update_one('player_stats', {'user_id': user_id}, {'$set': stats}, upsert=True)
        else:
            # Создаем новую запись
            new_stats = {
                'user_id': user_id,
                'name': player.get('name', 'Игрок'),
                'elo_rating': new_rating,
                'elo_change': int(rating_change),
                'games_played': 0,
                'games_won': 0,
                'games_lost': 0,
                'roles_played': {},
                'wins_by_role': {},
                'wins_by_team': {'peaceful': 0, 'mafia': 0, 'maniac': 0},
                'candies': 0
            }
            database.insert_one('player_stats', new_stats)

def update_player_stats(game, reason):
    """Обновить статистику игроков после завершения игры"""
    from datetime import datetime
    
    # Сначала обновляем ELO рейтинг
    update_elo_rating(game, reason)
    
    # Определяем победившую команду
    winner_team = None
    if 'Мирные победили' in reason or 'Победа Добра' in reason:
        winner_team = 'peaceful'
    elif 'Мафия победила' in reason or 'Победа Зла' in reason:
        winner_team = 'mafia'
    elif 'Маньяк победил' in reason:
        winner_team = 'maniac'
    
    # Получаем текущее время
    now = datetime.now()
    game_hour = now.hour  # 0-23
    game_day = now.weekday()  # 0=Monday, 6=Sunday
    
    # Вычисляем средний рейтинг всех игроков в игре
    all_ratings = []
    for p in game['players']:
        p_stats = database.find_one('player_stats', {'user_id': p['id']})
        p_rating = p_stats.get('elo_rating', 1000) if p_stats else 1000
        all_ratings.append(p_rating)
    avg_opponent_rating = sum(all_ratings) / len(all_ratings) if all_ratings else 1000
    
    # Импортируем модуль достижений
    try:
        from achievements import check_achievements, award_achievement
    except ImportError:
        check_achievements = None
        award_achievement = None
    
    # Обновляем статистику для каждого игрока
    for player in game['players']:
        user_id = player['id']
        role = player.get('role', 'peace')
        is_alive = player.get('alive', False)
        
        # Получаем текущую статистику
        stats = database.find_one('player_stats', {'user_id': user_id})
        if not stats:
            stats = {
                'user_id': user_id,
                'name': player.get('name', 'Игрок'),
                'games_played': 0,
                'games_won': 0,
                'games_lost': 0,
                'roles_played': {},
                'wins_by_role': {},
                'wins_by_team': {'peaceful': 0, 'mafia': 0, 'maniac': 0},
                'elo_rating': 1000,  # Начальный рейтинг
                'candies': 0,
                'achievements': [],  # Список полученных достижений
                'elo_history': [],  # История рейтинга
                'avg_opponent_rating': 0,  # Средний рейтинг соперников
                'games_by_hour': {},  # Статистика по часам (0-23)
                'games_by_day': {},  # Статистика по дням недели (0-6)
                'wins_by_hour': {},  # Победы по часам
                'wins_by_day': {}  # Победы по дням недели
            }
        
        # Инициализируем новые поля, если их нет
        if 'elo_history' not in stats:
            stats['elo_history'] = []
        if 'avg_opponent_rating' not in stats:
            stats['avg_opponent_rating'] = 0
        if 'games_by_hour' not in stats:
            stats['games_by_hour'] = {}
        if 'games_by_day' not in stats:
            stats['games_by_day'] = {}
        if 'wins_by_hour' not in stats:
            stats['wins_by_hour'] = {}
        if 'wins_by_day' not in stats:
            stats['wins_by_day'] = {}
        
        # Обновляем статистику
        stats['games_played'] = stats.get('games_played', 0) + 1
        
        # Определяем, выиграл ли игрок
        won = False
        if winner_team == 'peaceful' and role in ('peace', 'civilian', 'commissar', 'sergeant', 'doctor', 'lucky', 'kamikaze'):
            won = True
        elif winner_team == 'mafia' and role in ('mafia', 'don'):
            won = True
        elif winner_team == 'maniac' and role == 'maniac':
            won = True
        
        if won:
            stats['games_won'] = stats.get('games_won', 0) + 1
            stats['wins_by_team'][winner_team] = stats['wins_by_team'].get(winner_team, 0) + 1
            stats['wins_by_role'][role] = stats['wins_by_role'].get(role, 0) + 1
            # Даём 10 конфет за победу
            stats['candies'] = stats.get('candies', 0) + 10
        else:
            stats['games_lost'] = stats.get('games_lost', 0) + 1
        
        # Обновляем статистику по ролям
        stats['roles_played'][role] = stats['roles_played'].get(role, 0) + 1
        
        # Сохраняем текущий рейтинг в историю (последние 50 игр)
        current_elo = stats.get('elo_rating', 1000)
        stats['elo_history'].append({
            'rating': current_elo,
            'timestamp': now.isoformat(),
            'game_id': game.get('id', 'unknown')
        })
        # Оставляем только последние 50 записей
        if len(stats['elo_history']) > 50:
            stats['elo_history'] = stats['elo_history'][-50:]
        
        # Обновляем средний рейтинг соперников (скользящее среднее)
        current_avg = stats.get('avg_opponent_rating', 1000)
        games_count = stats.get('games_played', 1)
        # Взвешенное среднее: старый средний * (n-1)/n + новый * 1/n
        stats['avg_opponent_rating'] = (current_avg * (games_count - 1) + avg_opponent_rating) / games_count
        
        # Обновляем статистику по времени суток
        stats['games_by_hour'][game_hour] = stats['games_by_hour'].get(game_hour, 0) + 1
        if won:
            stats['wins_by_hour'][game_hour] = stats['wins_by_hour'].get(game_hour, 0) + 1
        
        # Обновляем статистику по дням недели
        stats['games_by_day'][game_day] = stats['games_by_day'].get(game_day, 0) + 1
        if won:
            stats['wins_by_day'][game_day] = stats['wins_by_day'].get(game_day, 0) + 1
        
        # Обновляем имя, если изменилось
        stats['name'] = player.get('name', stats.get('name', 'Игрок'))
        
        # Инициализируем рейтинг, если его нет
        if 'elo_rating' not in stats:
            stats['elo_rating'] = 1000
        
        # Инициализируем конфеты, если их нет
        if 'candies' not in stats:
            stats['candies'] = 0
        
        # Инициализируем достижения, если их нет
        if 'achievements' not in stats:
            stats['achievements'] = []
        
        # Сохраняем статистику перед проверкой достижений
        database.update_one('player_stats', {'user_id': user_id}, {'$set': stats}, upsert=True)
        
        # Проверяем достижения
        if check_achievements:
            try:
                game_result = {
                    'role': role,
                    'won': won,
                    'alive': is_alive
                }
                new_achievements = check_achievements(user_id, game_result, stats)
                
                # Выдаем новые достижения
                for achievement in new_achievements:
                    if award_achievement:
                        if award_achievement(user_id, achievement):
                            # Отправляем уведомление игроку
                            try:
                                reward_text = f"🎉 <b>НОВОЕ ДОСТИЖЕНИЕ!</b>\n\n"
                                reward_text += f"{achievement['icon']} <b>{achievement['name']}</b>\n"
                                reward_text += f"{achievement['description']}\n\n"
                                reward_text += f"🍭 Награда: +{achievement.get('reward_candies', 0)} конфет"
                                bot.send_message(user_id, reward_text, parse_mode='HTML')
                            except:
                                pass
            except Exception as e:
                print(f"Error checking achievements for user {user_id}: {e}")

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
    
    # Обновляем статистику игроков (включая ELO рейтинг)
    try:
        update_player_stats(game, reason)
        
        # Отправляем личные сообщения с изменением рейтинга
        for player in game['players']:
            user_id = player['id']
            stats = database.find_one('player_stats', {'user_id': user_id})
            if stats and 'elo_change' in stats:
                elo_change = stats.get('elo_change', 0)
                elo_rating = stats.get('elo_rating', 1000)
                if elo_change != 0:
                    change_emoji = "📈" if elo_change > 0 else "📉"
                    change_text = f"{change_emoji} <b>Изменение рейтинга: {elo_change:+d}</b>\n"
                    change_text += f"🏆 <b>Новый рейтинг: {elo_rating}</b>"
                    try:
                        bot.send_message(user_id, change_text, parse_mode='HTML')
                    except:
                        pass  # Игрок заблокировал бота или не может получать сообщения
    except Exception as e:
        print(f"Error updating player stats: {e}")
    
    database.delete_one('games', {'_id': game['_id']})

def start_game(chat_id, players, mode='full'):
    players_count = len(players)
    cards = []
    
    # --- БАЛАНСИРОВКА (TrueMafia стиль) ---
    # Базовый набор: мафия, дон, комиссар, сержант, доктор
    mafia_count = max(1, players_count // 3)
    cards = ['mafia'] * mafia_count
    if mafia_count > 1:
        cards.append('don')
    
    cards.extend(['commissar', 'sergeant', 'doctor'])
    
    # Специальные роли (добавляются в зависимости от количества игроков)
    special_roles = []
    
    if players_count >= 6:
        special_roles.extend(['mistress', 'lawyer'])
    if players_count >= 7:
        special_roles.append('bum')
    if players_count >= 8:
        special_roles.append('lucky')
    if players_count >= 9:
        special_roles.append('kamikaze')
    if players_count >= 10:
        special_roles.append('maniac')
    if players_count >= 11:
        special_roles.append('suicide')
    
    random.shuffle(special_roles)
    
    # Добавляем специальные роли
    while len(cards) < players_count and special_roles:
        cards.append(special_roles.pop(0))
    
    # Добиваем мирными
    while len(cards) < players_count:
        cards.append('peace')
            
    random.shuffle(cards)
    
    game_players = []
    for i, p in enumerate(players):
        p_obj = p.copy()
        p_obj['role'] = cards[i]
        p_obj['alive'] = True
        p_obj['pm_id'] = None
        p_obj['position'] = i + 1  # Позиция за столом
        p_obj['has_spoken'] = False  # Говорил ли в этот день
        p_obj['self_heal_used'] = False  # Использовал ли доктор самолечение
        p_obj['lawyer_client'] = None  # Подзащитный адвоката
        game_players.append(p_obj)

    game = {
        'game': 'mafia', 'mode': mode, 'chat': chat_id, 'stage': -4,
        'day_count': 0, 'players': game_players, 'cards': cards,
        'vote': {}, 'shots': [], 'heals': [], 'played': [], 
        'blocks': [], 'silenced': [],  # Для Любовницы
        'candidates': [],  # Кандидаты на голосование
        'first_night_done': False,  # Была ли первая ночь
        'mafia_met': False,  # Знакомилась ли мафия
        'last_word_player': None,  # Игрок с последним словом
        'best_move_player': None,  # Игрок с лучшим ходом
        'commissar_killed': False,  # Убит ли комиссар
        'current_speaker': 0,  # Текущий говорящий
        'speech_start_time': None,  # Время начала речи
        'night_count': 0,  # Счетчик ночей
        'missed_actions': {}  # Счетчик пропущенных действий для каждого игрока {user_id: count}
    }
    
    return database.insert_one('games', game), game