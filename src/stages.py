import lang
from bot import bot
import database
from game import role_titles, stop_game
import random
from time import time
from collections import Counter
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiException

stages = {}

def add_stage(number, time=None, delete=False):
    def decorator(func):
        stages[number] = {'time': time, 'func': func, 'delete': delete}
        return func
    return decorator

def safe_lang_get(key, default="..."):
    return getattr(lang, key, default)

def get_votes(game):
    """Формирует список голосования для отображения в чате."""
    votes = game.get('vote', {})
    if not votes:
        return "Пока никто не голосовал."
    
    # Группируем голоса: за кого -> кто голосовал
    vote_map = {}
    for voter_idx, target_idx in votes.items():
        target_idx = int(target_idx)
        if target_idx not in vote_map: vote_map[target_idx] = []
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

def send_player_message(player, text, markup=None):
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
            player['pm_id'] = msg.message_id
            return True
        except:
            return False 
    return True

def go_to_next_stage(game, inc=1):
    database.delete_many('polls', {'chat': game['chat']})
    
    current_stage = game['stage']
    if current_stage >= 15:
        stage_number = 0
        database.update_one('games', {'_id': game['_id']}, {'$inc': {'day_count': 1}})
    else:
        stage_number = current_stage + inc

    stage = stages.get(stage_number)
    if not stage:
        print(f"Stage {stage_number} not found, skip")
        return go_to_next_stage(game, inc=1)

    duration = stage['time'](game) if callable(stage['time']) else stage['time']
    
    updates = {}
    if stage_number == 3:
        updates = {
            'shots': [], 'heals': [], 'played': [], 'stolen': [], 'blocks': [], 
            'shields': [], 'tracks': [], 'hidden_shadows': [], 'silenced': [],
            'current_event': None, 'caramel_mode': False,
            'vote': {}, 'vote_map_ids': {}
        }
        trigger_random_event(game)
        
    updates.update({
        'stage': stage_number,
        'time': time() + duration,
        'next_stage_time': time() + duration,
        'played': []
    })
    
    database.update_one('games', {'_id': game['_id']}, {'$set': updates})
    new_game = database.find_one('games', {'_id': game['_id']})
    
    try: stage['func'](new_game)
    except Exception as e: print(f"Error in stage {stage_number}: {e}")
    
    return new_game

def trigger_random_event(game):
    if random.random() > 0.2: return None
    event = random.choice(['blizzard', 'bonfire', 'firework'])
    database.update_one('games', {'_id': game['_id']}, {'$set': {'current_event': event}})
    return event

def format_roles(game, show_roles=False, condition=lambda p: p.get('alive', True)):
    return '\n'.join([f'{i+1}. {p["name"]}{" - " + role_titles.get(p.get("role"), "?") if show_roles else ""}' 
                      for i, p in enumerate(game['players']) if condition(p)])

# --- НОВАЯ ФУНКЦИЯ ОБНОВЛЕНИЯ ТАЙМЕРА ---
def update_timer(game):
    if 'message_id' not in game: return
    remaining = int(game['next_stage_time'] - time())
    if remaining < 0: remaining = 0
    time_str = f"{remaining} сек."
    
    text = None
    if game['stage'] == 0:
        text = lang.morning_message.format(
            day=game['day_count'],
            time=time_str, 
            order=format_roles(game),
            event_text=game.get('day_event_text', ''),
            peaceful_night=game.get('day_peace_text', '')
        )
    
    if text:
        try:
            bot.edit_message_text(text=text, chat_id=game['chat'], message_id=game['message_id'], parse_mode='HTML')
        except ApiException: pass

# --- СТАДИИ ---

@add_stage(-4, 60)
def lobby(game): pass

