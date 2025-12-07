# game_events.py
import random
import logging
from datetime import datetime, timedelta
import traceback
import database

logger = logging.getLogger(__name__)

class GameEvent:
    def __init__(self, name, description, duration=1, is_positive=True, rarity='common', seasonal=None, cost=30):
        self.name = name
        self.description = description
        self.duration = duration
        self.activation_time = datetime.utcnow()
        self.is_positive = is_positive
        self.applied_effects = []
        self.rarity = rarity  # common, rare, legendary
        self.seasonal = seasonal  # 'winter', 'summer', 'spring', 'autumn', None
        self.cost = cost

    def apply_effect(self, game):
        try:
            effect_result = self._apply_effect(game)
            self.applied_effects.append({
                'timestamp': datetime.utcnow().isoformat(),
                'effect': effect_result
            })
            logger.info(f"Applied effect for event {self.name}: {effect_result}")
            return effect_result
        except Exception as e:
            logger.error(f"Error applying event {self.name}: {str(e)}")
            logger.error(traceback.format_exc())
            return None

    def _apply_effect(self, game):
        return {"status": "no_effect"}

    def is_active(self):
        return (datetime.utcnow() - self.activation_time) < timedelta(hours=self.duration)

# Обычные события (common)
class TimeFreezeEvent(GameEvent):
    COST = 30
    def __init__(self):
        super().__init__(
            "time_freeze",
            "⏱️ Замедление времени! Следующий день длится в 2 раза дольше.",
            duration=1,
            is_positive=True,
            rarity='common',
            cost=30
        )
    def _apply_effect(self, game):
        if 'day_duration_multiplier' not in game:
            game['day_duration_multiplier'] = 1
        game['day_duration_multiplier'] = 2
        database.update_one('games', {'_id': game['_id']}, {'$set': {'day_duration_multiplier': 2}})
        return {"effect": "day_duration_doubled", "turns": 1}

class BlizzardEvent(GameEvent):
    COST = 30
    def __init__(self):
        super().__init__(
            "blizzard",
            "❄️ Метель! Случайный живой игрок заблокирован на следующую ночь.",
            duration=0,
            is_positive=False,
            rarity='common',
            seasonal='winter',
            cost=30
        )
    def _apply_effect(self, game):
        alive_players = [(i, p) for i, p in enumerate(game['players']) if p.get('alive')]
        if not alive_players:
            return {"effect": "no_targets", "affected_players": []}
        target_idx, target = random.choice(alive_players)
        if 'blizzard_blocked' not in game:
            game['blizzard_blocked'] = []
        if target['id'] not in game['blizzard_blocked']:
            game['blizzard_blocked'].append(target['id'])
            database.update_one('games', {'_id': game['_id']}, {'$set': {'blizzard_blocked': game['blizzard_blocked']}})
        return {"effect": "block_player", "target": target['name'], "target_idx": target_idx}

class DoubleVoteEvent(GameEvent):
    COST = 25
    def __init__(self):
        super().__init__(
            "double_vote",
            "🗳️ Двойное голосование! Следующее голосование будет проведено дважды.",
            duration=0,
            is_positive=True,
            rarity='common',
            cost=25
        )
    def _apply_effect(self, game):
        game['double_vote'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'double_vote': True}})
        return {"effect": "double_vote_enabled"}

class NightVisionEvent(GameEvent):
    COST = 35
    def __init__(self):
        super().__init__(
            "night_vision",
            "🌙 Ночное зрение! Комиссар может проверить двух игроков вместо одного в следующую ночь.",
            duration=0,
            is_positive=True,
            rarity='common',
            cost=35
        )
    def _apply_effect(self, game):
        game['commissar_double_check'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'commissar_double_check': True}})
        return {"effect": "commissar_double_check"}

