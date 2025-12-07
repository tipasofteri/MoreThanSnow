import lang
from bot import bot
import database
from game import role_titles, stop_game
import random
from time import time, sleep
from collections import Counter
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiException
from settings import get_settings

stages = {}

def add_stage(number, time=None, delete=False):
    def decorator(func):
        stages[number] = {'time': time, 'func': func, 'delete': delete}
        return func
    return decorator

def safe_lang_get(key, default="..."):
    return getattr(lang, key, default)

def format_roles(game, show_roles=False, condition=lambda p: p.get('alive', True)):
    """Форматировать список ролей с учетом кастомизации"""
    result = []
    for i, p in enumerate(game['players']):
        if condition(p):
            name = p["name"]
            if show_roles:
                role_name = role_titles.get(p.get("role"), "?")
                # Применяем кастомизацию
                try:
                    from customization import format_role_name
                    role_name = format_role_name(role_name, p['id'], game.get('chat'))
                except ImportError:
                    pass  # Кастомизация недоступна, используем стандартное имя
                result.append(f'{i+1}. {name} - {role_name}')
            else:
                result.append(f'{i+1}. {name}')
    return '\n'.join(result)

def get_votes(game):
    """Формирует список голосования для отображения в чате."""
    votes = game.get('vote', {})
    if not votes:
        return "Пока никто не голосовал."
    
    # Группируем голоса: за кого -> кто голосовал
    vote_map = {}
    for voter_idx, target_idx in votes.items():
        target_idx = int(target_idx)
        if target_idx not in vote_map: 
            vote_map[target_idx] = []
        vote_map[target_idx].append(int(voter_idx))
    
    lines = []
    # Сортируем: сначала игроки (0+), потом воздержавшиеся (-1)
    for target_idx in sorted(vote_map.keys()):
        voter_indices = vote_map[target_idx]
        voter_names = [game['players'][v]['name'] for v in voter_indices if v < len(game['players'])]
        
        if target_idx < 0:
            # Это голоса "Воздержаться"
            lines.append(f"<b>😶 Воздержались</b>: {', '.join(voter_names)}")
        elif target_idx < len(game['players']):
            # Это голоса за игрока
            target_name = game['players'][target_idx]['name']
            lines.append(f"<b>{target_name}</b>: {', '.join(voter_names)}")
        
    return "\n".join(lines)

def update_timer(game):
    """Обновляет таймер в сообщении дня"""
    if 'message_id' not in game: 
        return
    
    remaining = int(game['next_stage_time'] - time())
    if remaining < 0: 
        remaining = 0
    
    time_str = f"{remaining // 60:02}:{remaining % 60:02}"
    
    text = None
    if game['stage'] == 0:  # День - обсуждение
        victim_text = ""
        if game['day_count'] > 0:
            dead = [p for p in game['players'] if not p.get('alive', True) and p.get('died_night', False)]
            if dead:
                victim = dead[-1]
                victim_idx = game['players'].index(victim) if victim in game['players'] else 0
                victim_pos = victim.get('position', victim_idx + 1)
                victim_text = lang.morning_victim.format(
                    victim_name=victim['name'],
                    victim_num=victim_pos
                )
            else:
                victim_text = lang.morning_peaceful
        else:
            victim_text = ""
        
        current_speaker_idx = game.get('current_speaker', 0)
        current_speaker = game['players'][current_speaker_idx] if current_speaker_idx < len(game['players']) else None
        
        # Показываем оставшееся время обсуждения и голоса
        text = f"⏱ <b>Обсуждение продолжается</b>\n\n"
        if victim_text:
            text += f"{victim_text}\n\n"
        text += f"⏰ Осталось времени: {time_str}\n\n"
        
        # Подсчитываем голоса для каждого игрока
        votes = game.get('vote', {})
        vote_map_ids = game.get('vote_map_ids', {})
        vote_counts = {}
        for user_id, target_idx in vote_map_ids.items():
            target_idx = int(target_idx)
            if target_idx >= 0 and target_idx < len(game['players']):
                vote_counts[target_idx] = vote_counts.get(target_idx, 0) + 1
        
        # Формируем список игроков с голосами
        players_list = []
        skipped = []
        for i, player in enumerate(game['players']):
            if not player.get('alive', True):
                continue
            votes_count = vote_counts.get(i, 0)
            snowmen = '⛄' * votes_count
            player_name = player.get('name', f'Игрок {i+1}')
            position = player.get('position', i + 1)
            players_list.append(f"{position}. {player_name}{snowmen}")
            if votes_count == 0:
                skipped.append(player_name)
        
        text += f"📋 <b>Живые игроки:</b>\n" + "\n".join(players_list)
        if skipped:
            text += f"\n\nПропустили: {', '.join(skipped)}"
    
    if text:
        try:
            bot.edit_message_text(
                text=text, 
                chat_id=game['chat'], 
                message_id=game['message_id'], 
                parse_mode='HTML'
            )
        except ApiException: 
            pass

def send_player_message(player, game, text, markup=None):
    sent = False
    if player.get('pm_id'):
        try:
            bot.edit_message_text(
                text=text,
                chat_id=player['id'],
                message_id=player['pm_id'],
                reply_markup=markup,
                parse_mode='HTML'
            )
            sent = True
        except ApiException:
            pass 
            
    if not sent:
        try:
            msg = bot.send_message(player['id'], text, reply_markup=markup, parse_mode='HTML')
            player_idx = next(i for i, p in enumerate(game['players']) if p['id'] == player['id'])
            database.update_one('games', {'_id': game['_id']}, {
                '$set': {f'players.{player_idx}.pm_id': msg.message_id}
            })
            return True
        except:
            return False 
    return True

