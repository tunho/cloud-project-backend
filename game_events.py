# game_events.py
import random
import time # 👈 time 임포트
from threading import Timer
from flask import request
from flask_socketio import emit
from extensions import socketio
from game_logic import GameLogic
from omok_logic import OmokLogic
from omok_logic import OmokLogic
from omok_logic import OmokLogic
from models import Player, Color, TurnPhase, Optional, GameState # 👈 GameState 추가
from state import rooms # 👈 rooms 임포트
from utils import find_player_by_sid, find_player_by_uid, get_room, broadcast_in_game_state, serialize_state_for_lobby, update_user_money_async
from handlers.omok_handler import OmokHandler
from handlers.davinci_handler import DavinciHandler
from handlers.indian_poker_handler import IndianPokerHandler
from indian_poker_logic import IndianPokerLogic

from game_logic import (
    prepare_tiles, deal_initial_hands, start_turn_from, 
    auto_place_drawn_tile, guess_tile, is_player_eliminated, get_alive_players
)

# 🔥 Firebase Admin SDK 임포트
try:
    from firebase_admin_config import get_db
    from firebase_admin import firestore as admin_firestore
    FIREBASE_AVAILABLE = True
    print("✅ Firebase Admin imported successfully")
except Exception as e:
    FIREBASE_AVAILABLE = False
    print(f"⚠️ Firebase Admin not available: {e}")




TURN_TIMER_SECONDS = 60

# --- 헬퍼: 턴 관리 ---

def get_current_player(gs) -> Optional[Player]:
    # gs can be Room or GameState/OmokLogic
    players = getattr(gs, 'players', [])
    if not players:
        return None
        
    # Check if gs is Room and has game_state
    game_state = getattr(gs, 'game_state', gs)
    
    # Try to get current turn index
    if hasattr(game_state, 'current_turn_index'): # OmokLogic
        idx = game_state.current_turn_index
    elif hasattr(game_state, 'current_turn'): # GameLogic
        idx = game_state.current_turn
    else:
        return None
        
    return players[idx % len(players)]

def start_game_flow(room_id: str):
    """(백그라운드) 게임 시작 로직: 타일 준비 -> 패 분배 -> 시작 신호 -> 첫 턴"""
    # 1. 방 정보 가져오기
    gs = get_room(room_id)
    if not gs:
        print(f"❌ 게임 시작 실패: 방 {room_id}를 찾을 수 없음.")
        return

    print(f"🚀 게임 시작 루틴 실행: {room_id}")

    # 2. 게임 데이터 초기화 (로직)
    if gs.game_type == 'omok':
        # 오목 초기화
        if gs.game_state is None:
            gs.game_state = OmokLogic(gs.players)
    elif gs.game_type == 'indian_poker':
        if gs.game_state is None:
            gs.game_state = IndianPokerLogic(gs.players)
        gs.game_state.game_started = True # 🔥 [FIX] Mark game as started
    else:
        # 다빈치 초기화
        if gs.game_state is None:
            gs.game_state = GameLogic(gs.players)
            
        prepare_tiles(gs.game_state)        # 검정/흰색 타일 섞기
        deal_initial_hands(gs.game_state)   # 플레이어들에게 초기 패 분배 (3개 또는 4개)
        gs.game_state.game_started = True   # 🔥 [FIX] 명시적으로 게임 시작 플래그 설정

    # 3. 상태 플래그 설정
    gs.status = 'playing'
    # gs.current_turn = -1 # OmokLogic handles this internally or we sync

    # 4. 프론트엔드에 '게임 시작' 알림 (Lobby -> Game 화면 전환용)
    socketio.emit("game_started", {"roomId": room_id, "gameType": gs.game_type}, room=room_id)
    print(f"📡 game_started 이벤트 전송 완료 -> 프론트엔드 씬 전환 대기")

    # 5. 프론트엔드 로딩 대기 (Vue 컴포넌트가 마운트되고 소켓 리스너를 켤 시간 확보)
    socketio.sleep(3) # 🔥 [FIX] Increased delay for Game Start animation

    # 6. 첫 번째 턴 시작
    if gs.game_type == 'omok':
        handler = OmokHandler()
        handler.start_turn(room_id, gs)
    elif gs.game_type == 'indian_poker':
        handler = IndianPokerHandler()
        handler.start_turn(room_id, gs)
    else:
        gs.game_state.current_turn = -1
        start_next_turn(room_id)