# ИЗМЕНЕНО: Время обсуждения теперь 60 секунд
@add_stage(0, 60)
def discussion(game):
    for p in game['players']:
        if p.get('pm_id'):
            try: bot.edit_message_reply_markup(p['id'], p['pm_id'], reply_markup=None)
            except: pass

    event_text = ("\n" + lang.event_cookies) if game.get('current_event') == 'cookies' else ""
    peace_text = lang.morning_peaceful if game['day_count'] > 1 else ""
    
    database.update_one('games', {'_id': game['_id']}, {
        '$set': {'day_event_text': event_text, 'day_peace_text': peace_text}
    })

    remaining = int(game['next_stage_time'] - time())
    msg = lang.morning_message.format(
        day=game['day_count'], 
        time=remaining, 
        order=format_roles(game), 
        event_text=event_text, 
        peaceful_night=peace_text
    )
    sent = bot.send_message(game['chat'], msg, parse_mode='HTML')
    database.update_one('games', {'_id': game['_id']}, {'$set': {'message_id': sent.message_id}})

@add_stage(1, 30)
def vote(game):
    kb = InlineKeyboardMarkup(row_width=5)
    targets = [p for p in enumerate(game['players']) if p[1]['alive']]
    kb.add(*[InlineKeyboardButton(f'{i+1}', callback_data=f'vote {i+1}') for i, p in targets])
    kb.add(InlineKeyboardButton('🤐', callback_data='vote 0'))
    
    sent = bot.send_message(game['chat'], lang.vote_start.format(vote_list=get_votes(game)), reply_markup=kb, parse_mode='HTML')
    database.update_one('games', {'_id': game['_id']}, {'$set': {'message_id': sent.message_id}})

@add_stage(2, 10)
def vote_results(game):
    votes = game.get('vote', {})
    if not votes:
        bot.send_message(game['chat'], lang.vote_result_nobody, parse_mode='HTML')
        return go_to_next_stage(game)
        
    counts = Counter(votes.values())
    if not counts: return go_to_next_stage(game)
    
    # ИСПРАВЛЕНО: Удаляем только голоса "Воздержаться" (индекс -1).
    # Индекс 0 (первый игрок) НЕ удаляем!
    if -1 in counts: del counts[-1]
    if '-1' in counts: del counts['-1']
    
    if not counts:
        bot.send_message(game['chat'], lang.vote_result_nobody, parse_mode='HTML')
        return go_to_next_stage(game)

    winner_idx, count = counts.most_common(1)[0]
    winner_idx = int(winner_idx)
    
    if list(counts.values()).count(count) > 1:
        bot.send_message(game['chat'], lang.vote_result_nobody, parse_mode='HTML')
        return go_to_next_stage(game)
        
    victim = game['players'][winner_idx]
    
    if winner_idx in game.get('blessings', []):
        bot.send_message(game['chat'], lang.vote_saved_angel.format(name=victim['name']), parse_mode='HTML')
        return go_to_next_stage(game)

    victim['alive'] = False
    bot.send_message(game['chat'], lang.vote_result_jail.format(criminal_name=victim['name'], criminal_num=winner_idx+1), parse_mode='HTML')
    
    if victim['role'] == 'kamikaze':
        killers = [int(v_id) for v_id, t_idx in game.get('vote_map_ids', {}).items() if int(t_idx) == winner_idx]
        if killers:
            boom_target_id = random.choice(killers)
            boom_target_idx = next((i for i, p in enumerate(game['players']) if p['id'] == boom_target_id), None)
            if boom_target_idx is not None:
                game['players'][boom_target_idx]['alive'] = False
                bot.send_message(game['chat'], lang.kamikaze_boom.format(name=game['players'][boom_target_idx]['name']), parse_mode='HTML')

    database.update_one('games', {'_id': game['_id']}, {'$set': {'players': game['players']}})
    
    alive = [p for p in game['players'] if p['alive']]
    mafia = [p for p in alive if p['role'] in ('mafia', 'don')]
    if not mafia: return stop_game(game, 'Мирные победили!')
    if len(mafia) >= len(alive) - len(mafia): return stop_game(game, 'Мафия победила!')
    
    go_to_next_stage(game)

@add_stage(3, 5)
def night_start(game):
    bot.send_message(game['chat'], lang.night_start, parse_mode='HTML')