def handle_night_stage(game, stage_num, role, callback_prefix, lang_key, 
                       exclude_self=True, custom_targets=None, custom_kb=None, 
                       group_message=None, extra_logic=None):
    """
    Универсальная функция для обработки ночных стадий.
    
    Args:
        game: Объект игры
        stage_num: Номер стадии
        role: Роль игрока или кортеж ролей для множественных игроков
        callback_prefix: Префикс для callback_data кнопок
        lang_key: Ключ из lang для текста сообщения
        exclude_self: Исключать ли самого игрока из списка целей
        custom_targets: Кастомная функция для получения целей
        custom_kb: Кастомная клавиатура (если нужна особая логика)
        group_message: Сообщение в группу (если нужно)
        extra_logic: Дополнительная логика после отправки сообщений
    """
    settings = get_settings(game['chat'])
    night_time = settings.get('night_time', 30)
    
    # Обновляем время стадии
    if stage_num in stages:
        stages[stage_num]['time'] = night_time
    
    # Получаем игроков с нужной ролью
    if isinstance(role, tuple):
        # Множественные роли (например, мафия и дон)
        players = [p for p in game['players'] if p['role'] in role and p.get('alive')]
    else:
        # Одна роль
        players = [p for p in game['players'] if p['role'] == role and p.get('alive')]
    
    if not players:
        go_to_next_stage(game)
        return
    
    blocks = game.get('blocks', [])
    
    # Получаем цели
    if custom_targets:
        targets = custom_targets(game, players)
    else:
        if exclude_self:
            targets = [(i, p) for i, p in enumerate(game['players']) 
                      if p.get('alive') and p['id'] not in [pl['id'] for pl in players]]
        else:
            targets = [(i, p) for i, p in enumerate(game['players']) if p.get('alive')]
    
    # Создаем клавиатуру
    if custom_kb:
        kb = custom_kb(game, targets, callback_prefix)
    else:
        kb = create_player_buttons(targets, callback_prefix, row_width=2)
    
    # Отправляем сообщения игрокам
    for player in players:
        if player['id'] not in blocks:
            text = getattr(lang, lang_key).format(time=night_time)
            send_player_message(player, game, text, kb)
        else:
            send_player_message(player, game, lang.action_blocked)
    
    # Отправляем сообщение в группу, если нужно
    if group_message:
        try:
            bot.send_message(game['chat'], group_message, parse_mode='HTML')
        except:
            pass
    
    # Дополнительная логика
    if extra_logic:
        extra_logic(game, players)

def create_player_buttons(targets, callback_prefix, row_width=2):
    """Создает кнопки с никами/юзернеймами игроков"""
    kb = InlineKeyboardMarkup(row_width=row_width)
    buttons = []
    
    for idx, p in targets:
        pos = p.get('position', idx + 1)
        username = p.get('username', '')
        name = p.get('name', f'Игрок {pos}')
        
        # Используем username если есть, иначе имя
        button_text = f"№{pos} @{username}" if username else f"№{pos} {name}"
        # Ограничиваем длину текста кнопки (Telegram ограничение ~64 символа, но лучше короче)
        if len(button_text) > 20:
            button_text = button_text[:17] + "..."
        
        buttons.append(InlineKeyboardButton(
            button_text,
            callback_data=f'{callback_prefix} {idx}'
        ))
    
    # Добавляем кнопки по row_width в ряд
    for i in range(0, len(buttons), row_width):
        row_buttons = buttons[i:i+row_width]
        kb.add(*row_buttons)
    
    return kb

def cleanup_missed_actions(game, expected_players, action_type='ночное действие', role_name=None):
    """
    Удаляет сообщения игроков, которые не сделали ход, и увеличивает счетчик пропущенных действий.
    Если игрок пропустил 2 действия подряд - автокик.
    """
    played_ids = set(game.get('played', []))
    missed_actions = game.get('missed_actions', {})
    kicked_players = []
    current_stage = game.get('stage', 0)
    
    for player in expected_players:
        user_id = player['id']
        if not player.get('alive', True):
            continue
        
        # Проверяем, была ли стадия для этой роли
        # Если игрок заблокирован, он не должен получать предупреждение
        if user_id in game.get('blocks', []):
            continue
        
        # Если игрок не сделал ход
        if user_id not in played_ids:
            # Удаляем сообщение с кнопками, если оно есть
            pm_id = player.get('pm_id')
            if pm_id:
                try:
                    bot.delete_message(user_id, pm_id)
                except:
                    pass
            
            # Отправляем сообщение в группу о пропущенном действии
            player_pos = player.get('position', game['players'].index(player) + 1)
            player_role = player.get('role', 'игрок')
            role_display = role_titles.get(player_role, 'Игрок')
            
            if role_name:
                try:
                    bot.send_message(
                        game['chat'],
                        f'😴 {role_display} №{player_pos} {player["name"]} сегодня проспал.',
                        parse_mode='HTML'
                    )
                except:
                    pass
            
            # Увеличиваем счетчик пропущенных действий
            current_count = missed_actions.get(user_id, 0)
            new_count = current_count + 1
            missed_actions[user_id] = new_count
            
            # Если пропустил 2 действия подряд - автокик
            if new_count >= 2:
                player['alive'] = False
                kicked_players.append(player)
                try:
                    bot.send_message(
                        game['chat'],
                        f'🚫 Игрок №{player_pos} {player["name"]} исключен из игры за пропуск 2 действий подряд.',
                        parse_mode='HTML'
                    )
                except:
                    pass
            elif new_count == 1:
                # Первое предупреждение
                try:
                    bot.send_message(
                        user_id,
                        f'⚠️ Внимание! Ты пропустил {action_type}. При следующем пропуске будешь исключен из игры.',
                        parse_mode='HTML'
                    )
                except:
                    pass
        else:
            # Игрок сделал ход - сбрасываем счетчик пропущенных действий
            if user_id in missed_actions:
                missed_actions[user_id] = 0
    
    # Обновляем missed_actions в базе данных
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {'missed_actions': missed_actions, 'players': game['players']}
    })
    
    return kicked_players