def start_omok_turn(room_id: str):
    """오목 턴 시작 알림"""
    gs = get_room(room_id)
    if not gs or not gs.game_state: return
    
    handler = OmokHandler()
    handler.start_turn(room_id, gs)





def start_next_turn(room_id: str, reason: str = None):
    """(수정) 다음 턴을 시작 (드로우 또는 추리) - 플레이어 퇴장 시에도 안정적"""
    room = get_room(room_id)
    if not room: return
    gs = room.game_state
    if not gs: return

    # 🔥 [수정] 생존자 먼저 확인
    active_players_count = len(get_alive_players(gs))
    
    # 생존자가 1명 이하면 게임 종료되어야 하므로 턴 시작 안 함
    if active_players_count <= 1:
        print(f"[{room_id}] 생존자 {active_players_count}명, 게임 종료 조건")
        return

    # 🔥 [수정] 다음 생존 플레이어 찾기 (안전한 루프)
    attempts = 0
    max_attempts = len(gs.players)
    
    while attempts < max_attempts:
        gs.current_turn = (gs.current_turn + 1) % len(gs.players)
        next_player = gs.players[gs.current_turn]
        
        # final_rank가 0인 사람만 턴을 가질 수 있음 (0 = 생존, >0 = 탈락)
        if next_player.final_rank == 0:
            break
        attempts += 1
    else:
        # 루프를 다 돌았는데도 생존자가 없다면 (비정상)
        print(f"[{room_id}] ❌ ERROR: 턴을 넘길 생존자가 없습니다.")
        return

    player = get_current_player(gs)
    if not player: 
        print(f"[{room_id}] ❌ ERROR: 현재 플레이어를 찾을 수 없습니다.")
        return

    print(f"--- {player.nickname} 님의 턴 시작 ---")
    
    # [수정] 턴 페이즈 결정
    piles_empty = not gs.piles["black"] and not gs.piles["white"]
    
    if piles_empty:
        # 더미가 없으면 바로 '추리'
        print(f"[{room_id}] 더미 없음 -> GUESSING 페이즈로 설정")
        set_turn_phase(room_id, "GUESSING", reason=reason)
    else:
        # 👈 [복구] 더미가 있으면 '드로우' 단계
        print(f"[{room_id}] 더미 있음 -> DRAWING 페이즈로 설정")
        set_turn_phase(room_id, "DRAWING", reason=reason)

