# Copyright (C) 2017, 2018, 2019, 2020  alfred richardsn
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from typing import Optional

import config
from .database import database
from . import lang
# Removed croco and gallows imports
from .game import role_titles, stop_game
from .stages import stages, go_to_next_stage, format_roles, get_votes
from .bot import bot
from .newyear_mafia import NewYearMafiaGame, GamePhase, PlayerRole

# In-memory storage for active games
active_games = {}

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

import re
import random
from time import time
from uuid import uuid4
from datetime import datetime
from pymongo.collection import ReturnDocument


# ===== Snow mini-game (in-memory) =====
# Хранение очков и кулдаунов в памяти процесса (перезапускается при рестарте)
_snow_points = {}
_snow_last_action = {}

def _snow_rng_single():
    # 70% обычная (1), 20% синяя (3), 10% золотая (5)
    r = random.randint(1, 100)
    if r <= 70:
        return 1
    elif r <= 90:
        return 3
    else:
        return 5

def _snow_cooldown(user_id: int, seconds: float = 2.0) -> bool:
    now = time()
    last = _snow_last_action.get(user_id, 0.0)
    if now - last < seconds:
        return False
    _snow_last_action[user_id] = now
    return True


def get_name(user):
    return '@' + user.username if user.username else user.first_name


def get_full_name(user):
    result = user.first_name
    if user.last_name:
        result += ' ' + user.last_name
    return result


def user_object(user):
    return {'id': user.id, 'name': get_name(user), 'full_name': get_full_name(user)}


def command_regexp(command):
    return f'^/{command}(@{bot.get_me().username})?$'


@bot.message_handler(regexp=command_regexp('help'))
@bot.message_handler(func=lambda message: message.chat.type == 'private', commands=['start'])
def start_command(message, *args, **kwargs):
    answer = (
        f'Привет, я {bot.get_me().first_name}!\n'
        'Я умею создавать игры в мафию в группах и супергруппах.\n'
        'По всем вопросам пишите на https://t.me/AssetPro'
    )
    bot.send_message(message.chat.id, answer)


# --- Snow mini-game commands ---
@bot.message_handler(regexp=command_regexp('snow'))
def snow_command(message, *args, **kwargs):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(text='Поймать снежинку', callback_data='snow:single')
    )
    keyboard.add(
        InlineKeyboardButton(text='Поймать 5 сразу', callback_data='snow:five')
    )
    keyboard.add(
        InlineKeyboardButton(text='Рискнуть (x2/0)', callback_data='snow:risk')
    )
    keyboard.add(
        InlineKeyboardButton(text='Ежедневный бонус', callback_data='snow:daily')
    )
    bot.send_message(message.chat.id, 'Лови снежинки:', reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data in {'snow:single', 'snow:five', 'snow:risk', 'snow:daily'})
def snow_callbacks(call):
    user_id = call.from_user.id
    if not _snow_cooldown(user_id):
        bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text='Подождите…')
        return

    gained = 0
    if call.data == 'snow:single':
        gained = _snow_rng_single()
    elif call.data == 'snow:five':
        gained = sum(_snow_rng_single() for _ in range(5))
    elif call.data == 'snow:risk':
        last = 2  # упрощённо: последние очки условно принимаем 2
        gained = last * 2 if random.random() < 0.5 else -last
    elif call.data == 'snow:daily':
        gained = random.randint(3, 5)

    _snow_points[user_id] = _snow_points.get(user_id, 0) + gained
    sign = '+' if gained >= 0 else ''
    bot.answer_callback_query(callback_query_id=call.id)
    bot.send_message(call.message.chat.id, f'Снежинки: {sign}{gained}. Итого: {_snow_points[user_id]}')


def get_mafia_score(stats):
    if 'mafia' not in stats:
        return 0
    return stats['mafia'].get('score', 0)


@bot.message_handler(regexp=command_regexp('stats'))
def stats_command(message, *args, **kwargs):
    stats = database.stats.find_one({'id': message.from_user.id, 'chat': message.chat.id})

    if not stats:
        bot.send_message(message.chat.id, f'Статистика {get_name(message.from_user)} пуста.')
        return

    paragraphs = []

    if 'total' in stats:
        win = stats.get('win', 0)
        answer = (
            f'Счёт {get_name(message.from_user)} в мафии: {get_mafia_score(stats)}\n'
            f'Побед: {win}/{stats["total"]} ({100 * win // stats["total"]}%)'
        )
        roles = []
        for role, title in role_titles.items():
            if role in stats:
                role_win = stats[role].get('win', 0)
                roles.append({
                    'title': title,
                    'total': stats[role]['total'],
                    'win': role_win,
                    'rate': 100 * role_win // stats[role]['total']
                })
        for role in sorted(roles, key=lambda s: s['rate'], reverse=True):
            answer += (
                f'\n{role["title"].capitalize()}: '
                f'побед - {role.get("win", 0)}/{role["total"]} ({role["rate"]}%)'
            )
        paragraphs.append(answer)

    bot.send_message(message.chat.id, '\n\n'.join(paragraphs))


