from bot import bot
import database
import lang

import re
from enum import Enum, auto

# ASCII-арт виселицы
stickman = [
    ('', '', ''),
    (' 0', '', ''),
    (' 0', ' |', ''),
    (' 0', '/|', ''),
    (' 0', '/|\\', ''),
    (' 0', '/|\\', '/'),
    (' 0', '/|\\', '/ \\')
]

class GameResult(Enum):
    WIN = auto()
    LOSE = auto()

def get_stats(game):
    """Подсчитывает статистику на основе текущего состояния игры."""
    # Приводим ключи к строкам, так как в JSON ключи всегда строки
    # game['names'] = {"123": "Vasya", "456": "Petya"}
    stats = {str(uid): {'name': name, 'right': 0, 'wrong': 0} for uid, name in game.get('names', {}).items()}
    
    # game['right'] = {"а": 123, "б": 456}
    # game['wrong'] = {"в": 123}
    for key in ('right', 'wrong'):
        data = game.get(key, {})
        for letter, user_id in data.items():
            str_id = str(user_id)
            if str_id in stats:
                stats[str_id][key] += 1
            else:
                # Если игрока нет в names (странно, но бывает), добавим заглушку
                stats[str_id] = {'name': 'Неизвестный', 'right': 0, 'wrong': 0}
                if key == 'right': stats[str_id]['right'] = 1
                else: stats[str_id]['wrong'] = 1
                
    return stats

def set_gallows(game, result, word_display, stats=None):
    """Обновляет сообщение с игровым полем."""
    if game.get('names'):
        if stats is None:
            stats = get_stats(game)
        # Сортировка: сначала по правильным ответам, потом по неправильным (меньше ошибок - выше)
        users = sorted(stats.values(), key=lambda s: (s['right'], -s['wrong']), reverse=True)
        players = '\n\n' + '\n'.join(f'{u["name"]}: ✔️{u["right"]} ❌{u["wrong"]}' for u in users)
    else:
        players = ''
    
    # Защита от выхода за пределы массива stickman
    wrong_count = len(game.get('wrong', {}))
    stickman_idx = min(wrong_count, len(stickman) - 1)
    
    # Формируем строку попыток (буквы)
    attempts_str = ', '.join(sorted(game.get('wrong', {}).keys()))

    bot.try_to_send_message( # Используем безопасный метод из bot.py
        chat_id=game['chat'],
        text=lang.gallows.format(
            result=result,
            word=word_display,
            attempts='\nПопытки: ' + attempts_str if attempts_str else '',
            players=players
        ) % stickman[stickman_idx],
        parse_mode='HTML'
        # Заменили edit на send, если старое сообщение слишком далеко. 
        # Но если нужно именно редактировать:
    )
    # ПРИМЕЧАНИЕ: В оригинале был edit_message_text. 
    # Если вы хотите именно редактировать, нужно ловить ошибку "message not modified".
    try:
        bot.edit_message_text(
            lang.gallows.format(
                result=result,
                word=word_display,
                attempts='\nПопытки: ' + attempts_str if attempts_str else '',
                players=players
            ) % stickman[stickman_idx],
            chat_id=game['chat'],
            message_id=game['message_id'],
            parse_mode='HTML'
        )
    except Exception:
        pass # Игнорируем ошибки редактирования (например, тот же текст)

def end_game(game, game_result):
    """Завершает игру, обновляет статистику и удаляет из БД."""
    target_word = game['word']
    
    if game_result == GameResult.WIN:
        result_text = f'Победа! Слово: <b>{target_word}</b>'
    else:
        result_text = f'Вы проиграли. Слово было: <b>{target_word}</b>'
        
    stats = get_stats(game)
    set_gallows(game, result_text, ' '.join(list(target_word)), stats=stats)
    
    # Атомарное обновление статистики игроков
    for uid, s in stats.items():
        increments = {
            'gallows.right': s['right'],
            'gallows.wrong': s['wrong'],
            'gallows.total': 1
        }
        if game_result == GameResult.WIN and s['right'] > 0:
            increments['gallows.win'] = 1
            
        database.update_one(
            'stats',
            {'id': int(uid), 'chat': game['chat']}, # uid приводим обратно к int для базы
            {
                '$inc': increments,
                '$set': {'name': s['name']} 
            },
            upsert=True
        )
        
    database.delete_one('games', {'_id': game['_id']})


