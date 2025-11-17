# models.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Dict, Any
from threading import Timer

Color = Literal["black", "white"]


TurnPhase = Literal[
    "INIT", 
    "DRAWING",        # 타일 드로우 대기
    "PLACE_JOKER",    # 조커 배치 대기
    "GUESSING",       # 추리 대기
    "POST_SUCCESS_GUESS" # 추리 성공 후 연속 진행 여부 대기
]


@dataclass
class Tile:
    id: int
    color: Color
    value: Optional[int]  # 조커는 None
    is_joker: bool
    revealed: bool = False

@dataclass
class Player:
    sid: str          # 현재 연결된 세션 ID (바뀔 수 있음)
    uid: str          # (필수) Firebase 계정 ID (영구적)
    id: int           # 방 안에서의 인덱스 (0,1,2,...)
    name: str
    hand: List[Tile]
    last_drawn_index: Optional[int] = None

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