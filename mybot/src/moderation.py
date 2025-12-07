# moderation.py
"""
Система модерации и жалоб для игры в мафию
"""
import database
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
# Получаем ID администратора из конфига
try:
    import config
    ADMIN_ID = config.ADMIN_ID
except:
    # Если config не найден, используем значение по умолчанию
    ADMIN_ID = None

def is_moderator(user_id: int) -> bool:
    """Проверить, является ли пользователь модератором"""
    if user_id == ADMIN_ID:
        return True
    
    mod = database.find_one('moderators', {'user_id': user_id})
    return mod is not None

def add_moderator(user_id: int, added_by: int) -> Tuple[bool, str]:
    """
    Добавить модератора
    
    Returns:
        (success: bool, message: str)
    """
    # Только админ может добавлять модераторов
    if added_by != ADMIN_ID:
        return False, "Только администратор может добавлять модераторов"
    
    # Проверяем, не является ли уже модератором
    if is_moderator(user_id):
        return False, "Пользователь уже является модератором"
    
    # Получаем информацию о пользователе
    user_stats = database.find_one('player_stats', {'user_id': user_id})
    user_name = user_stats.get('name', 'Игрок') if user_stats else 'Игрок'
    
    mod = {
        'user_id': user_id,
        'name': user_name,
        'added_by': added_by,
        'added_at': datetime.now().isoformat()
    }
    
    database.insert_one('moderators', mod)
    return True, f"Модератор {user_name} добавлен"

def remove_moderator(user_id: int, removed_by: int) -> Tuple[bool, str]:
    """
    Удалить модератора
    
    Returns:
        (success: bool, message: str)
    """
    # Только админ может удалять модераторов
    if removed_by != ADMIN_ID:
        return False, "Только администратор может удалять модераторов"
    
    mod = database.find_one('moderators', {'user_id': user_id})
    if not mod:
        return False, "Пользователь не является модератором"
    
    database.delete_one('moderators', {'user_id': user_id})
    return True, f"Модератор {mod.get('name', 'Игрок')} удален"

def report_player(reporter_id: int, reported_id: int, reason: str) -> Tuple[bool, str]:
    """
    Пожаловаться на игрока
    
    Returns:
        (success: bool, message: str)
    """
    if reporter_id == reported_id:
        return False, "Нельзя пожаловаться на самого себя"
    
    # Получаем информацию о жалобщике и нарушителе
    reporter_stats = database.find_one('player_stats', {'user_id': reporter_id})
    reported_stats = database.find_one('player_stats', {'user_id': reported_id})
    
    if not reported_stats:
        return False, "Игрок не найден"
    
    reporter_name = reporter_stats.get('name', 'Игрок') if reporter_stats else 'Игрок'
    reported_name = reported_stats.get('name', 'Игрок')
    
    # Создаем жалобу
    report = {
        'reporter_id': reporter_id,
        'reporter_name': reporter_name,
        'reported_id': reported_id,
        'reported_name': reported_name,
        'reason': reason,
        'created_at': datetime.now().isoformat(),
        'status': 'pending'  # pending, reviewed, resolved
    }
    
    database.insert_one('reports', report)
    
    # Проверяем количество жалоб на этого игрока
    all_reports = database.find('reports', {'reported_id': reported_id, 'status': 'pending'})
    report_count = len(all_reports)
    
    # Автомодерация: если 3+ жалобы, автоматически баним на 24 часа
    if report_count >= 3:
        ban_until = datetime.now() + timedelta(hours=24)
        ban_player(reported_id, ADMIN_ID or 0, f"Автомодерация: {report_count} жалоб", ban_until)
        return True, f"Жалоба отправлена. Игрок автоматически забанен на 24 часа ({report_count} жалоб)"
    
    return True, f"Жалоба на {reported_name} отправлена модераторам"

