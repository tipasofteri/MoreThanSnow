import os
import sys
from time import time, sleep
from threading import Thread
import flask
from telebot import logger
from telebot.types import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiException

# Add the current directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

import config
import database
from handlers import bot, get_time_str
from game import stop_game
from stages import go_to_next_stage, update_timer
import lang

# Flask app initialization 
app = flask.Flask(__name__)

def update_request_timer(request):
    """Обновить таймер в сообщении заявки"""
    try:
        current_time = time()
        remaining = int(request['time'] - current_time)
        
        if remaining <= 0:
            # Время истекло, удаляем заявку
            database.delete_one('requests', {'_id': request['_id']})
            try:
                bot.edit_message_text(
                    '⏰ Время истекло! Заявка удалена.',
                    request['chat'],
                    request['message_id'],
                    parse_mode='HTML'
                )
            except:
                pass
            return
        
        time_str = get_time_str(request['time'])
        players_list = request.get('players', [])
        formatted_list = '\n'.join([f'{i+1}. {p["name"]}' for i, p in enumerate(players_list)])
        
        text = lang.game_created.format(
            owner=request['owner']['name'],
            time=time_str,
            order=f'Игроки ({len(players_list)}/{config.PLAYERS_COUNT_LIMIT}):\n{formatted_list}'
        )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text='🎮 Вступить', callback_data='request interact'))
        
        # Кнопка старта для создателя
        if len(players_list) >= config.PLAYERS_COUNT_TO_START:
            keyboard.add(InlineKeyboardButton(text='▶️ Начать игру', callback_data='start game'))
        
        try:
            bot.edit_message_text(
                text=text,
                chat_id=request['chat'],
                message_id=request['message_id'],
                reply_markup=keyboard,
                parse_mode='HTML'
            )
        except ApiException as e:
            # Обработка ошибки 429 (Too Many Requests)
            error_code = e.result.get('error_code', 0) if hasattr(e, 'result') and isinstance(e.result, dict) else 0
            if error_code == 429:
                retry_after = e.result.get('parameters', {}).get('retry_after', 1) if hasattr(e, 'result') and isinstance(e.result, dict) else 1
                logger.warning(f"Rate limit hit, waiting {retry_after} seconds")
                sleep(retry_after)
            else:
                pass  # Сообщение могло быть удалено или изменено
    except Exception as e:
        logger.debug(f"Error updating request timer: {e}")

def stage_cycle():
    """Главный цикл смены стадий игры + Обновление таймеров"""
    last_timer_update = time()
    last_request_update = time()
    
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
            
            # 3. Обновляем таймеры заявок каждые 5 секунд (чтобы не превышать лимиты API)
            if current_time - last_request_update >= 5:
                active_requests = database.find('requests', {'time': {'$gt': current_time}})
                for request in active_requests:
                    try:
                        update_request_timer(request)
                        sleep(0.1)  # Небольшая задержка между обновлениями
                    except Exception:
                        pass
                last_request_update = current_time

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

