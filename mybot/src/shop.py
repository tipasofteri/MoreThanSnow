# shop.py
"""
Система магазина для игры в мафию
"""
import database
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import random

# Определение товаров магазина
SHOP_ITEMS = {
    # Бейджи
    'badge_veteran': {
        'id': 'badge_veteran',
        'name': 'Бейдж Ветерана',
        'description': 'Особая иконка рядом с вашим именем',
        'type': 'badge',
        'icon': '🎖️',
        'cost_candies': 100,
        'cost_stars': None,
        'rarity': 'common'
    },
    'badge_champion': {
        'id': 'badge_champion',
        'name': 'Бейдж Чемпиона',
        'description': 'Эксклюзивный бейдж для победителей',
        'type': 'badge',
        'icon': '🏆',
        'cost_candies': 250,
        'cost_stars': None,
        'rarity': 'rare'
    },
    'badge_legend': {
        'id': 'badge_legend',
        'name': 'Бейдж Легенды',
        'description': 'Легендарный бейдж для лучших игроков',
        'type': 'badge',
        'icon': '👑',
        'cost_candies': 500,
        'cost_stars': None,
        'rarity': 'legendary'
    },
    
    # Титулы
    'title_mafia_boss': {
        'id': 'title_mafia_boss',
        'name': 'Титул: Босс Мафии',
        'description': 'Особый титул, отображаемый в профиле',
        'type': 'title',
        'icon': '🎩',
        'cost_candies': 150,
        'cost_stars': None,
        'rarity': 'uncommon'
    },
    'title_commissar': {
        'id': 'title_commissar',
        'name': 'Титул: Комиссар',
        'description': 'Титул защитника порядка',
        'type': 'title',
        'icon': '🎅',
        'cost_candies': 150,
        'cost_stars': None,
        'rarity': 'uncommon'
    },
    'title_doctor': {
        'id': 'title_doctor',
        'name': 'Титул: Доктор',
        'description': 'Титул спасителя жизней',
        'type': 'title',
        'icon': '🧦',
        'cost_candies': 150,
        'cost_stars': None,
        'rarity': 'uncommon'
    },
    
    # Кейсы с событиями
    'case_common': {
        'id': 'case_common',
        'name': 'Обычный кейс',
        'description': 'Содержит случайное обычное событие',
        'type': 'case',
        'icon': '📦',
        'cost_candies': 50,
        'cost_stars': None,
        'rarity': 'common',
        'event_rarity': 'common'
    },
    'case_rare': {
        'id': 'case_rare',
        'name': 'Редкий кейс',
        'description': 'Содержит случайное редкое событие',
        'type': 'case',
        'icon': '💎',
        'cost_candies': 150,
        'cost_stars': None,
        'rarity': 'rare',
        'event_rarity': 'rare'
    },
    'case_legendary': {
        'id': 'case_legendary',
        'name': 'Легендарный кейс',
        'description': 'Содержит случайное легендарное событие',
        'type': 'case',
        'icon': '🌟',
        'cost_candies': 300,
        'cost_stars': None,
        'rarity': 'legendary',
        'event_rarity': 'legendary'
    },
    
    # Покупка конфет за Звезды Telegram
    'candies_1000': {
        'id': 'candies_1000',
        'name': '1000 конфет',
        'description': 'Пакет конфет для покупок',
        'type': 'candies',
        'icon': '🍭',
        'cost_candies': None,
        'cost_stars': 3,
        'amount': 1000,
        'rarity': 'common'
    },
    'candies_2500': {
        'id': 'candies_2500',
        'name': '2500 конфет',
        'description': 'Большой пакет конфет',
        'type': 'candies',
        'icon': '🍬',
        'cost_candies': None,
        'cost_stars': 6,
        'amount': 2500,
        'rarity': 'uncommon'
    },
    'candies_10000': {
        'id': 'candies_10000',
        'name': '10000 конфет',
        'description': 'Огромный пакет конфет',
        'type': 'candies',
        'icon': '🎁',
        'cost_candies': None,
        'cost_stars': 15,
        'amount': 10000,
        'rarity': 'rare'
    },
}

