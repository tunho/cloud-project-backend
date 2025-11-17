# state.py
from typing import List, Dict, Any
from models import GameState

# 🔥 여러 방을 관리하는 딕셔너리
rooms: Dict[str, GameState] = {}

# 🔥 매칭 대기열 (sid와 이름을 저장)
queue: List[Dict[str, Any]] = []