def send_vote_buttons(player, game):
    """Отправляет игроку сообщение с кнопками для голосования во время обсуждения"""
    player_idx = next(i for i, p in enumerate(game['players']) if p['id'] == player['id'])
    
    # Получаем список живых игроков, исключая самого игрока
    alive_players = [
        (idx, p) for idx, p in enumerate(game['players']) 
        if p['alive'] and idx != player_idx
    ]
    
    if not alive_players:
        return
    
    # Формируем текст сообщения
    text = "🗳 <b>Голосование во время обсуждения</b>\n\n"
    text += "Выберите игрока, против которого хотите проголосовать:\n\n"
    text += "💡 Голоса отображаются в сообщении обсуждения (⛄)\n"
    text += "💡 Можно изменить свой голос в любой момент\n\n"
    
    # Формируем список игроков для текста
    players_list = []
    for idx, p in alive_players:
        pos = p.get('position', idx + 1)
        username = p.get('username', '')
        name = p.get('name', f'Игрок {pos}')
        if username:
            players_list.append(f"№{pos} @{username} ({name})")
        else:
            players_list.append(f"№{pos} {name}")
    
    text += "\n".join(players_list)
    
    # Создаем кнопки для голосования
    kb = create_player_buttons(alive_players, 'vote_discussion', row_width=2)
    
    # Отправляем сообщение
    try:
        msg = bot.send_message(player['id'], text, reply_markup=kb, parse_mode='HTML')
        database.update_one('games', {'_id': game['_id']}, {
            '$set': {f'players.{player_idx}.vote_pm_id': msg.message_id}
        })
    except Exception as e:
        pass  # Игнорируем ошибки отправки в ЛС

def send_candidate_buttons(player, game):
    """Отправляет игроку сообщение с кнопками для выбора кандидата на голосование
    (теперь использует send_vote_buttons для совместимости)"""
    send_vote_buttons(player, game)

# Маппинг стадий на роли и их конфигурацию
STAGE_ROLE_CONFIG = {
    4: {'roles': ('mafia', 'don'), 'multi': True, 'check_key': None},  # Мафия
    5: {'roles': ('don',), 'multi': False, 'check_key': 'don_check'},  # Дон
    6: {'roles': ('commissar',), 'multi': False, 'check_key': 'commissar_action'},  # Комиссар
    7: {'roles': None, 'multi': False, 'check_key': None, 'auto': True},  # Сержант (автоматически)
    8: {'roles': ('doctor',), 'multi': False, 'check_key': 'heals'},  # Доктор
    9: {'roles': ('maniac',), 'multi': False, 'check_key': 'maniac_shot'},  # Маньяк
    10: {'roles': ('mistress',), 'multi': False, 'check_key': None},  # Любовница
    11: {'roles': ('bum',), 'multi': False, 'check_key': 'bum_witness'},  # Бомж
    12: {'roles': ('bum',), 'multi': False, 'check_key': 'bum_witness'},  # Бомж (в cleanup)
}

def get_expected_players_for_stage(game, stage):
    """Получить список игроков, которые должны выполнить действие на данной стадии"""
    config = STAGE_ROLE_CONFIG.get(stage)
    if not config:
        return []
    
    if config.get('auto'):
        return []
    
    roles = config.get('roles')
    if not roles:
        return []
    
    blocks = game.get('blocks', [])
    players = game['players']
    
    if config.get('multi'):
        # Для мафии - все мафия и дон
        expected = [p for p in players if p['role'] in roles and p.get('alive') and p['id'] not in blocks]
    else:
        # Для остальных - один игрок
        player = next((p for p in players if p['role'] in roles and p.get('alive')), None)
        if player and player['id'] not in blocks:
            # Специальная проверка для адвоката
            if stage == 11 and player.get('lawyer_client'):
                return []
            return [player]
        return []
    
    return expected

def check_night_stage_complete(game):
    """Проверяет, все ли роли выполнили свои действия для текущей ночной стадии.
    Если да - автоматически переходит к следующей стадии."""
    current_stage = game.get('stage')
    
    # Проверяем только ночные стадии (4-11)
    if current_stage not in STAGE_ROLE_CONFIG:
        return False
    
    config = STAGE_ROLE_CONFIG.get(current_stage)
    if config.get('auto'):
        # Автоматические стадии всегда завершены
        go_to_next_stage(game)
        return True
    
    played = set(game.get('played', []))
    expected_players = get_expected_players_for_stage(game, current_stage)
    
    if not expected_players:
        # Нет игроков для этой стадии - завершена
        go_to_next_stage(game)
        return True
    
    # Проверяем, все ли выполнили действие
    expected_ids = {p['id'] for p in expected_players}
    all_played = expected_ids.issubset(played)
    
    # Дополнительная проверка по ключам в game
    check_key = config.get('check_key')
    if check_key and not all_played:
        if check_key == 'heals':
            all_played = all_played or len(game.get('heals', [])) > 0
        else:
            all_played = all_played or game.get(check_key) is not None
    
    if all_played:
        go_to_next_stage(game)
        return True
    
    return False

