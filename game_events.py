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
from models import Player, Color, TurnPhase, Optional, GameState # 👈 GameState 추가
from state import rooms # 👈 rooms 임포트
from utils import find_player_by_sid, find_player_by_uid, get_room, broadcast_in_game_state, serialize_state_for_lobby, update_user_money_async

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

def get_current_player(gs: GameState) -> Optional[Player]:
    if not gs.players:
        return None
    return gs.players[gs.current_turn % len(gs.players)]

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
    socketio.sleep(1)

    # 6. 첫 번째 턴 시작
    if gs.game_type == 'omok':
        start_omok_turn(room_id)
    else:
        gs.game_state.current_turn = -1
        start_next_turn(room_id)


def start_omok_turn(room_id: str):
    """오목 턴 시작 알림"""
    gs = get_room(room_id)
    if not gs or not gs.game_state: return
    
    omok_logic = gs.game_state
    current_player = omok_logic.players[omok_logic.current_turn_index]
    
    print(f"--- [Omok] {current_player.nickname} 님의 턴 시작 ---")
    
    socketio.emit("omok:turn_start", {
        "currentTurnUid": current_player.uid,
        "timer": 30 # 오목 턴 시간
    }, room=room_id)


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
        
        handle_winnings(room_id)
        
        winner = next((p for p in gs.players if p.final_rank == 1), None)
        socketio.emit("game_over", {
            "winner": {"name": winner.nickname if winner else "Unknown"}
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

    if not player or player.uid != player_uid or gs.turn_phase != expected_phase:
        print(f"타임아웃 무시: (uid: {player_uid}, phase: {expected_phase})")
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
        if player.settled:
            # 이미 정산되었으므로 money 업데이트는 건너뛰고 결과만 추가
            # net_change는 역산하거나 0으로 표시 (여기서는 0으로 표시하되, 최종 금액은 반영됨)
            # 정확한 net_change를 알기 위해선 별도 저장이 필요하지만, 
            # 일단 현재 로직상 1등 아니면 -bet 이었을 것임.
            if rank == 1:
                net_change = +(bet * 3)
            else:
                net_change = -bet
        else:
            # 정산 안 된 플레이어 (끝까지 남은 사람들)
            if rank == 1:
                net_change = +(bet * 3) # 🔥 1등은 베팅 금액의 3배 획득
            else:
                net_change = -bet # 🔥 나머지는 베팅 금액 차감 (패배)
            
            # 3. Player.money 업데이트
            player.money += net_change
            player.settled = True # 정산 완료 표시

            # 🔥 [NEW] Firestore 업데이트 (비동기)
            if FIREBASE_AVAILABLE:
                update_user_money_async(player.uid, net_change, player.nickname)

        # 4. 프론트엔드/DB 업데이트를 위한 결과 저장 (모든 플레이어 포함)
        payout_results.append({
            "uid": player.uid,
            "nickname": player.nickname,
            "rank": rank,
            "bet": bet,
            "net_change": net_change,
            "new_total": player.money
        })

    # 5. 모든 클라이언트에게 정산 결과 브로드캐스트
    if payout_results:
        gs.payout_results = payout_results # 🔥 [NEW] 결과 저장 (재접속 시 전송용)
        print(f"💸 정산 결과 ({room_id}): {payout_results}")
        socketio.emit("game:payout_result", payout_results, room=room_id)
    else:
        print(f"⚠️ 정산 결과 없음 ({room_id}) - 이미 처리됨?")
    
    print(f"[{room_id}] 게임 정산 완료. 순위별 정산 처리됨.")

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
    color = data.get("color")  # "black" or "white"
    
    room = get_room(room_id)
    if not room: return
    gs = room.game_state
    if not gs: return
    
    player = find_player_by_sid(gs, request.sid)
    
    if not player:
        return
    
    if gs.turn_phase != "DRAWING":
        return
    
    if gs.players[gs.current_turn].sid != player.sid:
        return
    
    # 타일 뽑기 로직 실행
    tile = start_turn_from(gs, player, color)
    
    if not tile:
        return
    
    # 조커인 경우 배치 페이즈로, 아니면 자동 배치
    if tile.is_joker:
        set_turn_phase(room_id, "PLACE_JOKER")
    else:
        auto_place_drawn_tile(gs, player)
        set_turn_phase(room_id, "GUESSING")

@socketio.on("place_joker")
def on_place_joker(data):
    """플레이어가 조커를 배치할 위치를 선택했을 때"""
    room_id = data.get("roomId")
    index = data.get("index")
    
    room = get_room(room_id)
    if not room: return
    gs = room.game_state
    if not gs: return

    player = find_player_by_sid(gs, request.sid)
    
    if not player:
        return
    
    if gs.turn_phase != "PLACE_JOKER":
        return
    
    if gs.players[gs.current_turn].sid != player.sid:
        return
    
    # 조커 배치
    if gs.drawn_tile and gs.drawn_tile.is_joker:
        player.hand.insert(index, gs.drawn_tile)
        player.last_drawn_index = index
        gs.drawn_tile = None
        gs.pending_placement = False
        gs.can_place_anywhere = False
        
        # 추리 페이즈로 전환
        set_turn_phase(room_id, "GUESSING")

@socketio.on("guess_value")
def on_guess_value(data):
    """플레이어가 추리를 시도할 때"""
    room_id = data.get("roomId")
    target_id = data.get("targetId")
    index = data.get("index")
    value = data.get("value")
    
    room = get_room(room_id)
    if not room: return
    gs = room.game_state
    if not gs: return

    guesser = find_player_by_sid(gs, request.sid)
    
    if not guesser:
        return
    
    if gs.turn_phase not in ["GUESSING", "POST_SUCCESS_GUESS"]:
        return
    
    if gs.players[gs.current_turn].sid != guesser.sid:
        return
    
    # 추리 로직 실행
    result = guess_tile(gs, guesser, target_id, index, value)
    
    if not result.get("ok"):
        return
    
    # 애니메이션 페이즈로 전환
    set_turn_phase(room_id, "ANIMATING_GUESS", broadcast=False)
    
    # 🔥 [FIXED] 추리 시작 이벤트 브로드캐스트 (애니메이션 트리거)
    # 프론트엔드는 "game:start_guess_animation"을 listen하고 있음
    socketio.emit("game:start_guess_animation", {
        "guesser_id": guesser.uid,
        "target_id": target_id,
        "index": index,
        "value": value,
        "correct": result.get("correct")
    }, room=room_id)

@socketio.on("stop_guessing")
def on_stop_guessing(data):
    """플레이어가 연속 추리를 멈추고 턴을 넘길 때 호출됨"""
    room_id = data.get("roomId")
    room = get_room(room_id)
    if not room: return
    gs = room.game_state
    if not gs:
        return
    
    player = find_player_by_sid(gs, request.sid)
    if not player:
        return
    
    # 현재 턴인지 확인
    if gs.players[gs.current_turn].sid != player.sid:
        return
    
    print(f"[{room_id}] {player.nickname} 턴 패스")
    
    # 다음 턴으로 넘김
    start_next_turn(room_id)
@socketio.on("game:animation_done")
def on_animation_done(data):
    """클라이언트가 추리 결과 애니메이션을 완료했을 때 호출됨"""
    room_id = data.get("roomId")
    guesser_uid = data.get("guesserUid") 
    correct = data.get("correct") 

    if not room_id or not guesser_uid: return
    
    room = get_room(room_id)
    if not room: return
    gs = room.game_state
    if not gs: return
    player = find_player_by_uid(gs, guesser_uid)
    
    # 검증: 현재 턴 플레이어만 이 신호를 보낼 수 있게 함 (중복 처리 방지)
    if not player or gs.players[gs.current_turn].uid != player.uid:
        return 

    if gs.turn_phase != "ANIMATING_GUESS":
        # 이미 처리되었거나 페이즈가 안 맞으면 무시
        return
    
    # 🔥 [FIX] Race Condition 방지: 즉시 페이즈를 변경하여 중복 실행 막음
    gs.turn_phase = "PROCESSING"

    print(f"[{room_id}] {player.nickname} 애니메이션 완료. 결과: {correct}")

    # 1. 탈락자 처리 및 순위 산정
    # 🔥 [FIX] Count UNRANKED players (final_rank == 0), not just alive players!
    # This ensures correct ranking: 4 players → 1st eliminated gets 4th place
    unranked_players = [p for p in gs.players if p.final_rank == 0]
    unranked_count = len(unranked_players)
    print(f"🔍 [DEBUG] Initial unranked_count: {unranked_count}, unranked: {[p.nickname for p in unranked_players]}")
    
    # 방금 탈락한 플레이어 찾기 (final_rank가 0인데 eliminated 상태인 경우)
    for p in gs.players:
        if p.final_rank == 0 and is_player_eliminated(p):
            # 🔥 [FIX] Use unranked_count (same fix as on_animation_done)
            # Count players who haven't been ranked yet
            # 🔥 [REFACTOR] Use eliminate_player logic here too?
            # For now, keep inline to avoid breaking animation flow, but logic is identical
            p.final_rank = unranked_count
            print(f"🔥 [DEBUG] Assigning rank {unranked_count} to {p.nickname} (was eliminated)")
            unranked_count -= 1

            # Reveal all cards of eliminated player
            for tile in p.hand:
                tile.revealed = True
            print(f"🃏 [Elimination] All cards revealed for {p.nickname}")

            print(f"💀 플레이어 탈락: {p.nickname} (Rank: {p.final_rank})")
            socketio.emit("game:player_eliminated", {
                "uid": p.uid,
                "nickname": p.nickname,
                "rank": p.final_rank
            }, room=room_id)

            # Broadcast updated state so client knows player is eliminated before settlement
            broadcast_in_game_state(room_id)

            # 🔥 [NEW] 즉시 패배 정산 (돈 차감)
            if not p.settled:
                net_change = -p.bet_amount
                p.money += net_change
                p.settled = True

                print(f"💰 [Settlement] Player {p.nickname} eliminated. Bet: {p.bet_amount}, Net: {net_change}") # 🔥 [LOG]
                
                # 정산 결과 저장 및 전송
                payout_data = {
                    "uid": p.uid,
                    "nickname": p.nickname,
                    "rank": p.final_rank,
                    "bet": p.bet_amount,
                    "net_change": net_change,
                    "new_total": p.money
                }
                if gs.payout_results is None: gs.payout_results = []
                gs.payout_results.append(payout_data)

                socketio.emit("game:payout_result", [payout_data], room=room_id)

                # Firestore 업데이트 (패배 패널티 - 비동기)
                if FIREBASE_AVAILABLE:
                    update_user_money_async(p.uid, net_change, p.nickname)

            # Broadcast again after payout result to ensure UI sync
            broadcast_in_game_state(room_id)
 # 🔥 [NEW] 상태 브로드캐스트 (카드 공개 및 탈락 반영)

    # 🔥 [FIX] 게임 종료 체크 전에 반드시 상태 업데이트를 먼저 보냄
    # 그래야 마지막 카드가 뒤집힌 상태(eliminated)가 프론트엔드에 반영됨
    broadcast_in_game_state(room_id)

    # Slight delay before checking game end to allow UI to process state update
    socketio.sleep(0.3)

    # 2. 게임 종료 조건 확인 (순위 없는 플레이어가 1명 이하일 때)
    # 🔥 [FIX] Check unranked_count, not alive_count!
    print(f"🔍 [DEBUG] Checking game end: unranked_count={unranked_count}")
    if unranked_count <= 1:
        print(f"🏆 게임 종료! 순위 없는 플레이어 {unranked_count}명")
        
        # 🔥 [FIX] 마지막 순위 없는 플레이어에게 1등 부여
        if unranked_count == 1:
            # Find the remaining unranked player
            remaining_unranked = [p for p in gs.players if p.final_rank == 0]
            if remaining_unranked:
                winner = remaining_unranked[0]
                winner.final_rank = 1
                print(f"🏆 [DEBUG] Winner {winner.nickname} assigned rank 1")
        
        # 정산 및 종료 처리
        handle_winnings(room_id)

        # Ensure UI receives final state before game_over
        broadcast_in_game_state(room_id)
        socketio.sleep(0.5)

        # 게임 종료 이벤트 전송 (handle_winnings에서 payout_result를 보내지만, 명시적 game_over도 보냄)
        winner = next((p for p in gs.players if p.final_rank == 1), None)
        print(f"🏆 Sending game_over for {room_id}. Winner: {winner.nickname if winner else 'Unknown'}")
        socketio.emit("game_over", {
            "winner": {"name": winner.nickname if winner else "Unknown"}
        }, room=room_id)
        
        # 방 정리 (약간의 딜레이 후)
        # socketio.sleep(10) 
        # del rooms[room_id] # 바로 삭제하면 클라이언트가 결과를 못 봄. 나중에 처리하거나 클라이언트가 나가도록 유도.
        return

    # 3. 상태 업데이트 전송
    broadcast_in_game_state(room_id)

    # 4. 결과에 따른 턴 진행 분기
    if correct:
        # 정답 -> 연속 추리 기회 (단, 내가 탈락했으면 턴 넘김 - 희박하지만 자폭룰이 있다면)
        if is_player_eliminated(player):
             start_next_turn(room_id)
        else:
            set_turn_phase(room_id, "POST_SUCCESS_GUESS")
            # 🔥 [FIX] 연속 추리 시 타이머 리셋 (서버 기준 시간 갱신)
            gs.turn_start_time = time.time()
            
            socketio.emit("game:prompt_continue", 
                          {"timer": TURN_TIMER_SECONDS}, 
                          to=player.sid)
    else:
        # 오답 -> 턴 종료 및 다음 사람
        start_next_turn(room_id)

@socketio.on("request_game_state")
def on_request_game_state(data):
    """(신규) 프론트엔드가 게임 페이지 로드 직후 호출하는 함수"""
    room_id = data.get("roomId")
    if not room_id: return

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
            if gs.turn_timer:
                gs.turn_timer.cancel()
                gs.turn_timer = None
            
            # 🔥 [FIX] Use eliminate_player helper
            game_ended = eliminate_player(room_id, player, reason="disconnect")

            # 3. 턴 넘기기 (만약 내 턴이었다면)
            if not game_ended and gs.players[gs.current_turn].sid == player.sid:
                print("내 턴에 나갔으므로 턴을 넘깁니다.")
                if gs.turn_timer: gs.turn_timer.cancel()

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
    x = data.get("x")
    y = data.get("y")
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    
    if not gs or not player or not gs.game_state:
        return
        
    omok_logic = gs.game_state
    
    # 돌 두기 시도
    success, message = omok_logic.place_stone(player.sid, x, y)
    
    if success:
        # 보드 업데이트 브로드캐스트
        socketio.emit("omok:update_board", {
            "board": omok_logic.board,
            "lastMove": {"x": x, "y": y, "color": omok_logic.board[y][x]}
        }, room=room_id)
        
        # 게임 종료 체크
        if omok_logic.phase == 'GAME_OVER':
            winner = omok_logic.winner
            print(f"🏆 [Omok] Game Over! Winner: {winner.nickname}")
            
            # 정산 처리
            handle_winnings(room_id) # OmokLogic already updated money/pot, but handle_winnings does DB sync/broadcast
            # Note: handle_winnings logic in game_events might be tailored for Davinci.
            # Let's check handle_winnings. If it relies on final_rank, we need to set it.
            
            # Set ranks for handle_winnings
            winner.final_rank = 1
            loser = next(p for p in gs.players if p != winner)
            loser.final_rank = 2
            
            handle_winnings(room_id)
            
            socketio.emit("game_over", {
                "winner": {"name": winner.nickname}
            }, room=room_id)
            
        else:
            # 다음 턴 진행
            start_omok_turn(room_id)
            
    else:
        # 에러 전송
        emit("error_message", {"message": message})
        import traceback
        traceback.print_exc()