class ProtectionEvent(GameEvent):
    COST = 40
    def __init__(self):
        super().__init__(
            "protection",
            "🛡️ Защита! Случайный живой игрок защищен от следующего убийства.",
            duration=0,
            is_positive=True,
            rarity='common',
            cost=40
        )
    def _apply_effect(self, game):
        alive_players = [(i, p) for i, p in enumerate(game['players']) if p.get('alive')]
        if alive_players:
            target_idx, target = random.choice(alive_players)
            if 'protected_players' not in game:
                game['protected_players'] = []
            game['protected_players'].append(target['id'])
            database.update_one('games', {'_id': game['_id']}, {'$set': {'protected_players': game['protected_players']}})
            return {"effect": "player_protected", "target": target['name']}
        return {"effect": "no_targets"}

class ConfusionEvent(GameEvent):
    COST = 30
    def __init__(self):
        super().__init__(
            "confusion",
            "🌀 Путаница! Все роли перемешаны - игроки видят чужие роли в следующую ночь.",
            duration=0,
            is_positive=False,
            rarity='common',
            cost=30
        )
    def _apply_effect(self, game):
        game['roles_confused'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'roles_confused': True}})
        return {"effect": "roles_confused"}

class ExtraTimeEvent(GameEvent):
    COST = 20
    def __init__(self):
        super().__init__(
            "extra_time",
            "⏰ Дополнительное время! Следующая фаза длится на 30 секунд дольше.",
            duration=0,
            is_positive=True,
            rarity='common',
            cost=20
        )
    def _apply_effect(self, game):
        game['extra_time'] = 30
        database.update_one('games', {'_id': game['_id']}, {'$set': {'extra_time': 30}})
        return {"effect": "extra_time_added", "seconds": 30}

# Редкие события (rare)
class SantaWorkshopEvent(GameEvent):
    COST = 50
    def __init__(self):
        super().__init__(
            "santa_workshop",
            "🎅 Мастерская Санты! Доктор может снова использовать самолечение, если уже использовал.",
            duration=0,
            is_positive=True,
            rarity='rare',
            seasonal='winter',
            cost=50
        )
    def _apply_effect(self, game):
        reset_players = []
        for i, player in enumerate(game['players']):
            if player.get('alive') and player.get('role') == 'doctor' and player.get('self_heal_used', False):
                game['players'][i]['self_heal_used'] = False
                database.update_one('games', {'_id': game['_id']}, {
                    '$set': {f'players.{i}.self_heal_used': False}
                })
                reset_players.append(i)
        return {"effect": "reset_self_heal", "players_affected": reset_players}

class ResurrectionEvent(GameEvent):
    COST = 80
    def __init__(self):
        super().__init__(
            "resurrection",
            "💀 Воскрешение! Последний убитый игрок возвращается в игру.",
            duration=0,
            is_positive=True,
            rarity='rare',
            cost=80
        )
    def _apply_effect(self, game):
        dead_players = [(i, p) for i, p in enumerate(game['players']) if not p.get('alive')]
        if dead_players:
            target_idx, target = dead_players[-1]
            game['players'][target_idx]['alive'] = True
            database.update_one('games', {'_id': game['_id']}, {'$set': {f'players.{target_idx}.alive': True}})
            return {"effect": "player_resurrected", "target": target['name']}
        return {"effect": "no_dead_players"}

class RoleRevealEvent(GameEvent):
    COST = 60
    def __init__(self):
        super().__init__(
            "role_reveal",
            "🔍 Раскрытие роли! Роль случайного живого игрока раскрывается всем.",
            duration=0,
            is_positive=True,
            rarity='rare',
            cost=60
        )
    def _apply_effect(self, game):
        alive_players = [(i, p) for i, p in enumerate(game['players']) if p.get('alive')]
        if alive_players:
            target_idx, target = random.choice(alive_players)
            game['revealed_roles'] = game.get('revealed_roles', [])
            game['revealed_roles'].append({'player_id': target['id'], 'role': target.get('role')})
            database.update_one('games', {'_id': game['_id']}, {'$set': {'revealed_roles': game['revealed_roles']}})
            return {"effect": "role_revealed", "target": target['name'], "role": target.get('role')}
        return {"effect": "no_targets"}

