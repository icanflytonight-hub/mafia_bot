import random
import json
import os
from typing import Dict, List, Optional, Any

class Player:
    def __init__(self, user_id: int, username: str, first_name: str):
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.character_name: Optional[str] = None
        self.is_alive: bool = True
        self.hidden_role: Optional[str] = None
        self.is_admin: bool = False
        self.vote: Optional[int] = None
        self.night_choice: Optional[int] = None
        self.presented: bool = False   # новое поле: представился ли

    def __repr__(self):
        return f"Player({self.user_id}, {self.character_name}, alive={self.is_alive})"

class Game:
    def __init__(self, leader_id: int, chat_id: int):
        self.leader_id = leader_id
        self.chat_id = chat_id
        self.players: Dict[int, Player] = {}
        self.phase: str = "idle"  # idle, registration, night, discussion, voting, ended
        self.hidden_roles: Dict[str, int] = {}
        self.night_actions: Dict[str, int] = {}
        self.vote_results: Dict[int, int] = {}
        self.vote_count: Dict[int, int] = {}
        self.alive_players: List[int] = []
        self.winner: Optional[str] = None
        self.end_reason: Optional[str] = None  # "caught", "vote", "win", None
        self.registration_message_id: Optional[int] = None
        self.discussion_message_id: Optional[int] = None
        self.night_message_id: Optional[int] = None
        self.morning_message_id: Optional[int] = None
        self.current_night_klepto_target: Optional[int] = None
        self.current_night_komendant_target: Optional[int] = None
        self.current_night_uborshica_target: Optional[int] = None
        self.klepto_caught: bool = False
        self.klepto_stole: bool = False
        self.klepto_stole_from: Optional[int] = None
        self.stolen_items: List[tuple] = []   # список (имя_жертвы, вещь)
        self.klepto_item: Optional[str] = None
        self.klepto_awaiting_item: bool = False

    def add_player(self, user_id: int, username: str, first_name: str):
        if user_id not in self.players:
            self.players[user_id] = Player(user_id, username, first_name)
            self.alive_players.append(user_id)

    def remove_player(self, user_id: int):
        if user_id in self.players:
            del self.players[user_id]
            if user_id in self.alive_players:
                self.alive_players.remove(user_id)
            for role, uid in list(self.hidden_roles.items()):
                if uid == user_id:
                    del self.hidden_roles[role]
            for role in list(self.night_actions.keys()):
                if self.night_actions[role] == user_id:
                    del self.night_actions[role]

    def get_alive_players(self) -> List[Player]:
        return [self.players[uid] for uid in self.alive_players if self.players[uid].is_alive]

    def assign_hidden_roles(self, role_history: Dict[int, List[str]]):
        candidates = [p for p in self.players.values() if p.user_id != self.leader_id and p.is_alive]
        if len(candidates) < 3:
            raise ValueError("Недостаточно игроков для назначения скрытых ролей (нужно минимум 3).")

        never_played = [p for p in candidates if p.user_id not in role_history]
        if len(never_played) >= 3:
            selected = random.sample(never_played, 3)
        else:
            candidates_sorted = sorted(candidates, key=lambda p: len(role_history.get(p.user_id, [])))
            selected = candidates_sorted[:3]

        roles = ["klepto", "komendant", "uborshica"]
        random.shuffle(roles)
        for i, player in enumerate(selected):
            player.hidden_role = roles[i]
            self.hidden_roles[roles[i]] = player.user_id
            if player.user_id not in role_history:
                role_history[player.user_id] = []
            role_history[player.user_id].append(roles[i])

    def get_hidden_role_info(self, user_id: int) -> Optional[str]:
        for role, uid in self.hidden_roles.items():
            if uid == user_id:
                return role
        return None

    def check_win_condition(self) -> Optional[str]:
        klepto_id = self.hidden_roles.get("klepto")
        if not klepto_id or klepto_id not in self.players:
            return "residents"
        klepto = self.players[klepto_id]
        if not klepto.is_alive:
            return "residents"
        alive_count = sum(1 for p in self.players.values() if p.is_alive)
        if alive_count <= 2 and klepto.is_alive:
            return "klepto"
        return None