def update_rating(rating, name, score, maxlen):
    place = None
    for i, (_, rating_score) in enumerate(rating):
        if score > rating_score:
            place = i
            break
    if place is not None:
        rating.insert(place, (name, score))
        if len(rating) > maxlen:
            rating.pop(-1)
    elif len(rating) < maxlen:
        rating.append((name, score))


def get_rating_list(rating):
    return '\n'.join(f'{i + 1}. {n}: {s}' for i, (n, s) in enumerate(rating))


@bot.message_handler(regexp=command_regexp('rating'))
def rating_command(message, *args, **kwargs):
    chat_stats = database.stats.find({'chat': message.chat.id})

    if not chat_stats:
        bot.send_message(message.chat.id, 'Статистика чата пуста.')
        return

    mafia_rating = []
    for stats in chat_stats:
        if 'total' in stats:
            update_rating(mafia_rating, stats['name'], get_mafia_score(stats), 5)

    paragraphs = []
    if mafia_rating:
        paragraphs.append('Рейтинг игроков в мафию:\n' + get_rating_list(mafia_rating))

    bot.send_message(message.chat.id, '\n\n'.join(paragraphs))


@bot.callback_query_handler(func=lambda call: call.data == 'take card')
def take_card(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'stage': -4,
        'players.id': call.from_user.id,
        'chat': call.message.chat.id,
    })

    if player_game:
        player_index = next(i for i, p in enumerate(player_game['players']) if p['id'] == call.from_user.id)
        player_object = player_game['players'][player_index]

        if player_object.get('role') is None:
            keyboard = InlineKeyboardMarkup()
            keyboard.add(
                InlineKeyboardButton(
                    text='🃏 Вытянуть карту',
                    callback_data='take card'
                )
            )

            player_role = player_game['cards'][player_index]

            player_game = database.games.find_one_and_update(
                {'_id': player_game['_id']},
                {'$set': {f'players.{player_index}.role': player_role}},
                return_document=ReturnDocument.AFTER
            )

            bot.answer_callback_query(
                callback_query_id=call.id,
                show_alert=True,
                text=f'Твоя роль - {role_titles[player_role]}.'
            )

            players_without_roles = [i + 1 for i, p in enumerate(player_game['players']) if p.get('role') is None]

            if len(players_without_roles) > 0:
                bot.edit_message_text(
                    lang.take_card.format(
                        order=format_roles(player_game),
                        not_took=', '.join(map(str, players_without_roles))),
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=keyboard
                )

            else:
                database.games.update_one(
                    {'_id': player_game['_id']},
                    {'$set': {'order': []}}
                )

                bot.edit_message_text(
                    'Порядок игроков для игры следующий:\n\n' + format_roles(player_game),
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                )

                go_to_next_stage(player_game, inc=2)

        else:
            bot.answer_callback_query(
                callback_query_id=call.id,
                show_alert=False,
                text='У тебя уже есть роль.'
            )

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты сейчас не играешь в игру в этой конфе.'
        )