def set_turn_phase(room_id: str, phase: TurnPhase, broadcast: bool = True, reason: str = None):
    """
    (수정) 지정된 페이즈로 상태 변경 (DRAWING 로직 포함)
    broadcast: False이면 상태 전송을 건너뜀 (애니메이션 등 특수 상황용)
    """
    print(f"[{room_id}] set_turn_phase 호출됨: {phase}, reason={reason}")
    room = get_room(room_id)
    if not room:
        print(f"[{room_id}] set_turn_phase 실패: room not found")
        return
    gs = room.game_state
    player = get_current_player(gs)
    if not gs or not player:
        print(f"[{room_id}] set_turn_phase 실패: gs or player not found")
        return

    # 1. 기존 타이머 취소
    if gs.turn_timer:
        gs.turn_timer.cancel()
        gs.turn_timer = None

    # 2. 상태 변경
    gs.turn_phase = phase
    if phase != "PLACE_JOKER":
        gs.drawn_tile = None
        gs.pending_placement = False
        gs.can_place_anywhere = False
    
    print(f"[{room_id}] {player.nickname} 페이즈 변경: {phase}")

    # 3. 클라이언트에 현재 턴 정보 전송 (페이즈 변경 알림은 항상 전송)
    emit_data = {
            "phase": phase,
            "timer": TURN_TIMER_SECONDS,
            "currentTurnUid": player.uid,
            "reason": reason  # 🔥 [NEW] 타임아웃 등 사유 전달
        }
    
    # 👈 [복구] DRAWING 단계일 때만 뽑을 수 있는 타일 정보 전송
    if phase == "DRAWING":
        available_piles = []
        if gs.piles["black"]: available_piles.append("black")
        if gs.piles["white"]: available_piles.append("white")
        emit_data["available_piles"] = available_piles

    print(f"[{room_id}] game:turn_phase_start 이벤트 전송 시도: {emit_data}")
    socketio.emit("game:turn_phase_start", emit_data, room=room_id)
    print(f"[{room_id}] game:turn_phase_start 이벤트 전송 완료")

    # 5. 새 타이머 시작 (ANIMATING_GUESS 제외)
    # 🔥 [FIX] 상태 브로드캐스트 전에 시간 초기화해야 함
    if phase != "ANIMATING_GUESS":
        gs.turn_start_time = time.time() # 🔥 [NEW] 턴 시작 시간 기록
        gs.turn_timer = Timer(
            TURN_TIMER_SECONDS,
            lambda: handle_timeout(room_id, player.uid, phase)
        )
        gs.turn_timer.start()

    # 4. 전체 상태 브로드캐스트 (옵션)
    if broadcast:
        broadcast_in_game_state(room_id)


def eliminate_player(room_id: str, player: Player, reason: str = "eliminated"):
    """
    플레이어를 탈락 처리하고 관련 정산 및 게임 종료 확인을 수행하는 공통 함수
    reason: "timeout", "disconnect", "wrong_guess" (future use)
    """
    room = get_room(room_id)
    if not room: return False
    gs = room.game_state
    if not gs: return False

    print(f"💀 [Eliminate] Eliminating {player.nickname} (Reason: {reason})")

    # 1. 모든 카드 공개
    for tile in player.hand:
        tile.revealed = True
    print(f"🃏 [Eliminate] All cards revealed for {player.nickname}")

    # 2. 순위 산정 (현재 순위 없는 사람 수 = 내 순위)
    if player.final_rank == 0:
        unranked_players = [p for p in gs.players if p.final_rank == 0]
        unranked_count = len(unranked_players)
        player.final_rank = unranked_count
        print(f"🥇 [Eliminate] Rank assigned: {player.final_rank} (unranked_count was {unranked_count})")
        
        socketio.emit("game:player_eliminated", {
            "uid": player.uid,
            "nickname": player.nickname,
            "rank": player.final_rank
        }, room=room_id)

        # 3. 즉시 패배 정산 (돈 차감)
        if not player.settled:
            net_change = -player.bet_amount
            player.money += net_change
            player.settled = True
            
            payout_data = {
                "uid": player.uid,
                "nickname": player.nickname,
                "rank": player.final_rank,
                "bet": player.bet_amount,
                "net_change": net_change,
                "new_total": player.money
            }
            if gs.payout_results is None: gs.payout_results = []
            gs.payout_results.append(payout_data)
            
            socketio.emit("game:payout_result", [payout_data], room=room_id)
            print(f"💰 [Eliminate] Settlement processed. Net: {net_change}")

            # Firestore 업데이트
            if FIREBASE_AVAILABLE:
                update_user_money_async(player.uid, net_change, player.nickname)

    # 4. 상태 업데이트 전송
    broadcast_in_game_state(room_id)

    # 5. 게임 종료 조건 확인 (남은 순위 없는 플레이어가 1명 이하)
    unranked_remaining = [p for p in gs.players if p.final_rank == 0]
    print(f"🔍 [Eliminate] Checking game end: unranked_remaining={len(unranked_remaining)}")
    
    if len(unranked_remaining) <= 1:
        print(f"🏆 게임 종료! ({reason}로 인한 종료)")
        if len(unranked_remaining) == 1:
            winner = unranked_remaining[0]
            winner.final_rank = 1
            print(f"🏆 [DEBUG] Winner {winner.nickname} assigned rank 1")
        
        payout_results = handle_winnings(room_id)
        
        winner = next((p for p in gs.players if p.final_rank == 1), None)
        
        # 🔥 [FIX] Omok phase update
        if getattr(gs, 'game_type', 'davinci') == 'omok' and gs.game_state:
            gs.game_state.phase = 'GAME_OVER'
            gs.game_state.winner = winner
            # Broadcast state so OmokView sees phase change
            broadcast_in_game_state(room_id)
        


        socketio.emit("game_over", {
            "winner": {"name": winner.nickname if winner else "Unknown"},
            "payouts": payout_results
        }, room=room_id)
        return True # 게임 종료됨
    
    return False # 게임 계속됨


