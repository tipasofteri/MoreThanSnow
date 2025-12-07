import os
import sys
from time import time, sleep
from threading import Thread
import flask
from telebot import logger
from telebot.types import Update
from telebot.apihelper import ApiException 

# Add the current directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import config
import database
from handlers import bot
from game import stop_game
from stages import go_to_next_stage, update_timer # Импортируем update_timer

# Flask app initialization
app = flask.Flask(__name__)

def is_game_over(game):
    try:
        alive_players = [p for p in game['players'] if p['alive']]
        mafia = sum(1 for p in alive_players if p['role'] in ('don', 'mafia'))
        total_alive = len(alive_players)
        if mafia == 0: return 1
        if mafia >= total_alive - mafia: return 2
        return 0
    except KeyError:
        return 0

def stage_cycle():
    """Главный цикл смены стадий игры + Обновление таймеров"""
    last_timer_update = time()
    
    while True:
        try:
            current_time = time()
            
            # 1. Проверяем игры, где время истекло (переход на след. стадию)
            expired_games = database.find('games', {'game': 'mafia', 'next_stage_time': {'$lte': current_time}})
            
            for game in expired_games:
                try:
                    go_to_next_stage(game)
                except Exception as e:
                    logger.error(f"Error switching stage for game {game.get('_id')}: {e}")
                    database.update_one('games', {'_id': game['_id']}, {'$set': {'next_stage_time': time() + 10}})

            # 2. Обновляем таймеры в активных играх (раз в 10 секунд)
            # Обновляем только стадию 0 (День), так как там длинный таймер
            if current_time - last_timer_update >= 10:
                active_games = database.find('games', {'game': 'mafia', 'stage': 0, 'next_stage_time': {'$gt': current_time}})
                for game in active_games:
                    try:
                        update_timer(game)
                    except Exception:
                        pass
                last_timer_update = current_time

        except Exception as e:
            logger.error(f"Error in stage_cycle loop: {e}")
            sleep(1)
        
        sleep(1)

def remove_overtimed_requests():
    while True:
        try:
            database.delete_many('requests', {'time': {'$lte': time()}})
        except Exception as e:
            logger.error(f"Error in remove_overtimed_requests: {e}")
        sleep(5)

def croco_cycle():
    while True:
        try:
            curtime = time()
            games = database.find('games', {'game': 'croco', 'time': {'$lte': curtime}})
            for game in games:
                try:
                    if game.get('stage') == 0:
                        if database.update_one('games', {'_id': game['_id'], 'stage': 0}, {'$set': {'stage': 1, 'time': curtime + 60}}):
                            bot.send_message(game['chat'], f"{game.get('name', 'Игрок')}, минута осталась!")
                    else:
                        word = game.get('word', '???')
                        database.delete_one('games', {'_id': game['_id']})
                        bot.send_message(game['chat'], f'Время вышло! Слово было "{word}".')
                        database.update_one('stats', {'id': game['player'], 'chat': game['chat']}, {'$inc': {'croco.total': 1}, '$set': {'name': game.get('full_name', '')}}, upsert=True)
                except Exception: pass
        except Exception: pass
        sleep(1)

def start_thread(name, target):
    thread = Thread(target=target, name=name, daemon=True)
    thread.start()
    logger.info(f'Thread started: {name}')

@app.route(f'/{config.TOKEN}', methods=['POST'])
def webhook():
    if flask.request.headers.get('content-type') == 'application/json':
        json_string = flask.request.get_data().decode('utf-8')
        update = Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return flask.abort(403)

def main():
    try:
        print("Starting background threads...")
        start_thread('Stage Cycle', stage_cycle)
        start_thread('Request Cleaner', remove_overtimed_requests)
        start_thread('Croco Cycle', croco_cycle)
        
        print("Bot logic initialized.")

        if config.SET_WEBHOOK:
            print(f"Setting webhook to: https://{config.SERVER_IP}/{config.TOKEN}")
            bot.remove_webhook()
            sleep(1)
            cert = open(config.SSL_CERT, 'r') if config.SSL_CERT else None
            bot.set_webhook(url=f'https://{config.SERVER_IP}/{config.TOKEN}', certificate=cert)
            if cert: cert.close()
            app.run(host='0.0.0.0', port=config.SERVER_PORT)
        else:
            print("Starting polling...")
            bot.remove_webhook()
            bot.polling(none_stop=True)

    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)

if __name__ == '__main__':
    main()