from fastapi import WebSocket
from typing import Dict, List
import json
import random

class MatchManager:
    def __init__(self):
        self.waiting_players: List[Dict] = []
        self.active_matches: Dict[str, Dict] = {}
        self.connections: Dict[int, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.connections[user_id] = websocket
    
    def disconnect(self, user_id: int):
        if user_id in self.connections:
            del self.connections[user_id]
    
    def add_to_queue(self, user_id: int, username: str, rating: int):
        self.waiting_players.append({
            "user_id": user_id,
            "username": username,
            "rating": rating
        })
    
    def find_match(self, user_id: int):
        if len(self.waiting_players) < 2:
            return None
        
        current_player = None
        for i, player in enumerate(self.waiting_players):
            if player["user_id"] == user_id:
                current_player = self.waiting_players.pop(i)
                break
        
        if not current_player or not self.waiting_players:
            if current_player:
                self.waiting_players.append(current_player)
            return None
        
        opponent = self.waiting_players.pop(0)
        
        return current_player, opponent
    
    def create_match(self, player1: Dict, player2: Dict, task_id: int):
        match_id = f"{player1['user_id']}_{player2['user_id']}_{random.randint(1000, 9999)}"
        
        self.active_matches[match_id] = {
            "match_id": match_id,
            "player1": player1,
            "player2": player2,
            "task_id": task_id,
            "player1_answer": None,
            "player2_answer": None,
            "player1_score": 0,
            "player2_score": 0,
            "status": "active"
        }
        
        return match_id
    
    def get_match(self, match_id: str):
        return self.active_matches.get(match_id)
    
    def submit_answer(self, match_id: str, user_id: int, answer: str):
        match = self.active_matches.get(match_id)
        if not match:
            return None
        
        if match["player1"]["user_id"] == user_id:
            match["player1_answer"] = answer
        elif match["player2"]["user_id"] == user_id:
            match["player2_answer"] = answer
        
        return match
    
    def finish_match(self, match_id: str):
        if match_id in self.active_matches:
            del self.active_matches[match_id]

match_manager = MatchManager()