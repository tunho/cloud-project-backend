# models.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Dict, Any
from threading import Timer

Color = Literal["black", "white"]


TurnPhase = Literal[
    "INIT", 
    "DRAWING",        
    "PLACE_JOKER",    
    "GUESSING",       
    "POST_SUCCESS_GUESS",
    "ANIMATING_GUESS" # 👈 [추가] 추리 결과 애니메이션 재생 중
]

@dataclass
class Tile:
    id: int
    color: Color
    value: Optional[int]  # 조커는 None
    is_joker: bool
    revealed: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "color": self.color,
            "value": self.value,
            "is_joker": self.is_joker,
            "revealed": self.revealed
        }


@dataclass
class Player:
    sid: str
    uid: str
    id: int
    name: str
    hand: List[Any] = field(default_factory=list)
    last_drawn_index: Optional[int] = None
    
    # ▼▼▼ [최종 포함 필드] ▼▼▼
    email: str = ""
    major: str = ""
    money: int = 0  # 👈 money 필드 추가
    nickname: str = ""
    year: int = 0
    bet_amount: int = 0
    final_rank: int = 0
    

@dataclass
class GameState:
    players: List[Player]
    piles: Dict[Color, List[Tile]]
    same_number_order: Literal["black-first", "white-first"]
    current_turn: int
    drawn_tile: Optional[Tile]
    pending_placement: bool
    can_place_anywhere: bool
    next_tile_id: int
    game_started: bool = False # 로비/게임 구분
    turn_phase: TurnPhase = "INIT"
    turn_timer: Optional[Timer] = None
    elimination_count: int = 0
    