@bot.callback_query_handler(func=lambda call: call.data == 'mafia team')
def mafia_team(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'players': {'$elemMatch': {
            'id': call.from_user.id,
            'role': {'$in': ['don', 'mafia']},
        }},
        'chat': call.message.chat.id
    })

    if player_game:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=True,
            text='Ты играешь в следующей команде:\n' +
            format_roles(player_game, True, lambda p: p['role'] in ('don', 'mafia')))

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь знакомиться с командой мафии.'
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith('check don'))
def check_don(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'stage': 5,
        'players': {'$elemMatch': {
            'alive': True,
            'role': 'don',
            'id': call.from_user.id
        }},
        'chat': call.message.chat.id
    })

    if player_game and call.from_user.id not in player_game['played']:
        check_player = int(re.match(r'check don (\d+)', call.data).group(1)) - 1

        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=True,
            text=f'Да, игрок под номером {check_player + 1} - {role_titles["sheriff"]}'
                 if player_game['players'][check_player]['role'] == 'sheriff' else
                 f'Нет, игрок под номером {check_player + 1} - не {role_titles["sheriff"]}'
        )

        database.games.update_one({'_id': player_game['_id']}, {'$addToSet': {'played': call.from_user.id}})

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь совершать проверку дона.'
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith('check sheriff'))
def check_sheriff(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'stage': 6,
        'players': {'$elemMatch': {
            'alive': True,
            'role': 'sheriff',
            'id': call.from_user.id
        }},
        'chat': call.message.chat.id
    })

    if player_game and call.from_user.id not in player_game['played']:
        check_player = int(re.match(r'check sheriff (\d+)', call.data).group(1)) - 1

        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=True,
            text=f'Да, игрок под номером {check_player + 1} - {role_titles["don"]}'
                 if player_game['players'][check_player]['role'] == 'don' else
                 f'Да, игрок под номером {check_player + 1} - {role_titles["mafia"]}'
                 if player_game['players'][check_player]['role'] == 'mafia' else
                 f'Нет, игрок под номером {check_player + 1} - не {role_titles["mafia"]}'
        )

        database.games.update_one({'_id': player_game['_id']}, {'$addToSet': {'played': call.from_user.id}})

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь совершать проверку шерифа.'
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith('append to order'))
def append_order(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'stage': -2,
        'players': {'$elemMatch': {
            'role': 'don',
            'id': call.from_user.id
        }},
        'chat': call.message.chat.id
    })

    if player_game:
        call_player = re.match(r'append to order (\d+)', call.data).group(1)

        database.games.update_one(
            {'_id': player_game['_id']},
            {'$addToSet': {'order': call_player}}
        )

        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text=f'Игрок под номером {call_player} добавлен в приказ.'
        )

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь отдавать приказ дона.'
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith('vote'))
def vote(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'stage': 1,
        'players': {'$elemMatch': {
            'alive': True,
            'id': call.from_user.id
        }},
        'chat': call.message.chat.id
    })

    if player_game and call.from_user.id not in player_game['played']:
        vote_player = int(re.match(r'vote (\d+)', call.data).group(1)) - 1
        player_index = next(i for i, p in enumerate(player_game['players']) if p['id'] == call.from_user.id)

        game = database.games.find_one_and_update(
            {'_id': player_game['_id']},
            {'$addToSet': {
                'played': call.from_user.id,
                'vote.%d' % vote_player: player_index
            }},
            return_document=ReturnDocument.AFTER
        )

        keyboard = InlineKeyboardMarkup(row_width=8)
        keyboard.add(
            *[InlineKeyboardButton(
                text=f'{i + 1}',
                callback_data=f'vote {i + 1}'
            ) for i, player in enumerate(game['players']) if player['alive']]
        )
        keyboard.add(
            InlineKeyboardButton(
                text='Не голосовать',
                callback_data='vote 0'
            )
        )
        bot.edit_message_text(
            lang.vote.format(vote=get_votes(game)),
            chat_id=game['chat'],
            message_id=game['message_id'],
            reply_markup=keyboard
        )

        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text=f'Голос отдан против игрока {vote_player + 1}.' if vote_player >= 0 else 'Голос отдан.'
        )

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь голосовать.'
        )


@bot.callback_query_handler(func=lambda call: call.data == 'end order')
def end_order(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'stage': -2,
        'players': {'$elemMatch': {
            'role': 'don',
            'id': call.from_user.id
        }},
        'chat': call.message.chat.id
    })

    if player_game:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Приказ записан и будет передан команде мафии.'
        )

        go_to_next_stage(player_game)

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь отдавать приказ дона.'
        )


@bot.callback_query_handler(
    func=lambda call: call.data == 'get order',
)
def get_order(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        '$or': [
            {'players': {'$elemMatch': {
                'role': 'don',
                'id': call.from_user.id
            }}},
            {'players': {'$elemMatch': {
                'role': 'mafia',
                'id': call.from_user.id
            }}}
        ],
        'chat': call.message.chat.id
    })

    if player_game:
        if player_game.get('order'):
            order_text = f'Я отдал тебе следующий приказ: {", ".join(player_game["order"])}. Стреляем именно в таком порядке, в противном случае промахнёмся. ~ {role_titles["don"]}'
        else:
            order_text = f'Я не отдал приказа, импровизируем по ходу игры. Главное - стрелять в одних и тех же людей в одну ночь, в противном случае промахнёмся. ~ {role_titles["don"]}'

        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=True,
            text=order_text
        )

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь получать приказ дона.'
        )