def ban_player(user_id: int, moderator_id: int, reason: str, ban_until: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Забанить игрока
    
    Args:
        user_id: ID игрока для бана
        moderator_id: ID модератора
        ban_until: До какого времени бан (None = постоянный)
    
    Returns:
        (success: bool, message: str)
    """
    if not is_moderator(moderator_id):
        return False, "Только модераторы могут банить игроков"
    
    # Проверяем, не забанен ли уже
    existing_ban = get_ban(user_id)
    if existing_ban and is_banned(user_id):
        return False, "Игрок уже забанен"
    
    # Получаем информацию о пользователе
    user_stats = database.find_one('player_stats', {'user_id': user_id})
    user_name = user_stats.get('name', 'Игрок') if user_stats else 'Игрок'
    
    # Получаем информацию о модераторе
    mod_stats = database.find_one('player_stats', {'user_id': moderator_id})
    mod_name = mod_stats.get('name', 'Модератор') if mod_stats else 'Модератор'
    
    ban = {
        'user_id': user_id,
        'user_name': user_name,
        'moderator_id': moderator_id,
        'moderator_name': mod_name,
        'reason': reason,
        'banned_at': datetime.now().isoformat(),
        'ban_until': ban_until.isoformat() if ban_until else None,
        'is_permanent': ban_until is None
    }
    
    database.insert_one('bans', ban)
    
    # Помечаем все жалобы на этого игрока как resolved
    # Обновляем все документы в цикле, так как update_one обновляет только первый
    all_reports = database.find('reports', {'reported_id': user_id, 'status': 'pending'})
    for report in all_reports:
        report_id = report.get('_id') or report.get('id')
        if report_id:
            database.update_one('reports', {'_id': report_id}, {'$set': {'status': 'resolved'}})
    
    ban_type = "постоянный" if ban_until is None else f"до {ban_until.strftime('%d.%m.%Y %H:%M')}"
    return True, f"Игрок {user_name} забанен ({ban_type})"

def unban_player(user_id: int, moderator_id: int) -> Tuple[bool, str]:
    """
    Разбанить игрока
    
    Returns:
        (success: bool, message: str)
    """
    if not is_moderator(moderator_id):
        return False, "Только модераторы могут разбанивать игроков"
    
    ban = get_ban(user_id)
    if not ban:
        return False, "Игрок не забанен"
    
    database.delete_one('bans', {'user_id': user_id})
    
    user_name = ban.get('user_name', 'Игрок')
    return True, f"Игрок {user_name} разбанен"

def get_ban(user_id: int) -> Optional[Dict]:
    """Получить информацию о бане игрока"""
    return database.find_one('bans', {'user_id': user_id})

def is_banned(user_id: int) -> bool:
    """Проверить, забанен ли игрок"""
    ban = get_ban(user_id)
    if not ban:
        return False
    
    # Если бан постоянный
    if ban.get('is_permanent', False):
        return True
    
    # Если бан временный, проверяем срок
    ban_until_str = ban.get('ban_until')
    if not ban_until_str:
        return True  # Если нет даты окончания, считаем постоянным
    
    try:
        ban_until = datetime.fromisoformat(ban_until_str)
        if datetime.now() < ban_until:
            return True  # Бан еще действует
        else:
            # Бан истек, удаляем его
            database.delete_one('bans', {'user_id': user_id})
            return False
    except:
        return True  # При ошибке считаем забаненным

def get_reports(status: str = 'pending', limit: int = 20) -> List[Dict]:
    """
    Получить список жалоб
    
    Args:
        status: pending, reviewed, resolved
        limit: Максимальное количество жалоб
    """
    all_reports = database.find('reports', {'status': status})
    # Сортируем по дате (новые первые)
    sorted_reports = sorted(all_reports, key=lambda x: x.get('created_at', ''), reverse=True)
    return sorted_reports[:limit]

def get_user_reports(user_id: int) -> List[Dict]:
    """Получить все жалобы на конкретного игрока"""
    return database.find('reports', {'reported_id': user_id})

def resolve_report(report_id: str, moderator_id: int, action: str = 'resolved') -> Tuple[bool, str]:
    """
    Обработать жалобу
    
    Args:
        report_id: ID жалобы (можно использовать created_at как идентификатор)
        moderator_id: ID модератора
        action: resolved, reviewed
    
    Returns:
        (success: bool, message: str)
    """
    if not is_moderator(moderator_id):
        return False, "Только модераторы могут обрабатывать жалобы"
    
    # Ищем жалобу по created_at (используем как ID)
    report = database.find_one('reports', {'created_at': report_id})
    if not report:
        return False, "Жалоба не найдена"
    
    database.update_one('reports', {'created_at': report_id}, 
                       {'$set': {'status': action, 'resolved_by': moderator_id, 
                                'resolved_at': datetime.now().isoformat()}})
    
    return True, "Жалоба обработана"

def get_moderators() -> List[Dict]:
    """Получить список всех модераторов"""
    return database.find('moderators', {})

def get_bans(limit: int = 50) -> List[Dict]:
    """Получить список всех банов"""
    all_bans = database.find('bans', {})
    # Фильтруем истекшие баны
    active_bans = []
    for ban in all_bans:
        if is_banned(ban['user_id']):
            active_bans.append(ban)
        else:
            # Удаляем истекший бан
            database.delete_one('bans', {'user_id': ban['user_id']})
    
    return active_bans[:limit]