def handle_timeout(room_id: str, player_uid: str, expected_phase: TurnPhase):
    """타임아웃 처리 -> 플레이어 탈락(패배) 처리"""
    room = rooms.get(room_id)

    if not room:
        print(f"타임아웃 무시: room {room_id}가 이미 삭제됨.")
        return
    gs = room.game_state
    if not gs: return

    player = get_current_player(gs)

    # 🔥 [FIX] Support both turn_phase (Davinci) and phase (Omok)
    current_phase = getattr(gs, 'turn_phase', getattr(gs, 'phase', 'PLAYING'))

    if not player or player.uid != player_uid or current_phase != expected_phase:
        print(f"타임아웃 무시: (uid: {player_uid}, phase: {expected_phase}, current: {current_phase})")
        return

    print(f"⏰ 타임아웃 발생! {player.nickname} 님을 탈락 처리합니다.")
    
    # 타이머 취소
    if gs.turn_timer:
        gs.turn_timer.cancel()
        gs.turn_timer = None
    
    # 🔥 [FIX] 타임아웃 = 패배 처리
    game_ended = eliminate_player(room_id, player, reason="timeout")

    if not game_ended:
        # 게임이 안 끝났으면 다음 턴으로
        start_next_turn(room_id, reason="timeout")


# ... (이벤트 핸들러들 생략) ...