def role_stage_gen(role_key, text_key):
    def func(game):
        player = next((p for p in game['players'] if p['role'] == role_key and p['alive']), None)
        if not player: return go_to_next_stage(game)
        if player['id'] not in game.get('blocks', []):
            kb = InlineKeyboardMarkup(row_width=4)
            targets = [p for p in enumerate(game['players']) if p[1]['alive']] if role_key == 'doctor' else [p for p in enumerate(game['players']) if p[1]['alive'] and p[1]['id'] != player['id']]
            kb.add(*[InlineKeyboardButton(f'{i+1}', callback_data=f'{role_key} {i+1}') for i,p in targets])
            text = safe_lang_get(text_key).format(time=30, check_available="Да", shield_available="Да", save_available="Да", hide_available="Да", steal_available="Да")
            send_player_message(player, text, kb)
            database.update_one('games', {'_id': game['_id']}, {'$set': {f'players.{game["players"].index(player)}.pm_id': player.get('pm_id')}})
        else:
            send_player_message(player, lang.action_blocked)
    return func

@add_stage(4, 20)
def mistress_stage(game): role_stage_gen('mistress', 'mistress_pm')(game)
@add_stage(5, 20)
def drunkard_stage(game): role_stage_gen('drunkard', 'drunkard_pm')(game)
@add_stage(6, 30)
def mafia_stage(game):
    mafiosi = [p for p in game['players'] if p['role'] in ('mafia', 'don') and p['alive']]
    if not mafiosi: return go_to_next_stage(game)
    kb = InlineKeyboardMarkup(row_width=4)
    targets = [p for p in enumerate(game['players']) if p[1]['alive']]
    kb.add(*[InlineKeyboardButton(f'{i+1}', callback_data=f'shot {i+1}') for i,p in targets])
    for p in mafiosi:
        if p['id'] not in game.get('blocks', []):
            team = ", ".join([m['name'] for m in mafiosi if m['id'] != p['id']])
            text = lang.mafia_pm.format(time=30, mafia_team=team or "Ты один")
            send_player_message(p, text, kb)
            database.update_one('games', {'_id': game['_id']}, {'$set': {f'players.{game["players"].index(p)}.pm_id': p.get('pm_id')}})
        else: send_player_message(p, lang.action_blocked)
@add_stage(7, 30)
def don_stage(game): role_stage_gen('don', 'don_pm')(game)
@add_stage(8, 30)
def sheriff_stage(game): role_stage_gen('sheriff', 'sheriff_pm')(game)
@add_stage(9, 30)
def doctor_stage(game): role_stage_gen('doctor', 'doctor_pm')(game)
@add_stage(10, 30)
def snowman_stage(game): role_stage_gen('snowman', 'snowman_pm')(game)

@add_stage(11, 20)
def morning_results(game):
    dead = []
    if game.get('shots'):
        target_idx = int(Counter(game['shots']).most_common(1)[0][0])
        is_healed = target_idx in [int(x) for x in game.get('heals', [])]
        is_shielded = target_idx in [int(x) for x in game.get('shields', [])]
        if not is_healed and not is_shielded: dead.append(target_idx)
    for idx in set(dead):
        p = game['players'][idx]
        p['alive'] = False
        bot.send_message(game['chat'], lang.morning_victim.format(victim_name=p['name'], victim_num=idx+1), parse_mode='HTML')
        if p['role'] == 'sheriff':
            deputy_idx = next((i for i, d in enumerate(game['players']) if d['role'] == 'deputy' and d['alive']), None)
            if deputy_idx is not None:
                game['players'][deputy_idx]['role'] = 'sheriff'
                bot.send_message(game['players'][deputy_idx]['id'], lang.deputy_promoted, parse_mode='HTML')
    if not dead: bot.send_message(game['chat'], lang.morning_peaceful, parse_mode='HTML')
    database.update_one('games', {'_id': game['_id']}, {'$set': {'players': game['players']}})
    alive = [p for p in game['players'] if p['alive']]
    mafia = [p for p in alive if p['role'] in ('mafia', 'don')]
    if not mafia: return stop_game(game, 'Мирные победили!')
    if len(mafia) >= len(alive) - len(mafia): return stop_game(game, 'Мафия победила!')
    go_to_next_stage(game)