class MafiaRevealEvent(GameEvent):
    COST = 70
    def __init__(self):
        super().__init__(
            "mafia_reveal",
            "😈 Раскрытие мафии! Все мафиози раскрываются мирным игрокам.",
            duration=0,
            is_positive=True,
            rarity='rare',
            cost=70
        )
    def _apply_effect(self, game):
        mafia_players = [(i, p) for i, p in enumerate(game['players']) if p.get('role') in ('mafia', 'don') and p.get('alive')]
        if mafia_players:
            game['mafia_revealed'] = True
            database.update_one('games', {'_id': game['_id']}, {'$set': {'mafia_revealed': True}})
            return {"effect": "mafia_revealed", "count": len(mafia_players)}
        return {"effect": "no_mafia"}

class ImmunityEvent(GameEvent):
    COST = 75
    def __init__(self):
        super().__init__(
            "immunity",
            "✨ Иммунитет! Случайный живой игрок получает иммунитет от голосования на следующий день.",
            duration=0,
            is_positive=True,
            rarity='rare',
            cost=75
        )
    def _apply_effect(self, game):
        alive_players = [(i, p) for i, p in enumerate(game['players']) if p.get('alive')]
        if alive_players:
            target_idx, target = random.choice(alive_players)
            if 'immune_players' not in game:
                game['immune_players'] = []
            game['immune_players'].append(target['id'])
            database.update_one('games', {'_id': game['_id']}, {'$set': {'immune_players': game['immune_players']}})
            return {"effect": "player_immune", "target": target['name']}
        return {"effect": "no_targets"}

class DoubleKillEvent(GameEvent):
    COST = 90
    def __init__(self):
        super().__init__(
            "double_kill",
            "⚔️ Двойное убийство! Мафия может убить двух игроков вместо одного в следующую ночь.",
            duration=0,
            is_positive=False,
            rarity='rare',
            cost=90
        )
    def _apply_effect(self, game):
        game['mafia_double_kill'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'mafia_double_kill': True}})
        return {"effect": "mafia_double_kill_enabled"}

class LuckyDayEvent(GameEvent):
    COST = 55
    def __init__(self):
        super().__init__(
            "lucky_day",
            "🍀 Счастливый день! Все живые игроки получают случайный бонус.",
            duration=0,
            is_positive=True,
            rarity='rare',
            cost=55
        )
    def _apply_effect(self, game):
        alive_players = [p for p in game['players'] if p.get('alive')]
        bonuses = []
        for player in alive_players:
            bonus_type = random.choice(['candies', 'elo_boost'])
            if bonus_type == 'candies':
                stats = database.find_one('player_stats', {'user_id': player['id']})
                if stats:
                    bonus_amount = random.randint(3, 10)
                    new_candies = stats.get('candies', 0) + bonus_amount
                    database.update_one('player_stats', {'user_id': player['id']}, {'$set': {'candies': new_candies}})
                    bonuses.append({'player': player['name'], 'bonus': f"{bonus_amount} конфет"})
        return {"effect": "lucky_bonuses", "bonuses": bonuses}

# Легендарные события (legendary)
class TimeRewindEvent(GameEvent):
    COST = 150
    def __init__(self):
        super().__init__(
            "time_rewind",
            "⏪ Откат времени! Игра возвращается на предыдущую стадию.",
            duration=0,
            is_positive=True,
            rarity='legendary',
            cost=150
        )
    def _apply_effect(self, game):
        game['time_rewind'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'time_rewind': True}})
        return {"effect": "time_rewind_enabled"}