def go_to_next_stage(game, inc=1, max_recursion=10):
    """Переход к следующей стадии с защитой от бесконечной рекурсии"""
    if max_recursion <= 0:
        print(f"ERROR: Maximum recursion depth reached in go_to_next_stage. Current stage: {game.get('stage')}")
        return game
    
    database.delete_many('polls', {'chat': game['chat']})
    
    current_stage = game['stage']
    # Убеждаемся, что current_stage - это число
    if isinstance(current_stage, str):
        try:
            current_stage = int(current_stage)
        except:
            current_stage = 0
    
    # После стадии 12 (утро) возвращаемся к стадии 0 (день)
    if current_stage >= 12:
        stage_number = 0
        database.update_one('games', {'_id': game['_id']}, {'$inc': {'day_count': 1}})
    elif current_stage == -3:
        # После первой ночи переходим к дню (стадия 0)
        stage_number = 0
    elif current_stage == 0:
        # После обсуждения переходим к результатам голосования (стадия 2)
        stage_number = 2
    elif current_stage == 13:
        # После дополнительного обсуждения при ничьей - повторное голосование
        # Переходим к стадии 2 (результаты голосования) для повторного голосования
        stage_number = 2
    elif current_stage == 14:
        # После последнего слова - проверяем победу и переходим к ночи
        alive = [p for p in game['players'] if p['alive']]
        mafia = [p for p in alive if p['role'] in ('mafia', 'don')]
        maniac = [p for p in alive if p['role'] == 'maniac']
        
        if not mafia and not maniac:
            return stop_game(game, 'Мирные победили!')
        if len(mafia) >= len(alive) - len(mafia):
            return stop_game(game, 'Мафия победила!')
        if maniac and len(maniac) >= len(alive) - 1:
            return stop_game(game, 'Маньяк победил!')
        
        # Игра продолжается - переходим к ночи
        stage_number = 3  # Начало ночи
    elif current_stage == 15:
        # После подтверждения голосования - если не подтвердили, возвращаемся к обсуждению
        # Если подтвердили - исключаем игрока (переход к стадии 14)
        vote_confirmation = game.get('vote_confirmation')
        if vote_confirmation is None:
            # Не подтвердили - возвращаемся к обсуждению
            stage_number = 0
        else:
            # Подтвердили - переходим к последнему слову
            stage_number = 14
    else:
        stage_number = current_stage + inc
        # Защита: если пытаемся перейти к несуществующей стадии 1, переходим к стадии 2
        if stage_number == 1:
            stage_number = 2

    stage = stages.get(stage_number)
    if not stage:
        print(f"ERROR: Stage {stage_number} not found. Current stage: {current_stage}, inc: {inc}")
        print(f"Available stages: {sorted(stages.keys())}")
        # Пытаемся найти следующую доступную стадию
        for next_stage in range(stage_number, stage_number + 20):
            if stages.get(next_stage):
                print(f"Found alternative stage: {next_stage}")
                stage_number = next_stage
                stage = stages.get(stage_number)
                break
        
        if not stage:
            print(f"FATAL ERROR: No stage found after {stage_number}. Stopping game.")
            # Останавливаем игру, чтобы избежать бесконечной рекурсии
            return game

    # Перед переходом к следующей стадии проверяем пропущенные действия
    # для текущей ночной стадии (4-12)
    if current_stage in STAGE_ROLE_CONFIG:
        # Определяем, какие игроки должны были сделать ход
        expected_players = get_expected_players_for_stage(game, current_stage)
        
        # Получаем название роли для сообщения
        role_names = {
            4: 'Мафия', 5: 'Дон', 6: 'Комиссар', 7: None,
            8: 'Доктор', 9: 'Маньяк', 10: 'Любовница', 11: 'Адвокат', 12: 'Бомж'
        }
        role_name = role_names.get(current_stage)
        
        # Очищаем пропущенные действия
        if expected_players and role_name:
            cleanup_missed_actions(game, expected_players, 'ночное действие', role_name)
            # Обновляем игру после cleanup
            game = database.find_one('games', {'_id': game['_id']})
    
    # Получаем время из настроек для соответствующих стадий
    settings = get_settings(game['chat'])
    if stage_number == 0:
        # Обсуждение
        discussion_time = settings.get('discussion_time', 300)
        # Применяем множитель времени, если есть событие замедления времени
        multiplier = game.get('day_duration_multiplier', 1)
        discussion_time = int(discussion_time * multiplier)
        # Сбрасываем множитель после использования
        if multiplier > 1:
            database.update_one('games', {'_id': game['_id']}, {'$set': {'day_duration_multiplier': 1}})
        stage['time'] = discussion_time
    # Стадия 1 (голосование) больше не используется - голосуем во время обсуждения
    elif stage_number in [4, 5, 6, 7, 8, 9, 10, 11]:
        # Ночные действия (мафия, дон, комиссар, доктор, маньяк, любовница, адвокат, бомж)
        night_time = settings.get('night_time', 30)
        stage['time'] = night_time
    
    duration = stage['time'](game) if callable(stage['time']) else stage['time']
    
    updates = {
        'stage': stage_number,
        'time': time() + duration,
        'next_stage_time': time() + duration,
        'played': []
    }
    
    # Сброс ночных действий
    if stage_number == 3:  # Начало ночи
        # Применяем блокировки от метели
        blizzard_blocked = game.get('blizzard_blocked', [])
        if blizzard_blocked:
            # Добавляем заблокированных игроков в blocks
            current_blocks = game.get('blocks', [])
            for blocked_id in blizzard_blocked:
                if blocked_id not in current_blocks:
                    current_blocks.append(blocked_id)
            updates['blocks'] = current_blocks
            # Очищаем список заблокированных метелью
            updates['blizzard_blocked'] = []
        else:
            # Если нет блокировок от метели, сбрасываем blocks
            updates['blocks'] = []
        
        updates.update({
            'shots': [], 'heals': [], 'played': [],
            'commissar_action': None, 'commissar_target': None,
            'don_check': None, 'lawyer_client': None,
            'bum_witness': None, 'maniac_shot': None
        })
    
    database.update_one('games', {'_id': game['_id']}, {'$set': updates})
    new_game = database.find_one('games', {'_id': game['_id']})
    
    try: 
        stage['func'](new_game)
    except Exception as e: 
        print(f"Error in stage {stage_number}: {e}")
        import traceback
        traceback.print_exc()
    
    return new_game

