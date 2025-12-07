# game_events.py
import random
import logging
from datetime import datetime, timedelta
import traceback

logger = logging.getLogger(__name__)

class GameEvent:
    def __init__(self, name, description, duration=1, is_positive=True):
        self.name = name
        self.description = description
        self.duration = duration
        self.activation_time = datetime.utcnow()
        self.is_positive = is_positive
        self.applied_effects = []

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

class TimeFreezeEvent(GameEvent):
    def __init__(self):
        super().__init__(
            "time_freeze",
            "⏱️ Замедление времени! Следующий день длится в 2 раза дольше.",
            duration=1,
            is_positive=True
        )

    def _apply_effect(self, game):
        game['day_duration_multiplier'] = 2
        return {"effect": "day_duration_doubled", "turns": 1}

class BlizzardEvent(GameEvent):
    def __init__(self):
        super().__init__(
            "blizzard",
            "❄️ Метель! Все игроки теряют 1 здоровье, кроме тех, кто у камина.",
            duration=0,
            is_positive=False
        )

    def _apply_effect(self, game):
        affected = []
        for i, player in enumerate(game['players']):
            if player.get('alive') and not player.get('by_fireplace', False):
                player['health'] = max(0, player.get('health', 1) - 1)
                affected.append(i)
        return {"effect": "damage_players", "damage": 1, "affected_players": affected}

class SantaWorkshopEvent(GameEvent):
    def __init__(self):
        super().__init__(
            "santa_workshop",
            "🎅 Мастерская Санты! Все специальные способности восстанавливаются.",
            duration=0,
            is_positive=True
        )

    def _apply_effect(self, game):
        reset_players = []
        for i, player in enumerate(game['players']):
            if player.get('alive') and player.get('ability_used', False):
                game['players'][i]['ability_used'] = False
                reset_players.append(i)
        return {"effect": "reset_abilities", "players_affected": reset_players}

def get_random_event():
    event_classes = [
        TimeFreezeEvent,
        BlizzardEvent,
        SantaWorkshopEvent
    ]
    return random.choice(event_classes)()