@bot.callback_query_handler(func=lambda call: call.data == 'request interact')
def request_interact(call):
    message_id = call.message.message_id
    required_request = database.requests.find_one({'message_id': message_id})

    if required_request:
        update_dict = {}
        player_object = None
        for player in required_request['players']:
            if player['id'] == call.from_user.id:
                player_object = player
                increment_value = -1
                request_action = '$pull'
                alert_message = 'Ты больше не в игре.'

                break

        if player_object is None:
            if len(required_request['players']) >= config.PLAYERS_COUNT_LIMIT:
                bot.answer_callback_query(
                    callback_query_id=call.id,
                    show_alert=False,
                    text='В игре состоит максимальное количество игроков.'
                )
                return

            player_object = user_object(call.from_user)
            player_object['alive'] = True
            increment_value = 1
            request_action = '$push'
            alert_message = 'Ты теперь в игре.'
            update_dict['$set'] = {'time': time() + config.REQUEST_OVERDUE_TIME}

        update_dict.update(
            {request_action: {'players': player_object},
             '$inc': {'players_count': increment_value}}
        )

        updated_document = database.requests.find_one_and_update(
            {'_id': required_request['_id']},
            update_dict,
            return_document=ReturnDocument.AFTER
        )

        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton(
                text='Вступить в игру или выйти из игры',
                callback_data='request interact'
            )
        )

        bot.edit_message_text(
            lang.new_request.format(
                owner=updated_document['owner']['name'],
                time=datetime.utcfromtimestamp(updated_document['time']).strftime('%H:%M'),
                order='Игроков нет.' if not updated_document['players_count'] else
                      'Игроки:\n' + '\n'.join([f'{i + 1}. {p["name"]}' for i, p in enumerate(updated_document['players'])])
            ),
            chat_id=call.message.chat.id,
            message_id=message_id,
            reply_markup=keyboard
        )

        bot.answer_callback_query(callback_query_id=call.id, show_alert=False, text=alert_message)
    else:
        bot.edit_message_text('Заявка больше не существует.', chat_id=call.message.chat.id, message_id=message_id)


@bot.group_message_handler(regexp=command_regexp('create'))
def create(message, *args, **kwargs):
    existing_request = database.requests.find_one({'chat': message.chat.id})
    if existing_request:
        bot.send_message(message.chat.id, 'В этом чате уже есть игра!', reply_to_message_id=existing_request['message_id'])
        return
    existing_game = database.games.find_one({'chat': message.chat.id, 'game': 'mafia'})
    if existing_game:
        bot.send_message(message.chat.id, 'В этом чате уже идёт игра!')
        return

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton(
            text='Вступить в игру или выйти из игры',
            callback_data='request interact'
        )
    )

    player_object = user_object(message.from_user)
    player_object['alive'] = True
    request_overdue_time = time() + config.REQUEST_OVERDUE_TIME

    answer = lang.new_request.format(
        owner=get_name(message.from_user),
        time=datetime.utcfromtimestamp(request_overdue_time).strftime('%H:%M'),
        order=f'Игроки:\n1. {player_object["name"]}'
    )
    sent_message = bot.send_message(message.chat.id, answer, reply_markup=keyboard)

    database.requests.insert_one({
        'id': str(uuid4())[:8],
        'owner': player_object,
        'players': [player_object],
        'time': request_overdue_time,
        'chat': message.chat.id,
        'message_id': sent_message.message_id,
        'players_count': 1
    })


@bot.group_message_handler(regexp=command_regexp('start'))
def start_game(message, *args, **kwargs):
    req = database.requests.find_and_modify(
        {
            'owner.id': message.from_user.id,
            'chat': message.chat.id,
            'players_count': {'$gte': config.PLAYERS_COUNT_TO_START}
        },
        new=False,
        remove=True
    )
    if req is not None:
        players_count = req['players_count']

        cards = ['mafia'] * (players_count // 3 - 1) + ['don', 'sheriff']
        cards += ['peace'] * (players_count - len(cards))
        random.shuffle(cards)

        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton(
                text='🃏 Вытянуть карту',
                callback_data='take card'
            )
        )

        stage_number = min(stages.keys())

        message_id = bot.send_message(
            message.chat.id,
            lang.take_card.format(
                order='\n'.join([f'{i + 1}. {p["name"]}' for i, p in enumerate(req['players'])]),
                not_took=', '.join(map(str, range(1, len(req['players']) + 1))),
            ),
            reply_markup=keyboard
        ).message_id

        database.games.insert_one({
            'game': 'mafia',
            'chat': req['chat'],
            'id': req['id'],
            'stage': stage_number,
            'day_count': 0,
            'players': req['players'],
            'cards': cards,
            'next_stage_time': time() + stages[stage_number]['time'],
            'message_id': message_id,
            'don': [],
            'vote': {},
            'shots': [],
            'played': []
        })

    else:
        bot.send_message(message.chat.id, 'У тебя нет заявки на игру, которую возможно начать.')


@bot.group_message_handler(regexp=command_regexp('cancel'))
def cancel(message, *args, **kwargs):
    req = database.requests.find_one_and_delete({
        'owner.id': message.from_user.id,
        'chat': message.chat.id
    })
    if req:
        answer = 'Твоя заявка удалена.'
    else:
        answer = 'У тебя нет заявки на игру.'
    bot.send_message(message.chat.id, answer)


@bot.group_message_handler(regexp=command_regexp('end'))
def force_game_end(message, game, *args, **kwargs):
    create_poll(message, game, 'end', 'закончить игру')


@bot.group_message_handler(regexp=command_regexp('skip'))
def skip_current_stage(message, game, *args, **kwargs):
    create_poll(message, game, 'skip', 'пропустить текущую стадию')


