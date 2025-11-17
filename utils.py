# utils.py
from typing import Dict, Any, Optional
from models import Tile, Player, GameState
from state import rooms
from extensions import socketio

# ▼▼▼ (핵심 수정 1) ▼▼▼
# 'is_self' 플래그를 추가하여 본인 패가 아니면 값을 은닉합니다.
def serialize_tile(t: Tile, is_self: bool = False) -> Dict[str, Any]:
    if not t: return None # 타일이 None이면 None 반환

    if not is_self and not t.revealed:
        # 타인의 숨겨진 카드
        return {
            "id": t.id,
            "color": t.color,
            "value": None, # <- (보안) 값을 null로 보냄
            "isJoker": t.is_joker,
            "revealed": t.revealed,
        }
    
    # 본인 카드 또는 이미 공개된 카드
    return {
        "id": t.id,
        "color": t.color,
        "value": t.value, # <- (정상) 값 공개
        "isJoker": t.is_joker,
        "revealed": t.revealed,
    }

# ▼▼▼ (핵심 수정 2) ▼▼▼
# 'is_self' 플래그를 받아서 serialize_tile로 넘깁니다.
def serialize_player(p: Player, is_self: bool = False) -> Dict[str, Any]:
    return {
        "sid": p.sid,
        "uid": p.uid, # (이전 수정사항 반영)
        "id": p.id,
        "name": p.name,
        "hand": [serialize_tile(t, is_self) for t in p.hand],
        "lastDrawnIndex": p.last_drawn_index,
    }

# (신규) 이 함수는 이제 '로비'에서만 사용합니다.
# (게임 중에는 아래의 broadcast_in_game_state가 사용됩니다)
def serialize_state_for_lobby(gs: GameState) -> Dict[str, Any]:
    return {
        # 로비에서는 숨길 카드가 없으므로 is_self=True로 모두 공개
        "players": [serialize_player(p, is_self=True) for p in gs.players],
        "piles": { "black": 0, "white": 0 }, # 로비에서는 0
        "sameNumberOrder": gs.same_number_order,
        "currentTurn": gs.current_turn,
        "drawnTile": None,
        "pendingPlacement": False,
        "canPlaceAnywhere": False,
    }

# --- 공통 유틸리티 ---

def get_room(room_id: str) -> GameState:
    """roomId에 해당하는 GameState 가져오기 (없으면 생성)"""
    if room_id not in rooms:
        rooms[room_id] = GameState(
            players=[],
            piles={"black": [], "white": []},
            same_number_order="black-first",
            current_turn=0,
            drawn_tile=None,
            pending_placement=False,
            can_place_anywhere=False,
            next_tile_id=0,
        )
    return rooms[room_id]

def find_player_by_sid(gs: GameState, sid: str) -> Optional[Player]:
    for p in gs.players:
        if p.sid == sid:
            return p
    return None

def find_player_by_uid(gs: GameState, uid: str) -> Optional[Player]:
    for p in gs.players:
        if p.uid == uid:
            return p
    return None

# ▼▼▼ (핵심 수정 3) ▼▼▼
# 기존 broadcast_state 함수를 '인게임용'으로 완전히 교체합니다.
def broadcast_in_game_state(room_id: str):
    """(신규) 인게임 전용, 각 플레이어에게 '개인화된' 상태 전송"""
    gs = get_room(room_id)
    if not gs or not gs.players:
        return

    current_player_sid = None
    if gs.drawn_tile and gs.current_turn < len(gs.players):
         # current_turn은 '인덱스'이므로 바로 사용
        current_player_sid = gs.players[gs.current_turn].sid

    for p_to_send in gs.players:
        # 이 사람(p_to_send)이 현재 턴의 플레이어인가?
        is_current_turn_player = (p_to_send.sid == current_player_sid)

        state_for_player = {
            "players": [
                # 본인(is_self=True)과 타인(is_self=False)을 구분하여 직렬화
                serialize_player(p, is_self=(p.sid == p_to_send.sid)) 
                for p in gs.players
                    ],
            "piles": {
                            "black": len(gs.piles["black"]),
                            "white": len(gs.piles["white"]),
            },
            "sameNumberOrder": gs.same_number_order,
            "currentTurn": gs.current_turn, # 프론트가 턴을 식별하기 위함
            "pendingPlacement": gs.pending_placement,
            "canPlaceAnywhere": gs.can_place_anywhere,

            # (보안) '뽑은 타일'은 현재 턴인 사람에게만 값을 보여줌
            "drawnTile": serialize_tile(gs.drawn_tile, is_self=is_current_turn_player),
        }
        
        # 'state_update' 이벤트로 개인화된 상태 전송
        socketio.emit("state_update", state_for_player, to=p_to_send.sid)

# (기존 broadcast_state 함수는 삭제하고 위 함수로 대체)