def handle_winnings(room_id: str):
    """(수정) 게임 종료 후 랭킹과 개인 베팅 금액에 따라 화폐를 계산하고 정산"""
    print(f"💰 [handle_winnings] Called for {room_id}")
    room = get_room(room_id)
    if not room: return
    gs = room.game_state
    if not gs: return

    # 1. Assign ranks: winner gets 1, others get sequential ranks based on existing final_rank or order
    # 🔥 [DEBUG] Print current ranks before assignment
    print(f"🔍 [DEBUG] Ranks before handle_winnings assignment:")
    for p in gs.players:
        print(f"  - {p.nickname}: final_rank={p.final_rank}, settled={p.settled}")
    
    # Find any player without a rank (final_rank == 0) as the winner
    winner = next((p for p in gs.players if p.final_rank == 0), None)
    if winner:
        winner.final_rank = 1
        print(f"🏆 [DEBUG] Assigned rank 1 to winner: {winner.nickname}")
    # Assign ranks to remaining players who still have rank 0
    next_rank = 2
    for p in gs.players:
        if p.final_rank == 0:
            p.final_rank = next_rank
            print(f"🔢 [DEBUG] Assigned rank {next_rank} to {p.nickname}")
            next_rank += 1
    
    # 🔥 [DEBUG] Print final ranks
    print(f"🔍 [DEBUG] Ranks after handle_winnings assignment:")
    for p in gs.players:
        print(f"  - {p.nickname}: final_rank={p.final_rank}")

    payout_results = []
    
    # 2. 계산
    # 2. 계산 (모든 플레이어 순회)
    for player in gs.players:
        bet = player.bet_amount
        net_change = 0
        rank = player.final_rank
        
        # 이미 정산된 플레이어(중도 퇴장 등)도 결과 리스트에는 포함해야 함
            # 이미 정산된 플레이어(중도 퇴장 등)도 결과 리스트에는 포함해야 함
        if player.settled:
            # 이미 정산되었으므로 money 업데이트는 건너뛰고 결과만 추가
            if rank == 1:
                net_change = +(bet) # 🔥 [FIX] 2배 -> 1배 (Profit)
            else:
                net_change = -bet
        else:
            # 정산 안 된 플레이어 (끝까지 남은 사람들)
            if rank == 1:
                # 🔥 [FIX] Game Type based multiplier
                g_type = getattr(room, 'game_type', 'davinci')
                multiplier = 1 if str(g_type).lower() in ['omok', 'indian_poker'] else 3
                print(f"💰 [Payout] RoomType: {type(room)}, GameType: {g_type} (str: {str(g_type).lower()}), Multiplier: {multiplier}")
                net_change = +(bet * multiplier) # 🔥 나머지는 베팅 금액 차감 (패배)
            else:
                net_change = -bet # 🔥 나머지는 베팅 금액 차감 (패배)
            
            # 3. Player.money 업데이트
            player.money += net_change
            player.settled = True # 정산 완료 표시

            # 🔥 [NEW] Firestore 업데이트 (비동기)
            if FIREBASE_AVAILABLE:
                update_user_money_async(player.uid, net_change, player.nickname)

        payout_results.append({
            "uid": player.uid,
            "nickname": player.nickname,
            "rank": rank,
            "bet": bet,
            "net_change": net_change,
            "new_total": player.money
        })

    print(f"💸 정산 결과 ({room_id}): {payout_results}")
    
    # 5. 모든 클라이언트에게 정산 결과 브로드캐스트
    if payout_results:
        gs.payout_results = payout_results # 🔥 [NEW] 결과 저장 (재접속 시 전송용)
        socketio.emit("game:payout_result", payout_results, room=room_id)
    else:
        print(f"⚠️ 정산 결과 없음 ({room_id}) - 이미 처리됨?")
    
    print(f"[{room_id}] 게임 정산 완료. 순위별 정산 처리됨.")
    
    return payout_results

    # 🔥 [추가] 방 삭제 (리소스 정리)
    # 클라이언트가 결과를 볼 시간을 주기 위해 타이머로 삭제하거나,
    # 여기서는 즉시 삭제하되 메모리에서만 지우고 소켓 룸은 유지될 수 있음.
    # 안전하게 10초 후 삭제하도록 설정
    def delete_room():
        if room_id in rooms:
            del rooms[room_id]
            print(f"🗑️ 방 삭제 완료: {room_id}")
    
    Timer(10.0, delete_room).start()

@socketio.on("draw_tile")
def on_draw_tile(data):
    """플레이어가 덱에서 카드를 뽑을 때"""
    room_id = data.get("roomId")
    handler = DavinciHandler()
    handler.handle_action(room_id, "draw_tile", data, request.sid)

@socketio.on("place_joker")
def on_place_joker(data):
    """플레이어가 조커를 배치할 위치를 선택했을 때"""
    room_id = data.get("roomId")
    handler = DavinciHandler()
    handler.handle_action(room_id, "place_joker", data, request.sid)

@socketio.on("guess_value")
def on_guess_value(data):
    """플레이어가 추리를 시도할 때"""
    room_id = data.get("roomId")
    handler = DavinciHandler()
    handler.handle_action(room_id, "guess_value", data, request.sid)

@socketio.on("stop_guessing")
def on_stop_guessing(data):
    """플레이어가 연속 추리를 멈추고 턴을 넘길 때 호출됨"""
    room_id = data.get("roomId")
    handler = DavinciHandler()
    handler.handle_action(room_id, "stop_guessing", data, request.sid)
