import config
from bot import bot
import database

import re
import random
from os.path import getsize

# Используем встроенный open вместо codecs (в Python 3 это стандарт)
# Проверяем, существует ли файл, чтобы бот не падал при старте
try:
    BASE_SIZE = getsize(config.WORD_BASE)
except OSError:
    print(f"Warning: Word base file '{config.WORD_BASE}' not found!")
    BASE_SIZE = 0

def get_word():
    """Получает случайное слово из файла, корректно обрабатывая кодировку."""
    if BASE_SIZE == 0:
        return "ошибка_базы_слов"

    try:
        with open(config.WORD_BASE, 'r', encoding='utf-8', errors='ignore') as base:
            offset = random.randrange(BASE_SIZE)
            base.seek(offset)
            
            # Считываем "обрывок" первой строки (мы могли попасть на середину)
            base.readline()
            
            # Считываем целую следующую строку
            word = base.readline()
            
            # Если попали в самый конец файла, word может быть пустым — пробуем сначала
            if not word:
                base.seek(0)
                word = base.readline()

            # ВАЖНО: Убираем пробелы и символы переноса строки (\n)
            return word.strip()
            
    except Exception as e:
        print(f"Error getting word: {e}")
        return "ошибка"


def croco_suggestion(suggestion, game, user, message_id):
    """Проверяет догадку пользователя."""
    target_word = game.get('word', '').strip()
    
    if not target_word:
        return

    # Экранируем слово (на случай если там есть + или ?)
    # Добавляем флаг re.IGNORECASE, чтобы "Слон" == "слон"
    pattern = r'\b{}\b'.format(re.escape(target_word))
    
    if not re.search(pattern, suggestion, re.IGNORECASE):
        return

    # --- СЛОВО УГАДАНО ---

    increments = {'croco.total': 1}
    
    # Ситуация 1: Ведущий сам назвал слово (жульничество или случайность)
    if user['id'] == game['player']:
        increments['croco.cheat'] = 1
        answer = f'Игра окончена! Ведущий ({user["full_name"]}) проговорился! Слово было: {target_word}'
    
    # Ситуация 2: Игрок угадал
    else:
        increments['croco.win'] = 1 # Победа ведущего (он смог объяснить)
        
        # Обновляем статистику того, КТО угадал
        database.update_one('stats',
            {'id': user['id'], 'chat': game['chat']},
            {
                '$set': {'name': user['full_name']}, 
                '$inc': {'croco.guesses': 1} # Очки за угадывание
            },
            upsert=True
        )
        answer = f'✅ Верно! {user["full_name"]} угадал слово "{target_word}"!'

    bot.try_to_send_message(game['chat'], answer, reply_to_message_id=message_id)
    
    # Удаляем игру
    database.delete_one('games', {'_id': game['_id']})
    
    # Обновляем статистику ВЕДУЩЕГО
    database.update_one('stats',
        {'id': game['player'], 'chat': game['chat']},
        {
            '$set': {'name': game['full_name']}, 
            '$inc': increments
        },
        upsert=True
    )