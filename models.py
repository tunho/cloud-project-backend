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

# Assuming a Room class is intended to be added or modified,
# as the provided __init__ method clearly belongs to a Room class
# and the instruction mentions "Update Room init".
# Since no Room class exists in the provided document,
# I am adding a new Room class with the specified __init__ method.
@dataclass
class Room:
    room_id: str
    name: str
    password: Optional[str] = None
    game_type: str = 'davinci'
    max_players: int = field(init=False)
    players: List[Any] = field(default_factory=list) # List of Player objects
    game_state: Optional[Any] = None # Game state object
    status: str = 'waiting' # waiting, playing

    def __post_init__(self):
        # This logic is derived from the provided __init__
        self.max_players = 2 if self.game_type == 'omok' else 4


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
    bet_amount: int = 10000 # 🔥 [FIX] 기본값 10000
    final_rank: int = 0
    settled: bool = False  # 👈 정산 완료 여부
    

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
    turn_start_time: float = 0.0 # 👈 턴 시작 시간 (서버 타임스탬프)
    payout_results: List[Dict[str, Any]] = field(default_factory=list) # 🔥 [NEW] 정산 결과 저장 (재접속 시 복구용)
    