class AllRolesRevealEvent(GameEvent):
    COST = 200
    def __init__(self):
        super().__init__(
            "all_roles_reveal",
            "👁️ Всевидение! Все роли всех живых игроков раскрываются.",
            duration=0,
            is_positive=True,
            rarity='legendary',
            cost=200
        )
    def _apply_effect(self, game):
        alive_players = [(i, p) for i, p in enumerate(game['players']) if p.get('alive')]
        revealed = []
        for idx, player in alive_players:
            revealed.append({'player_id': player['id'], 'role': player.get('role')})
        game['all_roles_revealed'] = True
        game['revealed_roles'] = game.get('revealed_roles', []) + revealed
        database.update_one('games', {'_id': game['_id']}, {'$set': {'all_roles_revealed': True, 'revealed_roles': game['revealed_roles']}})
        return {"effect": "all_roles_revealed", "count": len(revealed)}

# Сезонные события - Зима
class SnowstormEvent(GameEvent):
    COST = 40
    def __init__(self):
        super().__init__(
            "snowstorm",
            "🌨️ Снежная буря! Все ночные действия отменяются в следующую ночь.",
            duration=0,
            is_positive=False,
            rarity='rare',
            seasonal='winter',
            cost=40
        )
    def _apply_effect(self, game):
        game['snowstorm'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'snowstorm': True}})
        return {"effect": "snowstorm_active"}

class GiftExchangeEvent(GameEvent):
    COST = 50
    def __init__(self):
        super().__init__(
            "gift_exchange",
            "🎁 Обмен подарками! Все живые игроки получают по 5 конфет.",
            duration=0,
            is_positive=True,
            rarity='rare',
            seasonal='winter',
            cost=50
        )
    def _apply_effect(self, game):
        alive_players = [p for p in game['players'] if p.get('alive')]
        for player in alive_players:
            stats = database.find_one('player_stats', {'user_id': player['id']})
            if stats:
                new_candies = stats.get('candies', 0) + 5
                database.update_one('player_stats', {'user_id': player['id']}, {'$set': {'candies': new_candies}})
        return {"effect": "gifts_given", "count": len(alive_players), "candies_per_player": 5}

class SilentNightEvent(GameEvent):
    COST = 40
    def __init__(self):
        super().__init__(
            "silent_night",
            "🤫 Тихая ночь! Все ночные способности работают в два раза медленнее.",
            duration=0,
            is_positive=False,
            rarity='common',
            seasonal='winter',
            cost=40
        )
    def _apply_effect(self, game):
        game['silent_night'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'silent_night': True}})
        return {"effect": "silent_night_active"}

# Сезонные события - Лето
class HeatWaveEvent(GameEvent):
    COST = 35
    def __init__(self):
        super().__init__(
            "heat_wave",
            "☀️ Волна жары! Все игроки теряют концентрацию - время на действия сокращается.",
            duration=0,
            is_positive=False,
            rarity='common',
            seasonal='summer',
            cost=35
        )
    def _apply_effect(self, game):
        game['heat_wave'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'heat_wave': True}})
        return {"effect": "heat_wave_active"}

class SummerFestivalEvent(GameEvent):
    COST = 45
    def __init__(self):
        super().__init__(
            "summer_festival",
            "🎉 Летний фестиваль! Все игроки получают бонус к ELO рейтингу за эту игру.",
            duration=0,
            is_positive=True,
            rarity='rare',
            seasonal='summer',
            cost=45
        )
    def _apply_effect(self, game):
        game['summer_festival'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'summer_festival': True}})
        return {"effect": "summer_festival_active"}

# Сезонные события - Весна
class SpringRainEvent(GameEvent):
    COST = 30
    def __init__(self):
        super().__init__(
            "spring_rain",
            "🌧️ Весенний дождь! Все способности работают с задержкой в следующую ночь.",
            duration=0,
            is_positive=False,
            rarity='common',
            seasonal='spring',
            cost=30
        )
    def _apply_effect(self, game):
        game['spring_rain'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'spring_rain': True}})
        return {"effect": "spring_rain_active"}

