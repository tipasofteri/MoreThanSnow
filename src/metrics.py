# metrics.py
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class GameMetrics:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GameMetrics, cls).__new__(cls)
            cls._instance.metrics = {
                'games_started': 0,
                'games_completed': 0,
                'events_triggered': {},
                'role_actions': {},
                'errors': 0
            }
        return cls._instance
    
    def increment(self, metric, tags=None):
        try:
            if metric not in self._instance.metrics:
                if isinstance(self._instance.metrics.get(metric), dict):
                    tag_key = tuple(sorted(tags.items())) if tags else 'default'
                    self._instance.metrics[metric][tag_key] = self._instance.metrics[metric].get(tag_key, 0) + 1
                else:
                    self._instance.metrics[metric] = 0
            self._instance.metrics[metric] += 1
            
            logger.info(f"METRIC: {metric} increased to {self._instance.metrics[metric]}")
            
            if metric == 'games_started':
                self._log_game_start(tags)
            elif metric == 'errors':
                logger.error(f"Error occurred: {tags}")
                
        except Exception as e:
            logger.error(f"Error in metrics: {str(e)}")

    def _log_game_start(self, tags):
        game_info = {
            'mode': tags.get('mode', 'unknown'),
            'player_count': tags.get('player_count', 0),
            'timestamp': datetime.utcnow().isoformat()
        }
        logger.info(f"GAME_START: {game_info}")

metrics = GameMetrics()