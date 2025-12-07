# teams.py
"""
Система команд для игры в мафию
"""
import database
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import random
import string

def generate_team_id() -> str:
    """Генерировать уникальный ID команды"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def create_team(creator_id: int, team_name: str) -> Optional[Dict]:
    """
    Создать новую команду
    
    Returns:
        Словарь с данными команды или None при ошибке
    """
    # Проверяем, не состоит ли создатель уже в команде
    existing_team = get_user_team(creator_id)
    if existing_team:
        return None  # Уже в команде
    
    # Получаем информацию о создателе
    creator_stats = database.find_one('player_stats', {'user_id': creator_id})
    if not creator_stats:
        return None
    
    creator_name = creator_stats.get('name', 'Игрок')
    
    # Создаем команду
    team_id = generate_team_id()
    team = {
        'team_id': team_id,
        'name': team_name,
        'creator_id': creator_id,
        'creator_name': creator_name,
        'members': [{
            'user_id': creator_id,
            'name': creator_name,
            'joined_at': datetime.now().isoformat(),
            'role': 'leader'  # Создатель - лидер
        }],
        'invitations': [],  # Список приглашений
        'created_at': datetime.now().isoformat(),
        'stats': {
            'total_games': 0,
            'total_wins': 0,
            'total_losses': 0,
            'avg_elo': 1000,
            'total_candies': 0
        }
    }
    
    database.insert_one('teams', team)
    return team

def get_team(team_id: str) -> Optional[Dict]:
    """Получить команду по ID"""
    return database.find_one('teams', {'team_id': team_id})

def get_user_team(user_id: int) -> Optional[Dict]:
    """Получить команду, в которой состоит пользователь"""
    all_teams = database.find('teams', {})
    for team in all_teams:
        if any(member['user_id'] == user_id for member in team.get('members', [])):
            return team
    return None

def invite_player(team_id: str, inviter_id: int, invitee_id: int) -> Tuple[bool, str]:
    """
    Пригласить игрока в команду
    
    Returns:
        (success: bool, message: str)
    """
    team = get_team(team_id)
    if not team:
        return False, "Команда не найдена"
    
    # Проверяем, что приглашающий состоит в команде
    inviter = next((m for m in team['members'] if m['user_id'] == inviter_id), None)
    if not inviter:
        return False, "Вы не состоите в этой команде"
    
    # Проверяем, не состоит ли приглашаемый уже в команде
    if any(m['user_id'] == invitee_id for m in team.get('members', [])):
        return False, "Игрок уже состоит в команде"
    
    # Проверяем, не приглашен ли уже
    if any(inv['user_id'] == invitee_id for inv in team.get('invitations', [])):
        return False, "Игрок уже приглашен"
    
    # Получаем информацию о приглашаемом
    invitee_stats = database.find_one('player_stats', {'user_id': invitee_id})
    if not invitee_stats:
        return False, "Игрок не найден"
    
    # Проверяем, не состоит ли приглашаемый в другой команде
    existing_team = get_user_team(invitee_id)
    if existing_team:
        return False, "Игрок уже состоит в другой команде"
    
    # Добавляем приглашение
    invitation = {
        'user_id': invitee_id,
        'name': invitee_stats.get('name', 'Игрок'),
        'invited_by': inviter_id,
        'invited_at': datetime.now().isoformat()
    }
    
    team['invitations'] = team.get('invitations', [])
    team['invitations'].append(invitation)
    
    database.update_one('teams', {'team_id': team_id}, {'$set': team})
    
    return True, f"Игрок {invitee_stats.get('name', 'Игрок')} приглашен в команду"

def accept_invitation(team_id: str, user_id: int) -> Tuple[bool, str]:
    """
    Принять приглашение в команду
    
    Returns:
        (success: bool, message: str)
    """
    team = get_team(team_id)
    if not team:
        return False, "Команда не найдена"
    
    # Проверяем, есть ли приглашение
    invitation = next((inv for inv in team.get('invitations', []) if inv['user_id'] == user_id), None)
    if not invitation:
        return False, "Приглашение не найдено"
    
    # Проверяем, не состоит ли уже в команде
    if any(m['user_id'] == user_id for m in team.get('members', [])):
        return False, "Вы уже состоите в этой команде"
    
    # Получаем информацию о пользователе
    user_stats = database.find_one('player_stats', {'user_id': user_id})
    if not user_stats:
        return False, "Пользователь не найден"
    
    # Добавляем в команду
    new_member = {
        'user_id': user_id,
        'name': user_stats.get('name', 'Игрок'),
        'joined_at': datetime.now().isoformat(),
        'role': 'member'
    }
    
    team['members'].append(new_member)
    
    # Удаляем приглашение
    team['invitations'] = [inv for inv in team.get('invitations', []) if inv['user_id'] != user_id]
    
    database.update_one('teams', {'team_id': team_id}, {'$set': team})
    
    return True, f"Вы присоединились к команде {team['name']}"

def reject_invitation(team_id: str, user_id: int) -> Tuple[bool, str]:
    """
    Отклонить приглашение в команду
    
    Returns:
        (success: bool, message: str)
    """
    team = get_team(team_id)
    if not team:
        return False, "Команда не найдена"
    
    # Удаляем приглашение
    team['invitations'] = [inv for inv in team.get('invitations', []) if inv['user_id'] != user_id]
    
    database.update_one('teams', {'team_id': team_id}, {'$set': team})
    
    return True, "Приглашение отклонено"

def leave_team(user_id: int) -> Tuple[bool, str]:
    """
    Покинуть команду
    
    Returns:
        (success: bool, message: str)
    """
    team = get_user_team(user_id)
    if not team:
        return False, "Вы не состоите в команде"
    
    # Если это создатель и в команде больше одного участника, передаем лидерство
    if team['creator_id'] == user_id and len(team['members']) > 1:
        # Передаем лидерство первому участнику (не создателю)
        other_members = [m for m in team['members'] if m['user_id'] != user_id]
        if other_members:
            new_leader = other_members[0]
            new_leader['role'] = 'leader'
            team['creator_id'] = new_leader['user_id']
            team['creator_name'] = new_leader['name']
    
    # Удаляем участника
    team['members'] = [m for m in team['members'] if m['user_id'] != user_id]
    
    # Если команда пуста, удаляем её
    if len(team['members']) == 0:
        database.delete_one('teams', {'team_id': team['team_id']})
        return True, "Команда распущена"
    
    database.update_one('teams', {'team_id': team['team_id']}, {'$set': team})
    return True, "Вы покинули команду"

def kick_member(team_id: str, leader_id: int, member_id: int) -> Tuple[bool, str]:
    """
    Исключить участника из команды (только для лидера)
    
    Returns:
        (success: bool, message: str)
    """
    team = get_team(team_id)
    if not team:
        return False, "Команда не найдена"
    
    # Проверяем, что это лидер
    leader = next((m for m in team['members'] if m['user_id'] == leader_id), None)
    if not leader or leader.get('role') != 'leader':
        return False, "Только лидер может исключать участников"
    
    # Нельзя исключить самого себя
    if member_id == leader_id:
        return False, "Нельзя исключить самого себя"
    
    # Удаляем участника
    team['members'] = [m for m in team['members'] if m['user_id'] != member_id]
    
    database.update_one('teams', {'team_id': team_id}, {'$set': team})
    
    return True, "Участник исключен из команды"

def get_team_stats(team_id: str) -> Dict:
    """
    Получить статистику команды
    
    Returns:
        Словарь со статистикой команды
    """
    team = get_team(team_id)
    if not team:
        return {}
    
    members_ids = [m['user_id'] for m in team.get('members', [])]
    
    # Собираем статистику всех участников
    total_games = 0
    total_wins = 0
    total_losses = 0
    total_candies = 0
    elo_ratings = []
    
    for user_id in members_ids:
        stats = database.find_one('player_stats', {'user_id': user_id})
        if stats:
            total_games += stats.get('games_played', 0)
            total_wins += stats.get('games_won', 0)
            total_losses += stats.get('games_lost', 0)
            total_candies += stats.get('candies', 0)
            elo_ratings.append(stats.get('elo_rating', 1000))
    
    avg_elo = sum(elo_ratings) / len(elo_ratings) if elo_ratings else 1000
    win_rate = (total_wins / total_games * 100) if total_games > 0 else 0
    
    team_stats = {
        'total_games': total_games,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'win_rate': win_rate,
        'avg_elo': avg_elo,
        'total_candies': total_candies,
        'members_count': len(members_ids)
    }
    
    # Обновляем статистику в команде
    team['stats'] = team_stats
    database.update_one('teams', {'team_id': team_id}, {'$set': team})
    
    return team_stats

def get_user_invitations(user_id: int) -> List[Dict]:
    """Получить все приглашения пользователя"""
    all_teams = database.find('teams', {})
    invitations = []
    
    for team in all_teams:
        for inv in team.get('invitations', []):
            if inv['user_id'] == user_id:
                invitation_info = {
                    'team_id': team['team_id'],
                    'team_name': team['name'],
                    'invited_by': inv.get('invited_by'),
                    'invited_at': inv.get('invited_at')
                }
                # Получаем имя пригласившего
                inviter_stats = database.find_one('player_stats', {'user_id': inv.get('invited_by')})
                if inviter_stats:
                    invitation_info['inviter_name'] = inviter_stats.get('name', 'Игрок')
                invitations.append(invitation_info)
    
    return invitations

