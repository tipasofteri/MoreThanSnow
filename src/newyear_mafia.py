from enum import Enum
import random
from typing import Dict, List, Optional, Tuple

class GamePhase(Enum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    ENDED = "ended"

class PlayerRole(Enum):
    CITIZEN = "Житель"
    DOCTOR = "Доктор"
    DETECTIVE = "Детектив"
    MAFIA_BOSS = "Главарь мафии"
    MAFIA = "Сообщник мафии"

class NewYearMafiaGame:
    def __init__(self, chat_id: int, creator_id: int, creator_name: str):
        self.chat_id = chat_id
        self.creator_id = creator_id
        self.phase = GamePhase.LOBBY
        self.players = []  # List of dicts: {id, name, role, alive, voted, target, action_used}
        self.day_number = 0
        self.night_actions = {}  # player_id -> target_id
        self.votes = {}  # voter_id -> target_id
        self.special_events = ["Пурга", "Тёплый костёр"]
        self.current_event = None
        self.night_time = 90  # seconds
        self.day_time = 180  # seconds
        self.voting_time = 60  # seconds

    def add_player(self, user_id: int, user_name: str) -> bool:
        """Add a player to the game if not already in the game"""
        if len(self.players) >= 10:
            return False
            
        if not any(p['id'] == user_id for p in self.players):
            self.players.append({
                'id': user_id,
                'name': user_name,
                'role': None,
                'alive': True,
                'voted': False,
                'target': None,
                'action_used': False
            })
            return True
        return False

    def remove_player(self, user_id: int) -> bool:
        """Remove a player from the game"""
        initial_count = len(self.players)
        self.players = [p for p in self.players if p['id'] != user_id]
        return len(self.players) < initial_count

    def start_game(self) -> bool:
        """Start the game if there are enough players"""
        if len(self.players) not in [6, 8, 10]:
            return False

        # Assign roles based on player count
        roles = []
        if len(self.players) == 6:
            roles = [
                PlayerRole.CITIZEN,
                PlayerRole.CITIZEN,
                PlayerRole.DOCTOR,
                PlayerRole.DETECTIVE,
                PlayerRole.MAFIA_BOSS,
                PlayerRole.MAFIA
            ]
        elif len(self.players) == 8:
            roles = [
                PlayerRole.CITIZEN,
                PlayerRole.CITIZEN,
                PlayerRole.CITIZEN,
                PlayerRole.DOCTOR,
                PlayerRole.DETECTIVE,
                PlayerRole.MAFIA_BOSS,
                PlayerRole.MAFIA,
                PlayerRole.MAFIA
            ]
        else:  # 10 players
            roles = [
                PlayerRole.CITIZEN,
                PlayerRole.CITIZEN,
                PlayerRole.CITIZEN,
                PlayerRole.CITIZEN,
                PlayerRole.DOCTOR,
                PlayerRole.DETECTIVE,
                PlayerRole.MAFIA_BOSS,
                PlayerRole.MAFIA,
                PlayerRole.MAFIA,
                PlayerRole.MAFIA
            ]

        # Shuffle and assign roles
        random.shuffle(roles)
        for i, player in enumerate(self.players):
            player['role'] = roles[i]
            player['alive'] = True
            player['voted'] = False
            player['target'] = None
            player['action_used'] = False

        self.phase = GamePhase.NIGHT
        self.day_number = 1
        self.night_actions = {}
        self.votes = {}
        
        # 20% chance for a special event
        if random.random() < 0.2:
            self.current_event = random.choice(self.special_events)
        else:
            self.current_event = None
            
        return True

    def process_night_action(self, player_id: int, target_id: Optional[int] = None) -> bool:
        """Process night actions (mafia kill, doctor heal, detective check)"""
        if self.phase != GamePhase.NIGHT:
            return False

        player = next((p for p in self.players if p['id'] == player_id), None)
        if not player or not player['alive'] or player['action_used']:
            return False

        target = next((p for p in self.players if p['id'] == target_id), None) if target_id else None
        
        # Mafia boss or mafia member submitting a kill
        if player['role'] in [PlayerRole.MAFIA_BOSS, PlayerRole.MAFIA]:
            # Only the mafia boss can submit the final kill
            if player['role'] == PlayerRole.MAFIA_BOSS and target:
                self.night_actions['mafia_kill'] = target['id']
                player['action_used'] = True
                return True
            return False
        
        # Doctor healing
        elif player['role'] == PlayerRole.DOCTOR and target:
            self.night_actions['doctor_heal'] = target['id']
            player['action_used'] = True
            return True
        
        # Detective checking
        elif player['role'] == PlayerRole.DETECTIVE and target:
            # If it's a blizzard night, detective gets no result
            if self.current_event == "Пурга":
                result = "Из-за пурги вы ничего не разглядели!"
            else:
                is_mafia = target['role'] in [PlayerRole.MAFIA_BOSS, PlayerRole.MAFIA]
                result = f"{'🔴 Подозрительный' if is_mafia else '🟢 Мирный житель'}"
            
            self.night_actions[f'detective_check_{player_id}'] = {
                'target_id': target['id'],
                'result': result
            }
            player['action_used'] = True
            return True
            
        return False

    def process_day_vote(self, voter_id: int, target_id: Optional[int] = None) -> bool:
        """Process day voting"""
        if self.phase != GamePhase.VOTING:
            return False

        voter = next((p for p in self.players if p['id'] == voter_id), None)
        if not voter or not voter['alive'] or voter['voted']:
            return False

        # If target_id is None, it's an abstention
        if target_id is not None:
            target = next((p for p in self.players if p['id'] == target_id), None)
            if not target or not target['alive'] or target_id == voter_id:
                return False
            self.votes[voter_id] = target_id
        else:
            self.votes[voter_id] = None  # Abstention
            
        voter['voted'] = True
        return True

    def check_win_condition(self) -> Tuple[bool, Optional[str]]:
        """Check if the game has been won by either team"""
        alive_players = [p for p in self.players if p['alive']]
        mafia_count = len([p for p in alive_players if p['role'] in [PlayerRole.MAFIA_BOSS, PlayerRole.MAFIA]])
        citizens_count = len(alive_players) - mafia_count
        
        if mafia_count == 0:
            return True, "Мирные жители"
        elif mafia_count >= citizens_count:
            return True, "Мафия"
            
        return False, None

    def process_night(self) -> str:
        """Process the end of night phase and return results"""
        if self.phase != GamePhase.NIGHT:
            return ""
            
        result = []
        
        # Process mafia kill (if any)
        target_id = self.night_actions.get('mafia_kill')
        heal_target = self.night_actions.get('doctor_heal')
        
        # If it's a warm night (special event), no one dies
        if self.current_event == "Тёплый костёр":
            result.append("🔥 Тёплая ночь! Благодаря волшебному костру никто не пострадал.")
        # Otherwise process kills and heals
        elif target_id and target_id != heal_target:
            killed = next((p for p in self.players if p['id'] == target_id), None)
            if killed and killed['alive']:
                killed['alive'] = False
                result.append(f"☠️ {killed['name']} был(а) убит(а) мафией!")
        
        # Reset night actions and advance phase
        self.night_actions = {}
        self.phase = GamePhase.DAY
        
        # Check for win condition
        game_over, winner = self.check_win_condition()
        if game_over:
            self.phase = GamePhase.ENDED
            result.append(f"\n🎉 Игра окончена! Победили {winner}!")
        
        return "\n".join(result)

    def start_voting(self) -> bool:
        """Start the voting phase"""
        if self.phase != GamePhase.DAY:
            return False
            
        self.phase = GamePhase.VOTING
        self.votes = {}
        for player in self.players:
            player['voted'] = False
            player['target'] = None
            
        return True

    def process_voting(self) -> str:
        """Process the end of voting phase and return results"""
        if self.phase != GamePhase.VOTING:
            return ""
            
        # Count votes
        vote_count = {}
        for target_id in self.votes.values():
            if target_id:  # Skip abstentions
                vote_count[target_id] = vote_count.get(target_id, 0) + 1
        
        result = []
        if not vote_count:
            result.append("Никто не получил голосов. Никто не выбывает.")
        else:
            # Find player(s) with most votes
            max_votes = max(vote_count.values())
            candidates = [pid for pid, votes in vote_count.items() if votes == max_votes]
            
            if len(candidates) > 1:
                result.append(f"Несколько игроков набрали по {max_votes} голосов. Никто не выбывает.")
            else:
                executed = next((p for p in self.players if p['id'] == candidates[0]), None)
                if executed and executed['alive']:
                    executed['alive'] = False
                    result.append(f"{executed['name']} был(а) казнён(а) по решению деревни!")
        
        # Reset for next night
        self.phase = GamePhase.NIGHT
        self.day_number += 1
        self.night_actions = {}
        
        # Check for win condition
        game_over, winner = self.check_win_condition()
        if game_over:
            self.phase = GamePhase.ENDED
            result.append(f"\n🎉 Игра окончена! Победили {winner}!")
        else:
            # 20% chance for a special event next night
            if random.random() < 0.2:
                self.current_event = random.choice(self.special_events)
                result.append(f"\n✨ Событие: {self.current_event}!")
            else:
                self.current_event = None
        
        return "\n".join(result)

    def get_player_role(self, player_id: int) -> Optional[PlayerRole]:
        """Get a player's role (for private messages)"""
        player = next((p for p in self.players if p['id'] == player_id), None)
        return player['role'] if player else None

    def get_alive_players(self, exclude_id: Optional[int] = None) -> List[dict]:
        """Get list of alive players (optionally excluding one)"""
        return [p for p in self.players if p['alive'] and (exclude_id is None or p['id'] != exclude_id)]

    def get_game_state(self) -> dict:
        """Get current game state for display"""
        return {
            'phase': self.phase.value,
            'day': self.day_number,
            'players': [{
                'id': p['id'],
                'name': p['name'],
                'alive': p['alive'],
                'role': p['role'].value if p['role'] and (not p['alive'] or self.phase == GamePhase.ENDED) else None,
                'voted': p['voted']
            } for p in self.players],
            'current_event': self.current_event
        }