@bot.callback_query_handler(func=lambda call: call.data == 'poll')
def poll_vote(call):
    message_id = call.message.message_id
    poll = database.polls.find_one({'message_id': message_id})

    if not poll:
        bot.edit_message_text(
            'Голосование больше не существует.',
            chat_id=call.message.chat.id,
            message_id=message_id
        )
        return

    if call.from_user.id in poll['votes']:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Твой голос уже был учтён.',
        )
        return

    player_game = database.games.find_one({
        'game': 'mafia',
        'players': {'$elemMatch': {
            'alive': True,
            'id': call.from_user.id
        }},
        'chat': call.message.chat.id
    })

    if not player_game:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь голосовать.',
        )
        return

    increment_value = {}

    if poll['check_roles']:
        mafia_count = poll['mafia_count']
        peace_count = poll['peace_count']

        for player in player_game['players']:
            if player['id'] == call.from_user.id:
                if player['role'] in ('don', 'mafia'):
                    increment_value['mafia_count'] = 1
                    mafia_count += 1
                else:
                    increment_value['peace_count'] = 1
                    peace_count += 1

                poll_condition = mafia_count > poll['mafia_required'] and peace_count >= poll['peace_required']
                break
    else:
        increment_value['count'] = 1
        poll_condition = poll['count'] + 1 > poll['required']

    if poll_condition:
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=message_id
        )
        if poll['type'] == 'skip':
            go_to_next_stage(player_game)
        elif poll['type'] == 'end':
            stop_game(player_game, reason='Игроки проголосовали за окончание игры.')
            return

    database.polls.update_one(
        {'_id': poll['_id']},
        {
            '$addToSet': {'votes': call.from_user.id},
            '$inc': increment_value
        }
    )

    bot.answer_callback_query(
        callback_query_id=call.id,
        show_alert=False,
        text='Голос учтён.'
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('shot'))
def callback_inline(call):
    player_game = database.games.find_one({
        'game': 'mafia',
        'stage': 4,
        'players': {'$elemMatch': {
            'alive': True,
            'role': {'$in': ['don', 'mafia']},
            'id': call.from_user.id
        }},
        'chat': call.message.chat.id
    })

    if player_game and call.from_user.id not in player_game['played']:
        victim = int(call.data.split()[1]) - 1
        database.games.update_one(
            {'_id': player_game['_id']},
            {
                '$addToSet': {'played': call.from_user.id},
                '$push': {'shots': victim}
            }
        )

        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text=f'Выстрел произведён в игрока {victim + 1}'
        )

    else:
        bot.answer_callback_query(
            callback_query_id=call.id,
            show_alert=False,
            text='Ты не можешь участвовать в стрельбе'
        )


@bot.message_handler(
    func=lambda message: message.from_user.id == config.ADMIN_ID,
    regexp=command_regexp('reset')
)
def reset(message, *args, **kwargs):
    database.games.delete_many({})
    bot.send_message(message.chat.id, 'База игр сброшена!')


@bot.message_handler(
    func=lambda message: message.from_user.id == config.ADMIN_ID,
    regexp=command_regexp('database')
)
def print_database(message, *args, **kwargs):
    print(list(database.games.find()))
    bot.send_message(message.chat.id, 'Все документы базы данных игр выведены в терминал!')


@bot.group_message_handler()
# ===== New Year's Mafia Commands =====

def get_game(chat_id: int) -> Optional[NewYearMafiaGame]:
    """Get active game for chat or None if none exists"""
    return active_games.get(chat_id)

def end_game(chat_id: int):
    """End and remove the game for the chat"""
    if chat_id in active_games:
        del active_games[chat_id]

@bot.message_handler(commands=['startmatch'])
def start_match_command(message):
    """Create a new New Year's Mafia game"""
    chat_id = message.chat.id
    if chat_id in active_games:
        bot.reply_to(message, "Игра уже идет в этом чате!")
        return
        
    game = NewYearMafiaGame(chat_id, message.from_user.id, message.from_user.first_name)
    game.add_player(message.from_user.id, message.from_user.first_name)
    active_games[chat_id] = game
    
    bot.reply_to(
        message,
        "🎄 *Новогодняя Мафия* 🎄\n"
        f"Создана новая игра! Присоединяйтесь: /join\n"
        f"Игроков: 1/6-10\n"
        f"Начать игру: /start",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['join'])
def join_command(message):
    """Join the current game"""
    game = get_game(message.chat.id)
    if not game:
        bot.reply_to(message, "Нет активной игры. Создайте игру с помощью /startmatch")
        return
        
    if game.phase != GamePhase.LOBBY:
        bot.reply_to(message, "Игра уже началась!")
        return
        
    if game.add_player(message.from_user.id, message.from_user.first_name):
        player_count = len(game.players)
        bot.reply_to(
            message,
            f"🎮 {message.from_user.first_name} присоединился(ась) к игре!\n"
            f"Игроков: {player_count}/10\n"
            f"Присоединиться: /join\n"
            f"Начать игру: /start"
        )
    else:
        bot.reply_to(message, "Вы уже в игре!")