# --- СТАДИИ ---

@add_stage(-4, 60)
def lobby(game): pass

# ПЕРВАЯ НОЧЬ - знакомство мафии
@add_stage(-3, 60)
def first_night(game):
    # Первая ночь уже прошла, переходим к дню
    if game.get('mafia_met'):
        go_to_next_stage(game)
        return
    
    mafiosi = [p for p in game['players'] if p['role'] in ('mafia', 'don')]
    if not mafiosi:
        database.update_one('games', {'_id': game['_id']}, {'$set': {'mafia_met': True}})
        go_to_next_stage(game)
        return
    
    mafia_team = '\n'.join([f'№{p.get("position", game["players"].index(p) + 1)} {p["name"]}' for p in mafiosi])
    
    for p in mafiosi:
        text = lang.first_night_mafia.format(mafia_team=mafia_team)
        text += '\n\n💬 <b>Вы можете общаться между собой!</b>\n'
        text += 'Напишите боту в личные сообщения, и ваше сообщение будет переслано всем мафии.\n'
        text += 'Используйте команду: <code>/mafia &lt;сообщение&gt;</code>'
        send_player_message(p, game, text)
    
    # Сохраняем список ID мафии для общения
    mafia_ids = [p['id'] for p in mafiosi]
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {'mafia_met': True, 'mafia_chat_ids': mafia_ids}
    })
    
    # После минуты отправляем сообщение о завершении
    bot.send_message(game['chat'], lang.first_night_done, parse_mode='HTML')

# ДЕНЬ - обсуждение (свободное общение)
@add_stage(0, None)  # Время будет браться из настроек динамически
def discussion(game):
    # Получаем настройки для этого чата
    settings = get_settings(game['chat'])
    discussion_time = settings.get('discussion_time', 300)  # По умолчанию 5 минут
    
    # Обновляем время стадии в словаре stages
    if 0 in stages:
        stages[0]['time'] = discussion_time
    # Сбрасываем кандидатов и голоса (теперь голосуем во время обсуждения)
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {'candidates': [], 'vote': {}, 'vote_map_ids': {}, 'vote_confirmation': None}
    })
    
    # Определяем живых игроков
    alive_players = [p for p in game['players'] if p['alive']]
    if not alive_players:
        return stop_game(game, 'Все игроки мертвы!')
    
    # Убеждаемся, что у всех игроков есть поле position
    for i, p in enumerate(game['players']):
        if 'position' not in p:
            p['position'] = i + 1
    database.update_one('games', {'_id': game['_id']}, {'$set': {'players': game['players']}})
    
    victim_text = ""
    if game['day_count'] > 0:
        # Проверяем, был ли кто-то убит ночью
        dead = [p for p in game['players'] if not p.get('alive', True) and p.get('died_night', False)]
        if dead:
            victim = dead[-1]
            victim_pos = victim.get('position', game['players'].index(victim) + 1)
            victim_text = lang.morning_victim.format(
                victim_name=victim['name'],
                victim_num=victim_pos
            )
        else:
            victim_text = lang.morning_peaceful
    
    # Сообщение о начале свободного обсуждения
    msg = f"🌅 <b>День {game['day_count']}</b>\n\n"
    if victim_text:
        msg += f"{victim_text}\n\n"
    msg += f"⏱ <b>Обсуждение начинается!</b>\n\n"
    msg += f"💬 <b>Свободное общение</b> - все игроки могут говорить одновременно.\n"
    msg += f"⏰ У вас есть {discussion_time // 60} минут на обсуждение.\n\n"
    msg += f"📋 <b>Живые игроки:</b>\n{format_roles(game)}\n\n"
    msg += f"💡 Используйте кнопки в личных сообщениях бота, чтобы выставить игрока на голосование."
    
    sent = bot.send_message(game['chat'], msg, parse_mode='HTML')
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {'message_id': sent.message_id}
    })
    
    # Отправляем всем игрокам сообщение с кнопками для голосования
    for player in alive_players:
        send_vote_buttons(player, game)

# ГОЛОСОВАНИЕ (теперь не используется, голосуем во время обсуждения)
# Стадия 1 оставлена для совместимости, но теперь сразу переходим к результатам

