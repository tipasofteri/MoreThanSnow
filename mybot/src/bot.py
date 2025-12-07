import config
from logger import logger
import database

from telebot import TeleBot
from telebot.apihelper import ApiException

# Константы стадий (лучше вынести их в config или game, но для наглядности здесь)
STAGE_LOBBY = 0
STAGE_DAY = 1
STAGE_NIGHT = 2
STAGE_VOTE = 3
STAGE_LAST_WORD = 7
STAGE_ENDING = -4

def group_only(message):
    return message.chat.type in ('group', 'supergroup')

class MafiaHostBot(TeleBot):
    def try_to_send_message(self, *args, **kwargs):
        try:
            return self.send_message(*args, **kwargs)
        except ApiException as e:
            # Логируем только реальные ошибки, игнорируем, если бот заблокирован пользователем
            error_code = e.result.get('error_code', 0) if hasattr(e, 'result') and isinstance(e.result, dict) else 0
            if error_code != 403:
                logger.error(f'Ошибка API при отправке сообщения: {e}', exc_info=False)

    def _game_handler(self, handler):
        def decorator(message, *args, **kwargs):
            # 1. Получаем игру
            game = database.find_one('games', {'chat': message.chat.id})
            
            # Если игры нет или это не мафия — пропускаем к хендлеру (пусть обрабатывает команды)
            if not game or game.get('game') != 'mafia':
                return handler(message, game, *args, **kwargs)

            stage = game.get('stage', 0)
            user_id = message.from_user.id
            
            # 2. Ищем игрока
            # Используем next с дефолтным значением None, чтобы не ловить StopIteration
            player = next((p for p in game.get('players', []) if p.get('id') == user_id), None)

            should_delete = False

            # --- ЛОГИКА УДАЛЕНИЯ СООБЩЕНИЙ ---
            
            # Сценарий А: Человек НЕ в игре (зритель)
            if player is None:
                # Если настройка запрещает писать зрителям и игра идет (не лобби)
                if config.DELETE_FROM_EVERYONE and stage not in (STAGE_LOBBY, STAGE_ENDING):
                    should_delete = True

            # Сценарий Б: Игрок в игре
            else:
                is_alive = player.get('alive', True)
                
                # 1. Мертвые молчат всегда (кроме Лобби и Конца)
                if not is_alive and stage not in (STAGE_LOBBY, STAGE_ENDING):
                    should_delete = True
                
                # 2. Ночь (Stage 2): Молчат ВСЕ (и живые, и мертвые)
                elif stage == STAGE_NIGHT:
                    should_delete = True
                    
                # 3. Последнее слово (Stage 7): Говорит ТОЛЬКО жертва
                elif stage == STAGE_LAST_WORD:
                    victim_id = game.get('victim')
                    # Если ты не жертва — молчишь
                    if victim_id and user_id != victim_id:
                        should_delete = True

            # --- ИТОГ ---
            if should_delete:
                self.safely_delete_message(chat_id=message.chat.id, message_id=message.message_id)
                return

            return handler(message, game, *args, **kwargs)
        return decorator

    def group_message_handler(self, *, func=None, **kwargs):
        def decorator(handler):
            if func is None:
                conjuction = group_only
            else:
                # Объединяем проверку на группу и пользовательскую функцию
                conjuction = lambda message: group_only(message) and func(message)

            # Оборачиваем сначала в логику игры, потом регистрируем
            new_handler = self._game_handler(handler)
            handler_dict = self._build_handler_dict(new_handler, func=conjuction, **kwargs)
            self.add_message_handler(handler_dict)
            return new_handler
        return decorator

    def safely_delete_message(self, *args, **kwargs):
        try:
            self.delete_message(*args, **kwargs)
        except ApiException as e:
            # Часто бывает, что сообщение уже удалено или у бота нет прав админа
            # error_code 400: Message to delete not found
            if "message to delete not found" not in str(e).lower():
                logger.debug(f'Не удалось удалить сообщение: {e}')

bot = MafiaHostBot(config.TOKEN, skip_pending=config.SKIP_PENDING)