@bot.message_handler(commands=['leave'])
def leave_command(message):
    """Leave the current game"""
    game = get_game(message.chat.id)
    if not game:
        bot.reply_to(message, "Нет активной игры.")
        return
        
    if game.phase != GamePhase.LOBBY:
        bot.reply_to(message, "Нельзя выйти после начала игры!")
        return
        
    if game.remove_player(message.from_user.id):
        player_count = len(game.players)
        bot.reply_to(
            message,
            f"👋 {message.from_user.first_name} вышел(а) из игры.\n"
            f"Осталось игроков: {player_count}"
        )
        
        # If no players left, end the game
        if player_count == 0:
            end_game(message.chat.id)
    else:
        bot.reply_to(message, "Вы не в игре!")

@bot.message_handler(commands=['start'])
def start_game_command(message):
    """Start the game"""
    game = get_game(message.chat.id)
    if not game:
        bot.reply_to(message, "Нет активной игры. Создайте игру с помощью /startmatch")
        return
        
    if game.phase != GamePhase.LOBBY:
        bot.reply_to(message, "Игра уже началась!")
        return
        
    if message.from_user.id != game.creator_id:
        bot.reply_to(message, "Только создатель игры может её начать!")
        return
        
    if len(game.players) not in [6, 8, 10]:
        bot.reply_to(message, "Для начала игры нужно 6, 8 или 10 игроков!")
        return
        
    if game.start_game():
        # Notify all players of their roles via private message
        for player in game.players:
            try:
                bot.send_message(
                    player['id'],
                    f"🎭 Ваша роль: *{player['role'].value}*\n\n"
                    f"{'Вы - мирный житель. Ваша цель - вычислить и казнить всех мафиози.' if player['role'] == PlayerRole.CITIZEN else ''}"
                    f"{'Вы - Доктор. Каждую ночь вы можете вылечить одного игрока.' if player['role'] == PlayerRole.DOCTOR else ''}"
                    f"{'Вы - Детектив. Каждую ночь вы можете проверить роль одного игрока.' if player['role'] == PlayerRole.DETECTIVE else ''}"
                    f"{'Вы - Главарь мафии. Выбирайте, кого убить ночью.' if player['role'] == PlayerRole.MAFIA_BOSS else ''}"
                    f"{'Вы - Сообщник мафии. Помогайте главарю в выборе жертвы.' if player['role'] == PlayerRole.MAFIA else ''}",
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Could not send PM to {player['name']}: {e}")
        
        # Start the first night
        bot.send_message(
            message.chat.id,
            "🎭 *Игра началась!* 🎭\n"
            "Наступает ночь. Все засыпают...\n"
            "Мафия, доктор и детектив - проверьте личные сообщения для действий.",
            parse_mode='Markdown'
        )
        
        # Send action buttons to relevant players
        for player in game.players:
            if player['role'] in [PlayerRole.MAFIA_BOSS, PlayerRole.DOCTOR, PlayerRole.DETECTIVE]:
                try:
                    send_night_actions(player['id'], game)
                except Exception as e:
                    print(f"Could not send night actions to {player['name']}: {e}")
    else:
        bot.reply_to(message, "Не удалось начать игру. Попробуйте ещё раз.")

def send_night_actions(player_id: int, game: NewYearMafiaGame):
    """Send night action buttons to a player"""
    player = next((p for p in game.players if p['id'] == player_id), None)
    if not player or not player['alive']:
        return
        
    role = player['role']
    
    if role in [PlayerRole.MAFIA_BOSS, PlayerRole.MAFIA]:
        # Only the mafia boss can submit the kill
        if role == PlayerRole.MAFIA_BOSS:
            keyboard = InlineKeyboardMarkup()
            alive_players = game.get_alive_players(player_id)
            for p in alive_players:
                keyboard.add(InlineKeyboardButton(
                    text=p['name'],
                    callback_data=f"mafia_kill:{p['id']}"
                ))
            
            bot.send_message(
                player_id,
                "🌙 Ночь. Выберите жертву:",
                reply_markup=keyboard
            )
    
    elif role == PlayerRole.DOCTOR:
        keyboard = InlineKeyboardMarkup()
        alive_players = game.get_alive_players(player_id)
        for p in alive_players:
            keyboard.add(InlineKeyboardButton(
                text=p['name'],
                callback_data=f"doctor_heal:{p['id']}"
            ))
        
        bot.send_message(
            player_id,
            "🌙 Ночь. Кого вылечите?",
            reply_markup=keyboard
        )
    
    elif role == PlayerRole.DETECTIVE:
        keyboard = InlineKeyboardMarkup()
        alive_players = game.get_alive_players(player_id)
        for p in alive_players:
            keyboard.add(InlineKeyboardButton(
                text=p['name'],
                callback_data=f"detective_check:{p['id']}"
            ))
        
        bot.send_message(
            player_id,
            "🌙 Ночь. Кого проверить?",
            reply_markup=keyboard
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith(('mafia_kill:', 'doctor_heal:', 'detective_check:')))
def night_action_handler(call):
    """Handle night action callbacks"""
    game = get_game(call.message.chat.id)
    if not game or game.phase != GamePhase.NIGHT:
        bot.answer_callback_query(call.id, "Сейчас не ночная фаза!")
        return
    
    action, target_id = call.data.split(':')
    target_id = int(target_id)
    
    if action == 'mafia_kill' and game.get_player_role(call.from_user.id) == PlayerRole.MAFIA_BOSS:
        if game.process_night_action(call.from_user.id, target_id):
            bot.answer_callback_query(call.id, f"Выбрана цель: {next(p['name'] for p in game.players if p['id'] == target_id)}")
            bot.edit_message_text("✅ Готово!", call.message.chat.id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "Ошибка выбора цели!")
    
    elif action == 'doctor_heal' and game.get_player_role(call.from_user.id) == PlayerRole.DOCTOR:
        if game.process_night_action(call.from_user.id, target_id):
            bot.answer_callback_query(call.id, f"Вы будете лечить: {next(p['name'] for p in game.players if p['id'] == target_id)}")
            bot.edit_message_text("✅ Готово!", call.message.chat.id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "Ошибка выбора цели!")
    
    elif action == 'detective_check' and game.get_player_role(call.from_user.id) == PlayerRole.DETECTIVE:
        if game.process_night_action(call.from_user.id, target_id):
            target_name = next(p['name'] for p in game.players if p['id'] == target_id)
            result = game.night_actions[f'detective_check_{call.from_user.id}']['result']
            bot.answer_callback_query(call.id, f"Результат проверки {target_name}: {result}")
            bot.edit_message_text("✅ Готово!", call.message.chat.id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "Ошибка проверки!")
    else:
        bot.answer_callback_query(call.id, "У вас нет прав на это действие!")

@bot.message_handler(commands=['endnight'])
def end_night_command(message):
    """End the night phase (admin only)"""
    game = get_game(message.chat.id)
    if not game or game.phase != GamePhase.NIGHT:
        return
        
    if message.from_user.id != game.creator_id:
        bot.reply_to(message, "Только создатель игры может завершить ночь!")
        return
        
    result = game.process_night()
    if game.phase == GamePhase.ENDED:
        # Game over
        bot.send_message(message.chat.id, result, parse_mode='Markdown')
        # Show roles
        roles = "🔍 *Роли игроков:*\n"
        for p in game.players:
            roles += f"{p['name']}: {p['role'].value}\n"
        bot.send_message(message.chat.id, roles, parse_mode='Markdown')
        end_game(message.chat.id)
    else:
        # Start day phase
        bot.send_message(
            message.chat.id,
            f"☀️ *День {game.day_number}*\n"
            f"{result}\n\n"
            f"Начинается обсуждение! Голосование начнётся через {game.day_time} секунд.",
            parse_mode='Markdown'
        )
        
        # Schedule voting to start after discussion time
        def start_voting(chat_id):
            game = get_game(chat_id)
            if game and game.phase == GamePhase.DAY:
                game.start_voting()
                bot.send_message(
                    chat_id,
                    "🗳 *Голосование началось!*\n"
                    "Голосуйте за игрока, которого хотите казнить, или нажмите /skip, чтобы пропустить.",
                    parse_mode='Markdown'
                )
        
        import threading
        timer = threading.Timer(game.day_time, start_voting, [message.chat.id])
        timer.start()

@bot.message_handler(commands=['vote'])
def vote_command(message):
    """Vote for a player during voting phase"""
    game = get_game(message.chat.id)
    if not game or game.phase != GamePhase.VOTING:
        return
        
    voter = next((p for p in game.players if p['id'] == message.from_user.id), None)
    if not voter or not voter['alive'] or voter['voted']:
        return
        
    # Check if the message is a reply to another player's message
    if not message.reply_to_message:
        bot.reply_to(message, "Ответьте на сообщение игрока, за которого голосуете!")
        return
        
    target = next((p for p in game.players if p['id'] == message.reply_to_message.from_user.id), None)
    if not target or not target['alive'] or target['id'] == message.from_user.id:
        bot.reply_to(message, "Нельзя проголосовать за этого игрока!")
        return
        
    if game.process_day_vote(message.from_user.id, target['id']):
        bot.reply_to(message, f"✅ Ваш голос против {target['name']} учтён!")
    else:
        bot.reply_to(message, "❌ Не удалось обработать ваш голос!")

@bot.message_handler(commands=['skip'])
def skip_vote_command(message):
    """Skip voting (abstain)"""
    game = get_game(message.chat.id)
    if not game or game.phase != GamePhase.VOTING:
        return
        
    voter = next((p for p in game.players if p['id'] == message.from_user.id), None)
    if not voter or not voter['alive'] or voter['voted']:
        return
        
    if game.process_day_vote(message.from_user.id, None):
        bot.reply_to(message, "✅ Вы решили воздержаться от голосования.")
    else:
        bot.reply_to(message, "❌ Не удалось обработать ваш голос!")

@bot.message_handler(commands=['endvote'])
def end_vote_command(message):
    """End the voting phase (admin only)"""
    game = get_game(message.chat.id)
    if not game or game.phase != GamePhase.VOTING:
        return
        
    if message.from_user.id != game.creator_id:
        bot.reply_to(message, "Только создатель игры может завершить голосование!")
        return
        
    result = game.process_voting()
    if game.phase == GamePhase.ENDED:
        # Game over
        bot.send_message(message.chat.id, result, parse_mode='Markdown')
        # Show roles
        roles = "🔍 *Роли игроков:*\n"
        for p in game.players:
            roles += f"{p['name']}: {p['role'].value}\n"
        bot.send_message(message.chat.id, roles, parse_mode='Markdown')
        end_game(message.chat.id)
    else:
        # Start next night
        bot.send_message(
            message.chat.id,
            f"🌙 *Ночь {game.day_number}*\n"
            f"{result}\n\n"
            f"Мафия, доктор и детектив - проверьте личные сообщения для действий.",
            parse_mode='Markdown'
        )
        
        # Send action buttons to relevant players
        for player in game.players:
            if player['alive'] and player['role'] in [PlayerRole.MAFIA_BOSS, PlayerRole.DOCTOR, PlayerRole.DETECTIVE]:
                try:
                    send_night_actions(player['id'], game)
                except Exception as e:
                    print(f"Could not send night actions to {player['name']}: {e}")

@bot.message_handler(commands=['status'])
def status_command(message):
    """Show current game status"""
    game = get_game(message.chat.id)
    if not game:
        bot.reply_to(message, "Нет активной игры. Создайте игру с помощью /startmatch")
        return
        
    status = game.get_game_state()
    
    # Build status message
    if status['phase'] == GamePhase.LOBBY.value:
        players = ", ".join([p['name'] for p in status['players']])
        message_text = (
            f"🎮 *Лобби Новогодней Мафии* 🎮\n"
            f"Игроков: {len(status['players'])}\n"
            f"Игроки: {players}\n\n"
            f"Присоединиться: /join\n"
            f"Начать игру: /start"
        )
    else:
        alive_players = [p for p in status['players'] if p['alive']]
        dead_players = [p for p in status['players'] if not p['alive']]
        
        if status['phase'] == GamePhase.NIGHT.value:
            phase = f"🌙 Ночь {status['day']}"
        elif status['phase'] == GamePhase.DAY.value:
            phase = f"☀️ День {status['day']} (обсуждение)"
        else:  # VOTING
            phase = f"🗳 День {status['day']} (голосование)"
        
        message_text = (
            f"🎭 *Новогодняя Мафия* 🎭\n"
            f"{phase}\n"
            f"Живых игроков: {len(alive_players)}\n\n"
        )
        
        if dead_players:
            message_text += "☠️ Выбыли: " + ", ".join([p['name'] for p in dead_players]) + "\n\n"
        
        if status['current_event']:
            message_text += f"✨ Событие: {status['current_event']}\n\n"
        
        # Show alive players
        message_text += "👥 *Игроки:*\n"
        for i, player in enumerate(alive_players, 1):
            role = f" ({player['role']})" if player['role'] and status['phase'] == GamePhase.ENDED.value else ""
            voted = " ✅" if player.get('voted') else ""
            message_text += f"{i}. {player['name']}{role}{voted}\n"
    
    bot.reply_to(message, message_text, parse_mode='Markdown')

@bot.message_handler(commands=['end'])
def end_game_command(message):
    """End the current game (admin only)"""
    game = get_game(message.chat.id)
    if not game:
        bot.reply_to(message, "Нет активной игры.")
        return
        
    if message.from_user.id != game.creator_id and message.from_user.id not in config.ADMIN_IDS:
        bot.reply_to(message, "Только создатель игры или администратор может её завершить!")
        return
        
    # Show final roles
    roles = "🎭 *Роли игроков:*\n"
    for p in game.players:
        roles += f"{p['name']}: {p['role'].value}\n"
    
    bot.send_message(message.chat.id, "❌ Игра досрочно завершена!\n\n" + roles, parse_mode='Markdown')
    end_game(message.chat.id)

# Default handler (must be last)
def default_handler(message, *args, **kwargs):
    pass