def gallows_suggestion(suggestion, game, user, message_id):
    """Обрабатывает ход игрока."""
    
    # 1. Удаляем сообщение игрока, чтобы не засорять чат
    bot.safely_delete_message(chat_id=game['chat'], message_id=message_id)

    suggestion = suggestion.lower().strip()
    target_word = game['word'].lower()
    user_id = user['id']
    user_name = user['full_name'] # В боте обычно full_name
    
    # --- СЦЕНАРИЙ 1: Попытка угадать слово целиком ---
    if len(suggestion) > 1:
        # Экранируем слово для защиты от regex injection
        if re.search(r'\b{}\b'.format(re.escape(target_word)), suggestion, re.IGNORECASE):
            # Если угадал слово — засчитываем ему все неоткрытые буквы
            # Но чтобы не усложнять, просто считаем победу. 
            # Можно добавить ему очков бонусом.
            
            # Обновляем локально, чтобы в end_game статистика была верной
            # (Добавляем его в names)
            if 'names' not in game: game['names'] = {}
            game['names'][str(user_id)] = user_name
            
            # Засчитываем победу
            end_game(game, GameResult.WIN)
        return

    # --- СЦЕНАРИЙ 2: Буква ---
    
    # Проверка на валидность буквы (кириллица + ё)
    # Если вы хотите поддерживать и латиницу, расширьте условие.
    if not (len(suggestion) == 1 and (suggestion.isalpha())):
        return

    # Проверка на повтор
    if suggestion in game.get('wrong', {}) or suggestion in game.get('right', {}):
        # Можно отправить временное сообщение "Уже было", которое само удалится
        msg = bot.try_to_send_message(game['chat'], f'{user_name}, буква "{suggestion}" уже была!')
        # Тут можно запустить таймер на удаление, но это усложнит код.
        return

    # --- ЛОГИКА ХОДА ---
    
    # Сначала обновляем БД, чтобы избежать гонки данных, потом читаем обновленное?
    # Нет, MongoDB атомарна на уровне одного документа.
    
    is_correct = suggestion in target_word
    
    update_query = {
        '$set': {f'names.{user_id}': user_name}
    }
    
    if is_correct:
        update_query['$set'][f'right.{suggestion}'] = user_id
    else:
        update_query['$set'][f'wrong.{suggestion}'] = user_id

    # Выполняем обновление в базе и получаем обновленный документ
    game = database.find_one_and_update(
        'games',
        {'_id': game['_id']},
        update_query
    )
    
    # Если игры уже нет (кто-то другой выиграл миллисекундой раньше), выходим
    if not game:
        return

    # --- ПРОВЕРКА СОСТОЯНИЯ ПОСЛЕ ХОДА ---
    
    word_chars = list(target_word)
    right_chars = game.get('right', {})
    wrong_chars = game.get('wrong', {})
    
    # 1. Проверяем победу (все буквы открыты)
    if all(char in right_chars for char in word_chars):
        end_game(game, GameResult.WIN)
        return

    # 2. Проверяем поражение (слишком много ошибок)
    if len(wrong_chars) >= len(stickman) - 1:
        end_game(game, GameResult.LOSE)
        return

    # 3. Игра продолжается — обновляем табло
    word_in_underlines = []
    for ch in word_chars:
        if ch in right_chars:
            word_in_underlines.append(ch.upper())
        else:
            word_in_underlines.append('_')
            
    set_gallows(game, '', ' '.join(word_in_underlines))