# Ограниченные предложения (обновляются ежедневно)
LIMITED_OFFERS = {
    'offer_event_discount': {
        'id': 'offer_event_discount',
        'name': '🔥 Скидка на события',
        'description': 'Все события со скидкой 30%',
        'type': 'discount',
        'discount_percent': 30,
        'valid_until': None,  # Устанавливается при создании
        'cost_candies': 0  # Бесплатно, но ограничено по времени
    }
}

def get_shop_items(category: Optional[str] = None) -> List[Dict]:
    """Получить товары магазина, опционально отфильтрованные по категории"""
    items = list(SHOP_ITEMS.values())
    if category:
        items = [item for item in items if item.get('type') == category]
    return items

def get_limited_offers() -> List[Dict]:
    """Получить активные ограниченные предложения"""
    offers = []
    for offer_id, offer in LIMITED_OFFERS.items():
        if offer.get('valid_until'):
            valid_until = datetime.fromisoformat(offer['valid_until'])
            if datetime.now() < valid_until:
                offers.append(offer)
        else:
            offers.append(offer)
    return offers

def purchase_item(user_id: int, item_id: str, payment_type: str = 'candies') -> Tuple[bool, str, Optional[Dict]]:
    """
    Купить товар в магазине
    
    Args:
        user_id: ID пользователя
        item_id: ID товара
        payment_type: 'candies' или 'stars'
    
    Returns:
        (success, message, item_data)
    """
    if item_id not in SHOP_ITEMS:
        return False, "❌ Товар не найден", None
    
    item = SHOP_ITEMS[item_id]
    
    # Получаем статистику игрока
    stats = database.find_one('player_stats', {'user_id': user_id})
    if not stats:
        return False, "❌ Статистика не найдена. Сыграйте хотя бы одну игру.", None
    
    # Проверяем способ оплаты
    if payment_type == 'candies':
        if item.get('cost_candies') is None:
            return False, "❌ Этот товар нельзя купить за конфеты", None
        
        candies = stats.get('candies', 0)
        cost = item['cost_candies']
        
        if candies < cost:
            return False, f"❌ Недостаточно конфет. Нужно: {cost} 🍭, у вас: {candies} 🍭", None
        
        # Списываем конфеты
        new_candies = candies - cost
        database.update_one('player_stats', {'user_id': user_id}, {
            '$set': {'candies': new_candies}
        })
        
    elif payment_type == 'stars':
        if item.get('cost_stars') is None:
            return False, "❌ Этот товар нельзя купить за Звезды", None
        
        # Покупка за звезды обрабатывается через invoice в handlers.py
        # Эта функция не должна вызываться для stars
        return False, "❌ Используйте кнопку покупки или команду /shop для покупки за звезды", None
    
    else:
        return False, "❌ Неверный способ оплаты", None
    
    # Выдаем товар
    if item['type'] == 'badge':
        # Добавляем бейдж в инвентарь
        inventory = stats.get('inventory', {})
        badges = inventory.get('badges', [])
        if item_id not in badges:
            badges.append(item_id)
            inventory['badges'] = badges
            database.update_one('player_stats', {'user_id': user_id}, {
                '$set': {'inventory': inventory}
            })
        return True, f"Вы купили {item['icon']} {item['name']}!", item
    
    elif item['type'] == 'title':
        # Добавляем титул в инвентарь
        inventory = stats.get('inventory', {})
        titles = inventory.get('titles', [])
        if item_id not in titles:
            titles.append(item_id)
            inventory['titles'] = titles
            database.update_one('player_stats', {'user_id': user_id}, {
                '$set': {'inventory': inventory}
            })
        return True, f"Вы купили {item['icon']} {item['name']}!", item
    
    elif item['type'] == 'case':
        # Открываем кейс и выдаем случайное событие
        try:
            from game_events import get_available_events
            events = get_available_events()
            event_rarity = item.get('event_rarity', 'common')
            
            # Фильтруем события по редкости
            filtered_events = [e for e in events if e.get('rarity') == event_rarity]
            if not filtered_events:
                # Если нет событий нужной редкости, берем любые
                filtered_events = events
            
            if filtered_events:
                random_event = random.choice(filtered_events)
                event_name = random_event.get('name', 'Событие')
                
                # Добавляем событие в инвентарь
                inventory = stats.get('inventory', {})
                events = inventory.get('events', [])
                events.append({
                    'event_id': random_event.get('id', 'unknown'),
                    'event_name': event_name,
                    'purchased_at': datetime.now().isoformat()
                })
                inventory['events'] = events
                database.update_one('player_stats', {'user_id': user_id}, {
                    '$set': {'inventory': inventory}
                })
                
                return True, f"Вы открыли {item['icon']} {item['name']} и получили: {event_name}!", random_event
            else:
                return False, "❌ Ошибка: не найдено событий для выдачи", None
        except Exception as e:
            return False, f"❌ Ошибка при открытии кейса: {str(e)}", None
    
    elif item['type'] == 'candies':
        # Выдаем конфеты
        amount = item.get('amount', 0)
        current_candies = stats.get('candies', 0)
        new_candies = current_candies + amount
        database.update_one('player_stats', {'user_id': user_id}, {
            '$set': {'candies': new_candies}
        })
        return True, f"Вы получили {amount} 🍭 конфет! Теперь у вас: {new_candies} 🍭", item
    
    return False, "❌ Неизвестный тип товара", None