def daily_events():
    """Ежедневные случайные события (дроп конфет в группах)"""
    from datetime import datetime
    import random
    
    last_daily_event = None
    
    while True:
        try:
            now = datetime.now()
            current_hour = now.hour
            current_minute = now.minute
            
            # Проверяем, наступил ли новый день (00:00) и не отправляли ли уже сегодня
            if current_hour == 0 and current_minute == 0:
                today = now.date().isoformat()
                
                # Проверяем, не отправляли ли уже сегодня
                daily_events_log = database.find_one('daily_events', {'date': today})
                if daily_events_log:
                    sleep(60)  # Спим минуту, чтобы не повторять
                    continue
                
                # Получаем все активные группы (где были игры)
                all_games = database.find('games', {'game': 'mafia'})
                active_chats = set()
                for game in all_games:
                    chat_id = game.get('chat')
                    if chat_id:
                        active_chats.add(chat_id)
                
                # Также проверяем заявки
                all_requests = database.find('requests', {})
                for req in all_requests:
                    chat_id = req.get('chat')
                    if chat_id:
                        active_chats.add(chat_id)
                
                # Отправляем случайный дроп конфет в каждую группу
                for chat_id in active_chats:
                    try:
                        # Случайное количество конфет (5-20)
                        candies_amount = random.randint(5, 20)
                        
                        # Случайное событие
                        event_messages = [
                            f"🎁 <b>Ежедневный подарок!</b>\n\nСегодня в группе выпало {candies_amount} 🍭 конфет!\n\n💡 Нажмите кнопку ниже, чтобы забрать!",
                            f"🍭 <b>Случайный дроп!</b>\n\nВ группе появилось {candies_amount} 🍭 конфет!\n\n💡 Нажмите кнопку, чтобы забрать!",
                            f"🎉 <b>Ежедневная награда!</b>\n\nГруппа получила {candies_amount} 🍭 конфет!\n\n💡 Нажмите кнопку для получения!"
                        ]
                        
                        message_text = random.choice(event_messages)
                        
                        # Сохраняем информацию о дропе
                        drop_info = {
                            'chat_id': chat_id,
                            'candies': candies_amount,
                            'date': today,
                            'claimed': False,
                            'claimed_by': None
                        }
                        database.insert_one('daily_drops', drop_info)
                        
                        # Создаем inline кнопку
                        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
                        kb = InlineKeyboardMarkup(row_width=1)
                        kb.add(InlineKeyboardButton(
                            f"🎁 Забрать {candies_amount} 🍭",
                            callback_data=f'daily_claim_{chat_id}'
                        ))
                        
                        # Отправляем сообщение с кнопкой
                        bot.send_message(chat_id, message_text, parse_mode='HTML', reply_markup=kb)
                        
                        sleep(0.5)  # Небольшая задержка между отправками
                    except Exception as e:
                        logger.debug(f"Error sending daily event to chat {chat_id}: {e}")
                
                # Сохраняем, что сегодня уже отправили
                database.insert_one('daily_events', {'date': today, 'sent_at': now.isoformat()})
                
                last_daily_event = today
            
            sleep(60)  # Проверяем каждую минуту
            
        except Exception as e:
            logger.error(f"Error in daily_events: {e}")
            sleep(300)  # При ошибке ждем 5 минут

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
        start_thread('Daily Events', daily_events)
        
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
            # Очищаем webhook перед запуском polling
            try:
                bot.remove_webhook()
                sleep(1)  # Даем время на очистку webhook
            except Exception as e:
                logger.warning(f"Error removing webhook: {e}")
            
            try:
                bot.polling(none_stop=True, interval=1, timeout=20)
            except KeyboardInterrupt:
                print("\nShutting down bot...")
                bot.stop_polling()
                logger.info("Bot stopped by user")
            except ApiException as e:
                # Проверяем код ошибки из result
                error_code = e.result.get('error_code') if hasattr(e, 'result') and e.result else None
                if error_code == 409 or "Conflict" in str(e) or "409" in str(e):
                    logger.error("409 Conflict: Another bot instance is running. Please stop it first.")
                    print("\n❌ Ошибка: Другой экземпляр бота уже запущен!")
                    print("   Остановите все запущенные экземпляры бота и попробуйте снова.")
                    print("   Или подождите несколько секунд и перезапустите бота.")
                    sys.exit(1)
                else:
                    raise
            except Exception as e:
                if "409" in str(e) or "Conflict" in str(e):
                    logger.error("409 Conflict: Another bot instance is running. Please stop it first.")
                    print("\n❌ Ошибка: Другой экземпляр бота уже запущен!")
                    print("   Остановите все запущенные экземпляры бота и попробуйте снова.")
                    print("   Или подождите несколько секунд и перезапустите бота.")
                    sys.exit(1)
                else:
                    raise

    except KeyboardInterrupt:
        print("\nShutting down bot...")
        bot.stop_polling()
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)

if __name__ == '__main__':
    main()