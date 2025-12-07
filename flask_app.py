"""
Flask WebApp - Информационный сайт + простое API статистики бота.
"""
import os
import sys
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template, request

# Пути
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

mybot_src = os.path.join(current_dir, 'mybot', 'src')
if mybot_src not in sys.path:
    sys.path.append(mybot_src)

from database import Database  # noqa: E402

# Создаем Flask приложение
# На PythonAnywhere приложение должно быть в переменной 'app'
app = Flask(
    __name__,
    template_folder='templates',
    static_folder='templates/static'
)
app.secret_key = os.getenv('SECRET_KEY', os.urandom(24).hex())

# Хранилище данных (JSON файлы)
db = Database(db_path=os.path.join(current_dir, 'mybot', 'data'))

# Простой кэш в памяти (для лидерборда/метрик)
_cache: Dict[str, Dict[str, Any]] = {}


def _cache_get(key: str, ttl: int) -> Optional[Any]:
    item = _cache.get(key)
    if not item:
        return None
    if time.time() - item['ts'] > ttl:
        return None
    return item['value']


def _cache_set(key: str, value: Any):
    _cache[key] = {'value': value, 'ts': time.time()}


# ==================== FRONTEND ROUTES ====================

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/rules')
def rules():
    """Страница с правилами игры"""
    return render_template('rules.html')


@app.route('/updates')
def updates():
    """Страница с последними обновлениями"""
    return render_template('updates.html')


@app.route('/about')
def about():
    """Страница о проекте"""
    return render_template('about.html')


@app.route('/profile')
def profile():
    """Страница профиля игрока (грузит данные через API)"""
    user_id = request.args.get('user_id', '')
    return render_template('profile.html', user_id=user_id)


@app.route('/leaderboard')
def leaderboard_page():
    """Страница лидерборда (использует API)"""
    return render_template('leaderboard.html')


# ==================== API ====================

@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/api/stats/<int:user_id>')
def api_stats(user_id: int):
    stats = db.find_one('player_stats', {'user_id': user_id})
    if not stats:
        return jsonify({'error': 'not found'}), 404
    return jsonify(stats)


@app.route('/api/leaderboard')
def api_leaderboard():
    limit = int(request.args.get('limit', 10))
    sort = request.args.get('sort', 'elo')  # elo | games | candies
    cache_key = f'leaderboard:{sort}'
    cached = _cache_get(cache_key, ttl=30)
    if cached:
        return jsonify(cached[:limit])

    all_stats = db.find('player_stats', {})
    if sort == 'games':
        all_stats.sort(key=lambda x: x.get('games_played', 0), reverse=True)
    elif sort == 'candies':
        all_stats.sort(key=lambda x: x.get('candies', 0), reverse=True)
    else:
        all_stats.sort(key=lambda x: x.get('elo_rating', 0), reverse=True)
    result = [{
        'user_id': s.get('user_id'),
        'name': s.get('name', 'Игрок'),
        'games_played': s.get('games_played', 0),
        'games_won': s.get('games_won', 0),
        'elo_rating': s.get('elo_rating', 0),
        'candies': s.get('candies', 0),
    } for s in all_stats[:limit]]
    _cache_set(cache_key, result)
    return jsonify(result)


@app.route('/api/search_players')
def api_search_players():
    q = (request.args.get('q') or '').strip().lower()
    limit = int(request.args.get('limit', 20))
    if not q:
        return jsonify([])
    all_stats = db.find('player_stats', {})
    matched = []
    for s in all_stats:
        name = (s.get('name') or '').lower()
        if q in name:
            matched.append({
                'user_id': s.get('user_id'),
                'name': s.get('name', 'Игрок'),
                'elo_rating': s.get('elo_rating', 0),
                'games_played': s.get('games_played', 0),
            })
        if len(matched) >= limit:
            break
    return jsonify(matched)


@app.route('/api/metrics')
def api_metrics():
    cached = _cache_get('metrics', ttl=30)
    if cached:
        return jsonify(cached)
    players = db.find('player_stats', {})
    games = db.find('games', {})
    total_players = len(players)
    total_games = len(games)
    total_candies = sum(p.get('candies', 0) for p in players)
    roles_set = set()
    for p in players:
        roles_set.update((p.get('roles_played') or {}).keys())
    metrics = {
        'players': total_players,
        'games': total_games,
        'roles': len(roles_set),
        'candies': total_candies,
    }
    _cache_set('metrics', metrics)
    return jsonify(metrics)


# ==================== STATIC FILES ====================

@app.route('/static/<path:filename>')
def static_files(filename):
    """Отдача статических файлов"""
    return app.send_static_file(filename)


if __name__ == '__main__':
    app.run(debug=True)