# РЕЗУЛЬТАТЫ ГОЛОСОВАНИЯ
@add_stage(2, 10)
def vote_results(game):
    votes = game.get('vote', {})
    vote_map_ids = game.get('vote_map_ids', {})
    
    # Удаляем сообщения с кнопками голосования для тех, кто не проголосовал
    alive_players = [p for p in game['players'] if p.get('alive', True)]
    for player in alive_players:
        if player.get('id') not in vote_map_ids and player.get('vote_pm_id'):
            try:
                bot.delete_message(player['id'], player['vote_pm_id'])
            except:
                pass
    
    # Удаляем кнопки из сообщения обсуждения
    try:
        if game.get('message_id'):
            bot.edit_message_reply_markup(
                game['chat'],
                game['message_id'],
                reply_markup=None
            )
    except:
        pass
    
    if not vote_map_ids:
        bot.send_message(game['chat'], lang.vote_result_nobody, parse_mode='HTML')
        go_to_next_stage(game)
        return
    
    # Подсчитываем голоса (используем vote_map_ids для подсчета)
    vote_counts = {}
    for user_id, target_idx in vote_map_ids.items():
        target_idx = int(target_idx)
        if target_idx >= 0 and target_idx < len(game['players']):
            vote_counts[target_idx] = vote_counts.get(target_idx, 0) + 1
    
    if not vote_counts:
        bot.send_message(game['chat'], lang.vote_result_nobody, parse_mode='HTML')
        go_to_next_stage(game)
        return
    
    # Находим победителя (игрока с наибольшим количеством голосов)
    max_votes = max(vote_counts.values())
    winners = [idx for idx, count in vote_counts.items() if count == max_votes]
    
    # Проверка на ничью
    vote_tie_count = game.get('vote_tie_count', 0)
    if len(winners) > 1:
        # Если это уже повторное голосование и снова ничья - ставим вопрос о выбывании всех
        if vote_tie_count > 0:
            tied_names = [f'№{game["players"][idx].get("position", idx + 1)} {game["players"][idx]["name"]}' for idx in winners]
            bot.send_message(game['chat'], 
                f'⚖️ <b>Снова ничья!</b>\n\n'
                f'Кандидаты: {", ".join(tied_names)}\n\n'
                f'Ставится вопрос: "Кто за то, чтобы все голосуемые игроки покинули стол?"\n'
                f'Голосуйте: <b>ДА</b> - все покидают, <b>НЕТ</b> - все остаются.',
                parse_mode='HTML'
            )
            # Упрощенно: если большинство за выбывание - все покидают, иначе остаются
            # В реальной игре это отдельное голосование, здесь упрощаем
            # Все связанные игроки покидают игру
            for idx in winners:
                if idx < len(game['players']):
                    game['players'][idx]['alive'] = False
                    # Сохраняем для последнего слова
                    database.update_one('games', {'_id': game['_id']}, {
                        '$set': {'players': game['players'], 'vote_tie': None, 'vote_tie_count': 0, 'last_word_player': idx}
                    })
            # Переходим к последнему слову для всех связанных
            database.update_one('games', {'_id': game['_id']}, {
                '$set': {'stage': 14, 'next_stage_time': time() + 60}
            })
            return
        else:
            # Первая ничья - дополнительные 30 секунд на обсуждение, затем повторное голосование
            tied_names = [f'№{game["players"][idx].get("position", idx + 1)} {game["players"][idx]["name"]}' for idx in winners]
            bot.send_message(game['chat'], lang.vote_tie.format(candidates=', '.join(tied_names)) if hasattr(lang, 'vote_tie') and '{candidates}' in lang.vote_tie else f'⚖️ <b>Ничья!</b>\n\nКандидаты: {", ".join(tied_names)}', parse_mode='HTML')
            
            # Сохраняем информацию о ничьей для повторного голосования
            database.update_one('games', {'_id': game['_id']}, {
                '$set': {'vote_tie': winners, 'vote_tie_count': 1, 'candidates': winners}
            })
            
            # Переходим к стадии дополнительного обсуждения (30 секунд)
            database.update_one('games', {'_id': game['_id']}, {
                '$set': {'stage': 13, 'next_stage_time': time() + 30}
            })
            return
    
    # Нет ничьей - определяем победителя
    winner_idx = winners[0]
    victim = game['players'][winner_idx]
    victim['alive'] = False
    
    # Камикадзе забирает с собой
    if victim['role'] == 'kamikaze':
        voters = [int(v_id) for v_id, t_idx in votes.items() if int(t_idx) == winner_idx]
        if voters:
            boom_target_idx = random.choice(voters)
            if boom_target_idx < len(game['players']):
                game['players'][boom_target_idx]['alive'] = False
                bot.send_message(game['chat'], lang.kamikaze_boom.format(
                    name=game['players'][boom_target_idx]['name']
                ), parse_mode='HTML')
    
    victim_pos = victim.get('position', winner_idx + 1)
    bot.send_message(game['chat'], lang.vote_result_jail.format(
        criminal_name=victim['name'],
        criminal_num=victim_pos
    ), parse_mode='HTML')
    
    # Сохраняем информацию о жертве для последнего слова
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {'players': game['players'], 'last_word_player': winner_idx}
    })
    
    # Переходим к стадии последнего слова
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {'stage': 14, 'next_stage_time': time() + 60}  # 1 минута на последнее слово
    })

# НОЧЬ
@add_stage(3, 5)
def night_start(game):
    game['night_count'] = game.get('night_count', 0) + 1
    database.update_one('games', {'_id': game['_id']}, {'$inc': {'night_count': 1}})
    bot.send_message(game['chat'], lang.night_start, parse_mode='HTML')

# МАФИЯ СТРЕЛЯЕТ
@add_stage(4, None)  # Время будет браться из настроек динамически
def mafia_stage(game):
    settings = get_settings(game['chat'])
    night_time = settings.get('night_time', 30)
    
    if 4 in stages:
        stages[4]['time'] = night_time
    
    mafiosi = [p for p in game['players'] if p['role'] in ('mafia', 'don') and p.get('alive')]
    if not mafiosi:
        go_to_next_stage(game)
        return
    
    targets = [(i, p) for i, p in enumerate(game['players']) if p.get('alive')]
    kb = create_player_buttons(targets, 'shot', row_width=2)
    
    blocks = game.get('blocks', [])
    for p in mafiosi:
        if p['id'] not in blocks:
            team = ", ".join([m['name'] for m in mafiosi if m['id'] != p['id']])
            text = lang.mafia_pm.format(time=night_time, mafia_team=team or "Ты один")
            send_player_message(p, game, text, kb)
        else:
            send_player_message(p, game, lang.action_blocked)

