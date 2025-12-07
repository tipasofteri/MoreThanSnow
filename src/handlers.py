import config
import database
import lang
import croco
import gallows
import logging
import traceback
import os
from logging.handlers import RotatingFileHandler
from game import role_titles, stop_game, start_game
from stages import stages, go_to_next_stage, format_roles, get_votes, send_player_message
from bot import bot
from metrics import metrics

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiException

import re
import random
import html
from time import time
from uuid import uuid4
from datetime import datetime

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

def command_regexp(command):
    return f'^/{command}(@{bot.get_me().username})?$'

def safe_answer_callback(call_id, text, show_alert=False):
    try:
        bot.answer_callback_query(callback_query_id=call_id, text=text, show_alert=show_alert)
    except ApiException:
        pass

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

@bot.message_handler(regexp=command_regexp('help'))
@bot.message_handler(func=lambda message: message.chat.type == 'private', commands=['start'])
def start_command(message, *args, **kwargs):
    if message.text and message.text.startswith('/start'):
        start_text = (
            f'🎉 <b>Мафия: Новогодний Переполох</b> 🎉\n\n'
            '🎄 Добавь меня в группу и нажми /create\n'
            '🔔 Здесь ты будешь получать свою роль и делать ночные ходы.\n\n'
            '📜 Правила: /rules'
        )
        bot.send_message(message.chat.id, start_text, parse_mode='HTML')
    else:
        bot.send_message(message.chat.id, '/create - Создать игру\n/rules - Правила', parse_mode='HTML')

@bot.message_handler(regexp=command_regexp('rules'))
def show_rules(message, *args, **kwargs):
    rules = (
        '🎄 <b>КОДЕКС СЕВЕРНОГО ПОЛЮСА</b> 📜\n\n'
        '🎅 <b>Мирные:</b> Санта (Шериф), Лекарь, Снеговик, Ангел, Следопыт, Добряк.\n'
        '😈 <b>Злодеи:</b> Морозник (Мафия), Тёмный Эльф (Дон), Гринч, Крампус.\n'
        '🍷 <b>Нейтралы:</b> Пьяница, Снегурочка (Любовница), Хлопушка.\n\n'
        '🏆 <b>ПОБЕДА:</b> Мирные — изгнать Зло. Зло — захватить город.'
    )
    bot.send_message(message.chat.id, rules, parse_mode='HTML')

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
        # Выход
        action = '$pull'
        update_data = {'players': player_found}
        inc_val = -1
        alert_text = "Ты вышел."
    else:
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
            
            text = lang.role_card.format(role=role_titles[p['role']], goal=role_goal, description=role_desc)
            send_player_message(p, text)
            
        bot.send_message(message.chat.id, lang.game_started.format(order="\n".join([p['name'] for p in game['players']])), parse_mode='HTML')
        
        game_w_id = database.find_one('games', {'chat': message.chat.id})
        go_to_next_stage(game_w_id, inc=4)
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

@bot.callback_query_handler(func=lambda call: True)
def callback_router(call):
    if call.data in ['request interact', 'start game']: return

    game = database.find_one('games', {'chat': call.message.chat.id})
    if not game: return

    action = call.data.split()[0]
    
    if action in ['mistress', 'drunkard', 'sheriff', 'don', 'doctor', 'snowman', 'angel', 'tracker', 'shadow', 'grinch']:
        role_action(call, game, action)
    elif action == 'shot':
        mafia_shot(call, game)
    elif action == 'vote':
        vote_action(call, game)

def role_action(call, game, role_key):
    user_id = call.from_user.id
    player = next((p for p in game['players'] if p['id'] == user_id), None)
    
    if not player or player['role'] != role_key: return
    
    ok, err = can_act(game, user_id)
    if not ok: 
        bot.answer_callback_query(call.id, err, show_alert=True)
        return

    # Тень действует на себя (скрывается)
    if role_key == 'shadow':
        update = {'$addToSet': {'played': user_id}, '$set': {'hidden_shadows': [user_id]}} # Упрощенно добавляем в список
        database.update_one('games', {'_id': game['_id']}, update)
        bot.answer_callback_query(call.id, lang.shadow_active)
        try: bot.edit_message_text(lang.shadow_active, chat_id=player['id'], message_id=player.get('pm_id'))
        except: pass
        return

    try: target_idx = int(call.data.split()[1]) - 1
    except: return
    
    update = {'$addToSet': {'played': user_id}}
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

    elif role_key in ['sheriff', 'don']:
        t_role = game['players'][target_idx]['role']
        # Тень проверяется как мирный, если скрылась
        is_hidden = game['players'][target_idx]['id'] in game.get('hidden_shadows', [])
        
        if role_key == 'don':
            msg = "ЭТО ШЕРИФ!" if t_role == 'sheriff' and not is_hidden else "Не шериф."
        else:
            msg = "ЭТО МАФИЯ!" if t_role in ['mafia', 'don'] and not is_hidden else "Мирный."
        
        try: bot.edit_message_text(msg, chat_id=player['id'], message_id=player.get('pm_id'))
        except: bot.send_message(player['id'], msg)
        resp = "Проверено"

    database.update_one('games', {'_id': game['_id']}, update)
    bot.answer_callback_query(call.id, resp)
    
    if role_key not in ['sheriff', 'don']:
        try: bot.edit_message_reply_markup(player['id'], player.get('pm_id'), reply_markup=None)
        except: pass