class BloomEvent(GameEvent):
    COST = 40
    def __init__(self):
        super().__init__(
            "bloom",
            "🌸 Цветение! Все живые игроки получают по 3 конфеты.",
            duration=0,
            is_positive=True,
            rarity='common',
            seasonal='spring',
            cost=40
        )
    def _apply_effect(self, game):
        alive_players = [p for p in game['players'] if p.get('alive')]
        for player in alive_players:
            stats = database.find_one('player_stats', {'user_id': player['id']})
            if stats:
                new_candies = stats.get('candies', 0) + 3
                database.update_one('player_stats', {'user_id': player['id']}, {'$set': {'candies': new_candies}})
        return {"effect": "bloom_bonus", "count": len(alive_players), "candies_per_player": 3}

# Сезонные события - Осень
class AutumnFogEvent(GameEvent):
    COST = 35
    def __init__(self):
        super().__init__(
            "autumn_fog",
            "🌫️ Осенний туман! Все проверки дают неверный результат в следующую ночь.",
            duration=0,
            is_positive=False,
            rarity='common',
            seasonal='autumn',
            cost=35
        )
    def _apply_effect(self, game):
        game['autumn_fog'] = True
        database.update_one('games', {'_id': game['_id']}, {'$set': {'autumn_fog': True}})
        return {"effect": "autumn_fog_active"}

class HarvestEvent(GameEvent):
    COST = 45
    def __init__(self):
        super().__init__(
            "harvest",
            "🌾 Урожай! Все живые игроки получают по 4 конфеты.",
            duration=0,
            is_positive=True,
            rarity='common',
            seasonal='autumn',
            cost=45
        )
    def _apply_effect(self, game):
        alive_players = [p for p in game['players'] if p.get('alive')]
        for player in alive_players:
            stats = database.find_one('player_stats', {'user_id': player['id']})
            if stats:
                new_candies = stats.get('candies', 0) + 4
                database.update_one('player_stats', {'user_id': player['id']}, {'$set': {'candies': new_candies}})
        return {"effect": "harvest_bonus", "count": len(alive_players), "candies_per_player": 4}

def get_current_season():
    """Определить текущий сезон"""
    month = datetime.now().month
    if month in (12, 1, 2):
        return 'winter'
    elif month in (3, 4, 5):
        return 'spring'
    elif month in (6, 7, 8):
        return 'summer'
    else:
        return 'autumn'

def get_random_event():
    """Получить случайное событие с учетом сезона и редкости"""
    current_season = get_current_season()
    
    # Все события
    all_events = [
        TimeFreezeEvent, BlizzardEvent, SantaWorkshopEvent,
        DoubleVoteEvent, NightVisionEvent, ProtectionEvent, ConfusionEvent, ExtraTimeEvent,
        ResurrectionEvent, RoleRevealEvent, MafiaRevealEvent, ImmunityEvent,
        TimeRewindEvent, AllRolesRevealEvent,
        SnowstormEvent, GiftExchangeEvent, SilentNightEvent,
        HeatWaveEvent, SummerFestivalEvent,
        SpringRainEvent, BloomEvent,
        AutumnFogEvent, HarvestEvent,
        DoubleKillEvent, LuckyDayEvent
    ]
    
    # Фильтруем по сезону
    seasonal_events = []
    for event_class in all_events:
        event_instance = event_class()
        if event_instance.seasonal is None or event_instance.seasonal == current_season:
            seasonal_events.append(event_class)
    
    # Взвешенный выбор по редкости
    common_events = []
    rare_events = []
    legendary_events = []
    
    for event_class in seasonal_events:
        event_instance = event_class()
        if event_instance.rarity == 'common':
            common_events.append(event_class)
        elif event_instance.rarity == 'rare':
            rare_events.append(event_class)
        elif event_instance.rarity == 'legendary':
            legendary_events.append(event_class)
    
    # Вероятности: 60% common, 30% rare, 10% legendary
    rand = random.random()
    if rand < 0.6 and common_events:
        return random.choice(common_events)()
    elif rand < 0.9 and rare_events:
        return random.choice(rare_events)()
    elif legendary_events:
        return random.choice(legendary_events)()
    else:
        # Fallback на любое событие
        return random.choice(seasonal_events)()