@socketio.on("game:animation_done")
def on_animation_done(data):
    """클라이언트가 추리 결과 애니메이션을 완료했을 때 호출됨"""
    room_id = data.get("roomId")
    handler = DavinciHandler()
    handler.handle_action(room_id, "animation_done", data, request.sid)

@socketio.on("request_game_state")
def on_request_game_state(data):
    """(신규) 프론트엔드가 게임 페이지 로드 직후 호출하는 함수"""
    room_id = data.get("roomId")
    uid = data.get('uid')
    print(f"🔍 [Debug] request_game_state called. Room: {room_id}, UID: {uid}, SID: {request.sid}")
    
    # 🔥 Direct Echo Test
    socketio.emit('debug_echo', {'message': 'Hello from Backend', 'sid': request.sid}, room=request.sid)

    if not room_id: 
        print("❌ [Debug] No room_id provided")
        return

    gs = get_room(room_id)
    
    # 🔥 [Resurrection] If room missing but players provided, recreate it
    if not gs and data.get('players'):
        print(f"🧟 [Resurrection] Room {room_id} missing. Recreating from frontend data...")
        from models import Room, Player
        from utils import rooms
        
        new_room = Room(room_id=room_id)
        new_room.game_type = 'indian_poker' # Assume Indian Poker for now
        
        recreated_players = []
        for p_data in data['players']:
            # Create player with minimal required fields
            p = Player(
                sid=request.sid if p_data.get('uid') == uid else 'offline', # Assign current SID to me, others offline
                uid=p_data.get('uid'),
                nickname=p_data.get('nickname', 'Unknown')
            )
            p.character = p_data.get('character')
            p.money = p_data.get('money', 100)
            recreated_players.append(p)
            
        new_room.players = recreated_players
        rooms[room_id] = new_room
        gs = new_room
        print(f"✅ [Resurrection] Room {room_id} restored with {len(gs.players)} players.")

    if not gs: 
        print(f"❌ [Debug] Room {room_id} not found in get_room()")
        return

    print(f"✅ [Debug] Room found. GameType: {getattr(gs, 'game_type', 'davinci')}, Players: {len(gs.players)}")

    # 🔥 [FIX] Self-healing logic for Indian Poker
    if getattr(gs, 'game_type', 'davinci') == 'indian_poker':
        # 🔥 [NEW] Sync SID if UID provided (Fixes reconnection/refresh issues)
        if uid:
            for p in gs.players:
                if p.uid == uid:
                    if p.sid != request.sid:
                        print(f"🔄 [Sync] Updating SID for {p.nickname}: {p.sid} -> {request.sid}")
                        p.sid = request.sid
                    else:
                        print(f"✅ [Sync] SID matches for {p.nickname}")
                    break
        else:
            print("⚠️ [Debug] No UID provided for SID sync")

        if gs.game_state is None:
            print(f"🔧 [Self-Healing] {room_id} IndianPokerLogic missing. Initializing...")
            gs.game_state = IndianPokerLogic(gs.players)
            gs.game_state.game_started = True
        else:
            print(f"✅ [Debug] GameState exists. Round: {gs.game_state.current_round}")
        
        if gs.game_state.current_round == 0:
            print(f"🔧 [Self-Healing] {room_id} Round 0 detected. Forcing start_round()...")
            gs.game_state.start_round()
            
        # Use handler to send specific state
        print(f"🚀 [Debug] Calling IndianPokerHandler.start_turn for Room {room_id}")
        IndianPokerHandler().start_turn(room_id, gs)
        print(f"[{room_id}] Indian Poker state synced (Self-Healed)")
        return

    # 현재 게임 상태 전체를 브로드캐스트 (혹은 요청자에게만 전송)
    # broadcast_in_game_state 함수가 이미 구현되어 있으므로 활용
    broadcast_in_game_state(room_id)
    
    print(f"[{room_id}] 클라이언트의 요청으로 게임 상태 동기화 전송")