def mafia_shot(call, game):
    user_id = call.from_user.id
    if not any(p['id'] == user_id and p['role'] in ['mafia', 'don'] for p in game['players']): return
    
    ok, err = can_act(game, user_id)
    if not ok:
        bot.answer_callback_query(call.id, err, show_alert=True)
        return

    try: target = int(call.data.split()[1]) - 1
    except: return

    database.update_one('games', {'_id': game['_id']}, 
                        {'$addToSet': {'played': user_id}, '$push': {'shots': target}})
    bot.answer_callback_query(call.id, "Выстрел принят")

def vote_action(call, game):
    user_id = call.from_user.id
    if user_id in game.get('silenced', []):
        bot.answer_callback_query(call.id, lang.action_silenced, show_alert=True)
        return
        
    try: target_idx = int(call.data.split()[1]) - 1
    except: return
    
    voter_idx = next(i for i, p in enumerate(game['players']) if p['id'] == user_id)
    
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {f'vote.{voter_idx}': target_idx, f'vote_map_ids.{user_id}': target_idx}
    })
    
    try:
        kb = InlineKeyboardMarkup(row_width=5)
        targets = [p for p in enumerate(game['players']) if p[1]['alive']]
        kb.add(*[InlineKeyboardButton(f'{i+1}', callback_data=f'vote {i+1}') for i, p in targets])
        kb.add(InlineKeyboardButton('🤐', callback_data='vote 0'))
        
        bot.edit_message_text(
            lang.vote_start.format(vote_list=get_votes(database.find_one('games', {'_id': game['_id']}))),
            chat_id=game['chat'],
            message_id=game['message_id'],
            reply_markup=kb,
            parse_mode='HTML'
        )
    except: pass
    
    bot.answer_callback_query(call.id, "Голос принят")

# --- MINI GAMES ---

@bot.group_message_handler(regexp=command_regexp('croco'))
def play_croco(message, game, *args, **kwargs):
    if game: return bot.send_message(message.chat.id, 'Игра уже идёт.')
    word = croco.get_word()
    if not word: return bot.send_message(message.chat.id, 'Ошибка базы слов.')

    game_id = str(uuid4())[:8]
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text='Получить слово', callback_data=f'get_word {game_id}'))
    name = get_name(message.from_user)
    
    database.insert_one('games', {
        'game': 'croco', 'id': game_id, 'player': message.from_user.id, 'name': name,
        'full_name': get_full_name(message.from_user), 'word': word, 'chat': message.chat.id,
        'time': time() + 120, 'stage': 0
    })
    bot.send_message(message.chat.id, f'🐊 <b>Крокодил!</b>\n{name}, объясни слово!', reply_markup=kb, parse_mode='HTML')

@bot.group_message_handler(regexp=command_regexp('gallows'))
def play_gallows(message, game, *args, **kwargs):
    if game: return bot.send_message(message.chat.id, 'Игра уже идёт.')
    word = croco.get_word()
    if not word: return
    sent = bot.send_message(message.chat.id, lang.gallows.format(result='', word=' '.join(['_']*len(word)), attempts='', players='') % gallows.stickman[0], parse_mode='HTML')
    database.insert_one('games', {'game': 'gallows', 'chat': message.chat.id, 'word': word, 'wrong': {}, 'right': {}, 'names': {}, 'message_id': sent.message_id})

@bot.callback_query_handler(func=lambda call: call.data.startswith('get_word'))
def get_croco_word(call):
    game = database.find_one('games', {'game': 'croco', 'id': call.data.split()[1]})
    if game and game['player'] == call.from_user.id: safe_answer_callback(call.id, f'Слово: {game["word"]}', show_alert=True)
    else: safe_answer_callback(call.id, 'Не твоя игра.', show_alert=True)

@bot.message_handler(func=lambda message: message.from_user.id == config.ADMIN_ID, regexp=command_regexp('reset'))
def reset(message, *args, **kwargs):
    database.delete_many('games', {})
    bot.send_message(message.chat.id, 'База игр очищена!')

@bot.group_message_handler(content_types=['text'])
def game_suggestion(message, game, *args, **kwargs):
    if not game or not message.text: return
    text = message.text.lower().replace('ё', 'е').strip()
    user = user_object(message.from_user)
    if game['game'] == 'gallows': gallows.gallows_suggestion(text, game, user, message.message_id)
    elif game['game'] == 'croco': croco.croco_suggestion(text, game, user, message.message_id)

@bot.group_message_handler()
def default_handler(message, *args, **kwargs): pass