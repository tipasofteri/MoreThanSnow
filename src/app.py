# app.py content
import config
from .logger import logger
from .bot import bot
from .newyear_mafia import NewYearMafiaGame, GamePhase
from telebot.types import Update
import time
import threading
from flask import Flask, request, jsonify

# Initialize Flask app for web interface
app = Flask(__name__)

# In-memory storage for active games
active_games = {}

# Web API Routes
@app.route('/api/game/<int:chat_id>', methods=['GET'])
def get_game_status(chat_id):
    """Get current game status for web interface"""
    game = active_games.get(chat_id)
    if not game:
        return jsonify({"error": "Game not found"}), 404
    return jsonify(game.get_game_state())

@app.route('/api/player/<int:user_id>', methods=['GET'])
def get_player_info(user_id):
    """Get player info and role for web interface"""
    for game in active_games.values():
        player = next((p for p in game.players if p['id'] == user_id), None)
        if player:
            return jsonify({
                "name": player['name'],
                "role": player['role'].value if hasattr(player['role'], 'value') else str(player['role']),
                "alive": player.get('alive', True),
                "game_id": game.chat_id
            })
    return jsonify({"error": "Player not found"}), 404

def cleanup_inactive_games():
    """Periodically clean up inactive games"""
    while True:
        current_time = time.time()
        inactive_games = []
        
        for chat_id, game in list(active_games.items()):
            if hasattr(game, 'last_activity') and (current_time - game.last_activity) > 86400:
                inactive_games.append(chat_id)
        
        for chat_id in inactive_games:
            del active_games[chat_id]
            logger.info(f"Removed inactive game in chat {chat_id}")
        
        time.sleep(3600)

def start_web_interface():
    """Start the Flask web interface"""
    app.run(host='0.0.0.0', port=5000, debug=False)

def start_background_tasks():
    """Start all background tasks"""
    cleanup_thread = threading.Thread(target=cleanup_inactive_games, daemon=True)
    cleanup_thread.start()
    
    web_thread = threading.Thread(target=start_web_interface, daemon=True)
    web_thread.start()

def run_webhook():
    """Run the bot with webhook"""
    if config.SET_WEBHOOK:
        bot.remove_webhook()
        bot.set_webhook(url=config.WEBHOOK_URL + config.TOKEN)
        app.run(host='0.0.0.0', port=config.PORT, ssl_context=getattr(config, 'SSL_CONTEXT', None))
    else:
        bot.polling(none_stop=True)

def main():
    """Main entry point for the application"""
    logger.info("Starting New Year's Mafia Bot...")
    start_background_tasks()
    
    # Import handlers to register them
    from . import handlers
    
    # Start the bot
    if config.SET_WEBHOOK:
        logger.info("Running in webhook mode")
        run_webhook()
    else:
        logger.info("Running in polling mode")
        bot.polling(none_stop=True, interval=0, timeout=20)

# Webhook handler for production
@app.route(f'/{config.TOKEN}', methods=['POST'])
def webhook():
    """Handle incoming updates from Telegram"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return 'Bad Request', 400