def get_event_by_name(event_name):
    """Получить класс события по имени"""
    events_map = {
        'time_freeze': TimeFreezeEvent,
        'blizzard': BlizzardEvent,
        'santa_workshop': SantaWorkshopEvent,
        'double_vote': DoubleVoteEvent,
        'night_vision': NightVisionEvent,
        'protection': ProtectionEvent,
        'confusion': ConfusionEvent,
        'extra_time': ExtraTimeEvent,
        'resurrection': ResurrectionEvent,
        'role_reveal': RoleRevealEvent,
        'mafia_reveal': MafiaRevealEvent,
        'immunity': ImmunityEvent,
        'time_rewind': TimeRewindEvent,
        'all_roles_reveal': AllRolesRevealEvent,
        'snowstorm': SnowstormEvent,
        'gift_exchange': GiftExchangeEvent,
        'silent_night': SilentNightEvent,
        'heat_wave': HeatWaveEvent,
        'summer_festival': SummerFestivalEvent,
        'spring_rain': SpringRainEvent,
        'bloom': BloomEvent,
        'autumn_fog': AutumnFogEvent,
        'harvest': HarvestEvent,
        'double_kill': DoubleKillEvent,
        'lucky_day': LuckyDayEvent
    }
    event_class = events_map.get(event_name)
    if event_class:
        return event_class()
    return None