# ДОН ИЩЕТ КОМИССАРА
@add_stage(5, 10)
def don_stage(game):
    def don_targets(game, players):
        return [(i, p) for i, p in enumerate(game['players']) 
                if p.get('alive') and p['role'] != 'don']
    
    handle_night_stage(
        game, 5, 'don', 'don_check', 'don_pm',
        exclude_self=True, custom_targets=don_targets,
        group_message=lang.don_turn_group
    )

# КОМИССАР ДЕЙСТВУЕТ
@add_stage(6, None)  # Время будет браться из настроек динамически
def commissar_stage(game):
    # Получаем настройки для этого чата
    settings = get_settings(game['chat'])
    night_time = settings.get('night_time', 30)
    
    # Обновляем время стадии в словаре stages
    if 6 in stages:
        stages[6]['time'] = night_time
    
    commissar = next((p for p in game['players'] if p['role'] == 'commissar' and p['alive']), None)
    if not commissar:
        go_to_next_stage(game)
        return
    
    if commissar['id'] in game.get('blocks', []):
        send_player_message(commissar, game, lang.action_blocked)
        go_to_next_stage(game)
        return
    
    kb = InlineKeyboardMarkup(row_width=2)
    targets = [(i, p) for i, p in enumerate(game['players']) if p['alive'] and p['id'] != commissar['id']]
    
    # Проверяем, первая ли это ночь
    # Если night_count == 0 - это первая ночь после первого дня, комиссар может только проверять
    is_first_night = game.get('night_count', 0) == 0
    
    # Кнопки: проверить или убить (с никами)
    for i, p in targets:
        pos = p.get('position', i + 1)
        username = p.get('username', '')
        name = p.get('name', f'Игрок {pos}')
        button_text = f"№{pos} @{username}" if username else f"№{pos} {name}"
        if len(button_text) > 15:
            button_text = button_text[:12] + "..."
        
        kb.add(
            InlineKeyboardButton(f'Проверить {button_text}', callback_data=f'commissar_check {i}')
        )
        # В первую ночь комиссар не может убивать
        if not is_first_night:
            kb.add(
                InlineKeyboardButton(f'Убить {button_text}', callback_data=f'commissar_kill {i}')
            )
    
    # В первую ночь комиссар может только проверять
    if is_first_night:
        text = lang.commissar_pm.format(time=night_time)
        text += '\n\n⚠️ <b>Первая ночь:</b> Вы можете только проверять игроков, убийство недоступно.'
    else:
        text = lang.commissar_pm.format(time=night_time)
    
    send_player_message(commissar, game, text, kb)
    bot.send_message(game['chat'], lang.commissar_turn_group, parse_mode='HTML')
    
    # Сержант узнаёт о проверке
    sergeant = next((p for p in game['players'] if p['role'] == 'sergeant' and p['alive']), None)
    if sergeant:
        bot.send_message(sergeant['id'], '👮 Комиссар проснулся. Ты узнаешь о его действии.', parse_mode='HTML')

# ДОКТОР ЛЕЧИТ
@add_stage(7, None)  # Время будет браться из настроек динамически
def doctor_stage(game):
    handle_night_stage(game, 7, 'doctor', 'doctor', 'doctor_pm', exclude_self=False)

# МАНЬЯК УБИВАЕТ
@add_stage(8, None)  # Время будет браться из настроек динамически
def maniac_stage(game):
    handle_night_stage(game, 8, 'maniac', 'maniac', 'maniac_pm', exclude_self=True)

# ЛЮБОВНИЦА БЛОКИРУЕТ
@add_stage(9, None)  # Время будет браться из настроек динамически
def mistress_stage(game):
    handle_night_stage(game, 9, 'mistress', 'mistress', 'mistress_pm', exclude_self=True)

# АДВОКАТ ВЫБИРАЕТ ПОДЗАЩИТНОГО
@add_stage(10, None)  # Время будет браться из настроек динамически
def lawyer_stage(game):
    lawyer = next((p for p in game['players'] if p['role'] == 'lawyer' and p.get('alive')), None)
    if lawyer and lawyer.get('lawyer_client'):
        go_to_next_stage(game)  # Уже выбрал
        return
    
    handle_night_stage(game, 10, 'lawyer', 'lawyer', 'lawyer_pm', exclude_self=True)

# БОМЖ СЛЕДИТ
@add_stage(11, None)  # Время будет браться из настроек динамически
def bum_stage(game):
    handle_night_stage(game, 11, 'bum', 'bum', 'bum_pm', exclude_self=True)