@socketio.on("leave_game")
def on_leave_game(data):
    room_id = data.get("roomId")
    sid = request.sid
    print(f"<- 방 이탈: {sid} left room {room_id}")

    if room_id not in rooms:
        return

    gs = rooms[room_id]
    player = find_player_by_sid(gs, sid)
    
    if not player:
        return

    try:
        # 1. 게임 중이라면 패배 처리 및 정산
        # 🔥 [FIX] Handle Room object
        game_state = gs.game_state if hasattr(gs, 'game_state') else gs
        
        has_cards = len(player.hand) > 0
        
        # Check game_started based on game type
        game_started = False
        if getattr(gs, 'game_type', 'davinci') == 'omok':
             if game_state and getattr(game_state, 'phase', 'INIT') != 'INIT':
                 game_started = True
        elif getattr(gs, 'game_type', 'davinci') == 'indian_poker':
             game_started = True
        else:
            # Davinci
            if game_state:
                if hasattr(game_state, 'game_started'):
                    game_started = game_state.game_started
                elif hasattr(game_state, 'turn_phase'):
                    game_started = (game_state.turn_phase != "INIT") or has_cards

        if game_started:
            print(f"⚠️ {player.nickname} 님이 나가기 버튼을 눌러 패배 처리됩니다.")
            TURN_TIMER_SECONDS = 60
            # 1. 기존 타이머 취소
            # 1. 기존 타이머 취소
            if game_state and hasattr(game_state, 'turn_timer') and game_state.turn_timer:
                game_state.turn_timer.cancel()
                game_state.turn_timer = None
            
            # 🔥 [FIX] Use eliminate_player helper
            game_ended = eliminate_player(room_id, player, reason="disconnect")

            # 3. 턴 넘기기 (만약 내 턴이었다면)
            if not game_ended:
                is_omok = getattr(gs, 'game_type', 'davinci') == 'omok'
                should_pass_turn = False
                
                # Omok is 2-player, so game_ended should be True if one leaves.
                # This block is mainly for Davinci (>2 players)
                if not is_omok:
                    if game_state and hasattr(game_state, 'current_turn') and game_state.players:
                        if game_state.current_turn < len(game_state.players):
                            if game_state.players[game_state.current_turn].sid == player.sid:
                                should_pass_turn = True

                if should_pass_turn:
                    print("내 턴에 나갔으므로 턴을 넘깁니다.")
                    if game_state and hasattr(game_state, 'turn_timer') and game_state.turn_timer:
                        game_state.turn_timer.cancel()
                    
                    from game_events import start_next_turn
                    start_next_turn(room_id)

        # 2. 플레이어 제거 (게임 중이 아닐 때만!)
        if not game_started:
            if player in gs.players:
                # 게임 시작 로직
                if room.game_type == 'omok':
                    room.game_state = OmokLogic(room.players)
                else:
                    room.game_state = GameLogic(room.players)
                    
                room.status = 'playing'

            # 3. 방이 비었거나 로비 상태라면 정리
            if gs.players:
                for i, p in enumerate(gs.players):
                    p.id = i
                socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)
            else:
                print(f"🗑️ Room {room_id} is empty, deleting.")
                if room_id in rooms:
                    del rooms[room_id]
        else:
            print(f"🚫 게임 중이므로 {player.nickname}를 목록에서 제거하지 않음 (재접속/정산 보존)")

    except Exception as e:
        print(f"❌ Error in on_leave_game: {e}")

@socketio.on("omok:place_stone")
def on_omok_place_stone(data):
    """오목 돌 두기 요청"""
    room_id = data.get("roomId")
    handler = OmokHandler()
    handler.handle_action(room_id, "place_stone", data, request.sid)

@socketio.on("indian_poker:bet")
def on_indian_poker_bet(data):
    room_id = data.get("roomId")
    handler = IndianPokerHandler()
    handler.handle_action(room_id, "bet", data, request.sid)

@socketio.on("indian_poker:next_round")
def on_indian_poker_next_round(data):
    room_id = data.get("roomId")
    handler = IndianPokerHandler()
    handler.handle_action(room_id, "next_round", data, request.sid)