def get_available_events():
    """Получить список доступных событий с ценами и редкостью"""
    current_season = get_current_season()
    
    all_events = [
        {'name': 'time_freeze', 'class': TimeFreezeEvent, 'cost': 30, 'description': '⏱️ Замедление времени! Следующий день длится в 2 раза дольше.', 'rarity': 'common', 'seasonal': None},
        {'name': 'blizzard', 'class': BlizzardEvent, 'cost': 30, 'description': '❄️ Метель! Случайный живой игрок заблокирован на следующую ночь.', 'rarity': 'common', 'seasonal': 'winter'},
        {'name': 'santa_workshop', 'class': SantaWorkshopEvent, 'cost': 50, 'description': '🎅 Мастерская Санты! Доктор может снова использовать самолечение.', 'rarity': 'rare', 'seasonal': 'winter'},
        {'name': 'double_vote', 'class': DoubleVoteEvent, 'cost': 25, 'description': '🗳️ Двойное голосование! Следующее голосование будет проведено дважды.', 'rarity': 'common', 'seasonal': None},
        {'name': 'night_vision', 'class': NightVisionEvent, 'cost': 35, 'description': '🌙 Ночное зрение! Комиссар может проверить двух игроков вместо одного.', 'rarity': 'common', 'seasonal': None},
        {'name': 'protection', 'class': ProtectionEvent, 'cost': 40, 'description': '🛡️ Защита! Случайный живой игрок защищен от следующего убийства.', 'rarity': 'common', 'seasonal': None},
        {'name': 'confusion', 'class': ConfusionEvent, 'cost': 30, 'description': '🌀 Путаница! Все роли перемешаны - игроки видят чужие роли.', 'rarity': 'common', 'seasonal': None},
        {'name': 'extra_time', 'class': ExtraTimeEvent, 'cost': 20, 'description': '⏰ Дополнительное время! Следующая фаза длится на 30 секунд дольше.', 'rarity': 'common', 'seasonal': None},
        {'name': 'resurrection', 'class': ResurrectionEvent, 'cost': 80, 'description': '💀 Воскрешение! Последний убитый игрок возвращается в игру.', 'rarity': 'rare', 'seasonal': None},
        {'name': 'role_reveal', 'class': RoleRevealEvent, 'cost': 60, 'description': '🔍 Раскрытие роли! Роль случайного живого игрока раскрывается всем.', 'rarity': 'rare', 'seasonal': None},
        {'name': 'mafia_reveal', 'class': MafiaRevealEvent, 'cost': 70, 'description': '😈 Раскрытие мафии! Все мафиози раскрываются мирным игрокам.', 'rarity': 'rare', 'seasonal': None},
        {'name': 'immunity', 'class': ImmunityEvent, 'cost': 75, 'description': '✨ Иммунитет! Случайный живой игрок получает иммунитет от голосования.', 'rarity': 'rare', 'seasonal': None},
        {'name': 'time_rewind', 'class': TimeRewindEvent, 'cost': 150, 'description': '⏪ Откат времени! Игра возвращается на предыдущую стадию.', 'rarity': 'legendary', 'seasonal': None},
        {'name': 'all_roles_reveal', 'class': AllRolesRevealEvent, 'cost': 200, 'description': '👁️ Всевидение! Все роли всех живых игроков раскрываются.', 'rarity': 'legendary', 'seasonal': None},
        {'name': 'snowstorm', 'class': SnowstormEvent, 'cost': 40, 'description': '🌨️ Снежная буря! Все ночные действия отменяются в следующую ночь.', 'rarity': 'rare', 'seasonal': 'winter'},
        {'name': 'gift_exchange', 'class': GiftExchangeEvent, 'cost': 50, 'description': '🎁 Обмен подарками! Все живые игроки получают по 5 конфет.', 'rarity': 'rare', 'seasonal': 'winter'},
        {'name': 'silent_night', 'class': SilentNightEvent, 'cost': 40, 'description': '🤫 Тихая ночь! Все ночные способности работают медленнее.', 'rarity': 'common', 'seasonal': 'winter'},
        {'name': 'heat_wave', 'class': HeatWaveEvent, 'cost': 35, 'description': '☀️ Волна жары! Время на действия сокращается.', 'rarity': 'common', 'seasonal': 'summer'},
        {'name': 'summer_festival', 'class': SummerFestivalEvent, 'cost': 45, 'description': '🎉 Летний фестиваль! Все игроки получают бонус к ELO рейтингу.', 'rarity': 'rare', 'seasonal': 'summer'},
        {'name': 'spring_rain', 'class': SpringRainEvent, 'cost': 30, 'description': '🌧️ Весенний дождь! Все способности работают с задержкой.', 'rarity': 'common', 'seasonal': 'spring'},
        {'name': 'bloom', 'class': BloomEvent, 'cost': 40, 'description': '🌸 Цветение! Все живые игроки получают по 3 конфеты.', 'rarity': 'common', 'seasonal': 'spring'},
        {'name': 'autumn_fog', 'class': AutumnFogEvent, 'cost': 35, 'description': '🌫️ Осенний туман! Все проверки дают неверный результат.', 'rarity': 'common', 'seasonal': 'autumn'},
        {'name': 'harvest', 'class': HarvestEvent, 'cost': 45, 'description': '🌾 Урожай! Все живые игроки получают по 4 конфеты.', 'rarity': 'common', 'seasonal': 'autumn'},
        {'name': 'double_kill', 'class': DoubleKillEvent, 'cost': 90, 'description': '⚔️ Двойное убийство! Мафия может убить двух игроков вместо одного.', 'rarity': 'rare', 'seasonal': None},
        {'name': 'lucky_day', 'class': LuckyDayEvent, 'cost': 55, 'description': '🍀 Счастливый день! Все живые игроки получают случайный бонус.', 'rarity': 'rare', 'seasonal': None}
    ]
    
    # Фильтруем по сезону
    available = [e for e in all_events if e['seasonal'] is None or e['seasonal'] == current_season]
    
    return available