# УТРО - РЕЗУЛЬТАТЫ НОЧИ
@add_stage(12, 20)
def morning_results(game):
    dead = []
    
    # Выстрелы мафии
    if game.get('shots'):
        target_idx = int(Counter(game['shots']).most_common(1)[0][0])
        is_healed = target_idx in [int(x) for x in game.get('heals', [])]
        is_lucky = game['players'][target_idx]['role'] == 'lucky' and random.random() < 0.5
        
        if not is_healed and not is_lucky:
            dead.append(target_idx)
        elif is_lucky:
            lucky_pos = game["players"][target_idx].get("position", target_idx + 1)
            bot.send_message(game['chat'], f'🍀 Игрок №{lucky_pos} {game["players"][target_idx]["name"]} выжил благодаря удаче!', parse_mode='HTML')
    
    # Выстрел маньяка
    if game.get('maniac_shot') is not None:
        maniac_target = int(game['maniac_shot'])
        is_healed = maniac_target in [int(x) for x in game.get('heals', [])]
        is_lucky = game['players'][maniac_target]['role'] == 'lucky' and random.random() < 0.5
        
        if not is_healed and not is_lucky:
            dead.append(maniac_target)
    
    # Убийство комиссара
    if game.get('commissar_action') == 'kill' and game.get('commissar_target') is not None:
        kill_target = int(game['commissar_target'])
        is_healed = kill_target in [int(x) for x in game.get('heals', [])]
        if not is_healed:
            dead.append(kill_target)
            kill_target_pos = game['players'][kill_target].get('position', kill_target + 1)
            bot.send_message(game['chat'], lang.commissar_kill_result.format(target_num=kill_target_pos), parse_mode='HTML')
    
    # Обрабатываем смерти
    for idx in set(dead):
        p = game['players'][idx]
        p['alive'] = False
        p['died_night'] = True
        
        # Если убит комиссар, сержант становится комиссаром
        if p['role'] == 'commissar':
            sergeant = next((s for s in game['players'] if s['role'] == 'sergeant' and s['alive']), None)
            if sergeant:
                sergeant['role'] = 'commissar'
                bot.send_message(sergeant['id'], '👮 Комиссар погиб! Ты становишься новым Комиссаром.', parse_mode='HTML')
        
        # Если убит дон, мафия выбирает нового
        if p['role'] == 'don':
            mafia = next((m for m in game['players'] if m['role'] == 'mafia' and m['alive']), None)
            if mafia:
                mafia['role'] = 'don'
                bot.send_message(mafia['id'], '🎩 Дон погиб! Ты становишься новым Доном.', parse_mode='HTML')
        
        victim_pos = p.get('position', idx + 1)
        bot.send_message(game['chat'], lang.morning_victim.format(
            victim_name=p['name'],
            victim_num=victim_pos
        ), parse_mode='HTML')
        
        # Лучший ход (только если не первая ночь и не было двойного голосования)
        if game['night_count'] > 1 and game['day_count'] > 0:
            if len([c for c in game.get('candidates', [])]) < 2:
                database.update_one('games', {'_id': game['_id']}, {'$set': {'best_move_player': idx}})
                text = lang.best_move_prompt.format(
                    player_num=victim_pos,
                    player_name=p['name']
                )
                bot.send_message(p['id'], text, parse_mode='HTML')
    
    if not dead:
        bot.send_message(game['chat'], lang.morning_peaceful, parse_mode='HTML')
    
    # Информация бомжу
    if game.get('bum_witness'):
        bum = next((p for p in game['players'] if p['role'] == 'bum' and p['alive']), None)
        if bum and game.get('bum_witness'):
            witness_info = game['bum_witness']
            source_pos = game['players'][witness_info['source']].get('position', witness_info['source'] + 1)
            target_pos = game['players'][witness_info['target']].get('position', witness_info['target'] + 1)
            bot.send_message(bum['id'], lang.bum_witness.format(
                source_num=source_pos,
                target_num=target_pos
            ), parse_mode='HTML')
    
    database.update_one('games', {'_id': game['_id']}, {'$set': {'players': game['players']}})
    
    # Проверка победы
    alive = [p for p in game['players'] if p['alive']]
    mafia = [p for p in alive if p['role'] in ('mafia', 'don')]
    maniac = [p for p in alive if p['role'] == 'maniac']
    
    if not mafia and not maniac:
        return stop_game(game, 'Мирные победили!')
    if len(mafia) >= len(alive) - len(mafia):
        return stop_game(game, 'Мафия победила!')
    if maniac and len(maniac) >= len(alive) - 1:
        return stop_game(game, 'Маньяк победил!')
    
    go_to_next_stage(game)

# ДОПОЛНИТЕЛЬНОЕ ОБСУЖДЕНИЕ ПРИ НИЧЬЕЙ
@add_stage(13, 30)
def vote_tie_discussion(game):
    """Дополнительные 30 секунд обсуждения при ничьей"""
    tied = game.get('vote_tie', [])
    if not tied:
        go_to_next_stage(game)
        return
    
    tied_names = [f'№{game["players"][idx].get("position", idx + 1)} {game["players"][idx]["name"]}' for idx in tied]
    bot.send_message(game['chat'], 
        f'⚖️ <b>Ничья!</b>\n\n'
        f'Кандидаты: {", ".join(tied_names)}\n\n'
        f'⏰ Дополнительные 30 секунд на обсуждение, затем повторное голосование.',
        parse_mode='HTML'
    )

# ПОСЛЕДНЕЕ СЛОВО
@add_stage(14, 60)
def last_word_stage(game):
    """Стадия последнего слова для покинувшего игру"""
    last_word_idx = game.get('last_word_player')
    if last_word_idx is None:
        # Проверяем победу и переходим к ночи
        alive = [p for p in game['players'] if p['alive']]
        mafia = [p for p in alive if p['role'] in ('mafia', 'don')]
        maniac = [p for p in alive if p['role'] == 'maniac']
        
        if not mafia and not maniac:
            return stop_game(game, 'Мирные победили!')
        if len(mafia) >= len(alive) - len(mafia):
            return stop_game(game, 'Мафия победила!')
        if maniac and len(maniac) >= len(alive) - 1:
            return stop_game(game, 'Маньяк победил!')
        
        go_to_next_stage(game)
        return
    
    victim = game['players'][last_word_idx]
    victim_pos = victim.get('position', last_word_idx + 1)
    
    bot.send_message(game['chat'], lang.last_word_prompt.format(
        player_num=victim_pos,
        player_name=victim['name']
    ), parse_mode='HTML')
    
    # После минуты проверяем победу и переходим к ночи
    database.update_one('games', {'_id': game['_id']}, {'$set': {'last_word_player': None}})