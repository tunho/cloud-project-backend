# utils.py
from typing import Dict, Any, Optional
from models import Tile, Player, GameState
from state import rooms
from extensions import socketio
import time # 👈 time 임포트

# 🔥 [FIX] 순환 참조 방지를 위해 상수 직접 정의하거나 game_events에서 가져오지 않음
# (game_events가 utils를 임포트하므로 여기서 game_events를 임포트하면 안됨)
TURN_TIMER_SECONDS = 60

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
    # print(f"🔍 Serializing {p.nickname}: Bet={p.bet_amount}, Rank={p.final_rank}") # Debug log
    return {
        "sid": p.sid,
        "uid": p.uid,
        "id": p.id,
        "name": p.name,
        "nickname": p.nickname,
        "major": p.major,
        "year": p.year,
        "money": p.money,
        "betAmount": p.bet_amount,
        "rank": p.final_rank, # 🔥 [NEW] 순위 정보 전송
        "hand": [serialize_tile(t, is_self) for t in p.hand],
        "lastDrawnIndex": p.last_drawn_index,
    }

# (신규) 이 함수는 이제 '로비'에서만 사용합니다.
# (게임 중에는 아래의 broadcast_in_game_state가 사용됩니다)
def serialize_state_for_lobby(gs: Any) -> Dict[str, Any]:
    # gs can be Room or GameState
    players = gs.players
    
    # Default values
    same_number_order = "black-first"
    current_turn = 0
    
    # If gs is Room and has game_state, use it
    if hasattr(gs, 'game_state') and gs.game_state:
        # Check if game_state has attributes (it could be OmokLogic or GameLogic)
        if hasattr(gs.game_state, 'same_number_order'):
            same_number_order = gs.game_state.same_number_order
        if hasattr(gs.game_state, 'current_turn'):
            current_turn = gs.game_state.current_turn
        elif hasattr(gs.game_state, 'current_turn_index'): # OmokLogic
            current_turn = gs.game_state.current_turn_index
            
    elif hasattr(gs, 'same_number_order'): # gs is GameState
        same_number_order = gs.same_number_order
        current_turn = gs.current_turn

    return {
        # 로비에서는 숨길 카드가 없으므로 is_self=True로 모두 공개
        "players": [serialize_player(p, is_self=True) for p in players],
        "piles": { "black": 0, "white": 0 }, # 로비에서는 0
        "sameNumberOrder": same_number_order,
        "currentTurn": current_turn,
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
    room = get_room(room_id)
    if not room: return
    
    # 🔥 [FIX] Handle Room object
    gs = room.game_state
    if not gs: return

    # If Omok, we might skip this or handle differently
    if getattr(room, 'game_type', 'davinci') == 'omok':
        # Omok uses different events (omok:update_board, omok:turn_start)
        # But we might want to send player list updates if needed.
        # For now, just return to prevent crash in Davinci logic
        return

    if not gs.players:
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
            "currentTurn": gs.current_turn, # 인덱스
            "pendingPlacement": gs.pending_placement,
            "canPlaceAnywhere": gs.can_place_anywhere,

            # (보안) '뽑은 타일'은 현재 턴인 사람에게만 값을 보여줌
            "drawnTile": serialize_tile(gs.drawn_tile, is_self=is_current_turn_player),
            "phase": gs.turn_phase, # 🔥 [FIX] Refresh 시 페이즈 정보 전송
            "remainingTime": max(0, TURN_TIMER_SECONDS - (time.time() - gs.turn_start_time)) if gs.turn_start_time else 0, # 🔥 [NEW] 남은 시간 전송
            "payoutResults": gs.payout_results, # 🔥 [NEW] 정산 결과 전송
        }
        
        # 'state_update' 이벤트로 개인화된 상태 전송
        try:
            socketio.emit("state_update", state_for_player, to=p_to_send.sid)
        except Exception as e:
            print(f"⚠️ Failed to send state to {p_to_send.nickname} ({p_to_send.sid}): {e}")
            
    print(f"📡 [Broadcast] Completed for room {room_id}") # Debug

# (기존 broadcast_state 함수는 삭제하고 위 함수로 대체)

# 🔥 [NEW] 비동기 Firestore 업데이트 함수
def update_user_money_async(uid: str, amount: int, nickname: str = "Unknown"):
    """
    Firestore 업데이트를 별도 스레드에서 실행하여 메인 스레드(Socket.IO) 차단을 방지함.
    """
    def _update():
        try:
            from firebase_admin_config import get_db
            from firebase_admin import firestore as admin_firestore
            
            db = get_db()
            if db:
                user_ref = db.collection('users').document(uid)
                user_ref.update({
                    'money': admin_firestore.Increment(amount)
                })
                print(f"💰 Firestore updated (async): {nickname} {amount:+d}")
        except Exception as e:
            print(f"❌ Firestore async update error for {nickname} ({uid}): {e}")

    import threading
    threading.Thread(target=_update, daemon=True).start()