def get_user_inventory(user_id: int) -> Dict:
    """Получить инвентарь пользователя"""
    stats = database.find_one('player_stats', {'user_id': user_id})
    if not stats:
        return {'badges': [], 'titles': [], 'events': []}
    
    inventory = stats.get('inventory', {})
    return {
        'badges': inventory.get('badges', []),
        'titles': inventory.get('titles', []),
        'events': inventory.get('events', [])
    }

def get_user_badges(user_id: int) -> List[str]:
    """Получить список бейджей пользователя"""
    inventory = get_user_inventory(user_id)
    return inventory.get('badges', [])

def get_user_titles(user_id: int) -> List[str]:
    """Получить список титулов пользователя"""
    inventory = get_user_inventory(user_id)
    return inventory.get('titles', [])

def get_user_events(user_id: int) -> List[Dict]:
    """Получить список купленных событий пользователя"""
    inventory = get_user_inventory(user_id)
    return inventory.get('events', [])

def create_limited_offer(offer_id: str, duration_hours: int = 24) -> bool:
    """Создать ограниченное предложение на определенное время"""
    if offer_id not in LIMITED_OFFERS:
        return False
    
    offer = LIMITED_OFFERS[offer_id].copy()
    offer['valid_until'] = (datetime.now() + timedelta(hours=duration_hours)).isoformat()
    
    # Сохраняем в базу данных
    database.update_one('shop_offers', {'offer_id': offer_id}, {
        '$set': offer
    }, upsert=True)
    
    return True

def get_active_limited_offers() -> List[Dict]:
    """Получить активные ограниченные предложения из базы данных"""
    offers = database.find('shop_offers', {})
    active_offers = []
    
    for offer in offers:
        valid_until = offer.get('valid_until')
        if valid_until:
            try:
                valid_until_dt = datetime.fromisoformat(valid_until)
                if datetime.now() < valid_until_dt:
                    active_offers.append(offer)
            except:
                pass
    
    return active_offers

def find_item_by_name(item_name: str) -> Optional[Dict]:
    """Найти товар по названию (частичное совпадение)"""
    item_name_lower = item_name.lower().strip()
    
    # Сначала ищем точное совпадение
    for item_id, item in SHOP_ITEMS.items():
        if item['name'].lower() == item_name_lower:
            return item
    
    # Затем ищем частичное совпадение
    for item_id, item in SHOP_ITEMS.items():
        if item_name_lower in item['name'].lower() or item['name'].lower() in item_name_lower:
            return item
    
    return None

