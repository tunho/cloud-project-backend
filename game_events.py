# game_events.py
import random
import time # 👈 time 임포트
from threading import Timer
from flask import request
from flask_socketio import emit
from extensions import socketio
from state import rooms
from models import GameState, Player, Color, TurnPhase, Optional # 👈 TurnPhase 임포트
from utils import (
    find_player_by_sid, find_player_by_uid, get_room, 
    broadcast_in_game_state, serialize_state_for_lobby
)
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
    prepare_tiles(gs)        # 검정/흰색 타일 섞기
    deal_initial_hands(gs)   # 플레이어들에게 초기 패 분배 (3개 또는 4개)

    # 3. 상태 플래그 설정
    gs.game_started = True
    gs.current_turn = -1     # start_next_turn에서 +1을 하여 0번(첫 번째) 플레이어가 되도록 설정

    # 4. 프론트엔드에 '게임 시작' 알림 (Lobby -> Game 화면 전환용)
    socketio.emit("game_started", {"roomId": room_id}, room=room_id)
    print(f"📡 game_started 이벤트 전송 완료 -> 프론트엔드 씬 전환 대기")

    # 5. 프론트엔드 로딩 대기 (Vue 컴포넌트가 마운트되고 소켓 리스너를 켤 시간 확보)
    socketio.sleep(1)

    # 6. 첫 번째 턴 시작 (DRAWING 단계로 진입)
    start_next_turn(room_id)


def start_next_turn(room_id: str):
    """(수정) 다음 턴을 시작 (드로우 또는 추리) - 플레이어 퇴장 시에도 안정적"""
    gs = get_room(room_id)
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

    print(f"--- 턴 시작 ({player.name}) ---")
    
    # [수정] 턴 페이즈 결정
    piles_empty = not gs.piles["black"] and not gs.piles["white"]
    
    if piles_empty:
        # 더미가 없으면 바로 '추리'
        set_turn_phase(room_id, "GUESSING")
    else:
        # 👈 [복구] 더미가 있으면 '드로우' 단계
        set_turn_phase(room_id, "DRAWING")

def set_turn_phase(room_id: str, phase: TurnPhase, broadcast: bool = True):
    """
    (수정) 지정된 페이즈로 상태 변경 (DRAWING 로직 포함)
    broadcast: False이면 상태 전송을 건너뜀 (애니메이션 등 특수 상황용)
    """
    gs = get_room(room_id)
    player = get_current_player(gs)
    if not gs or not player:
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
    
    print(f"[{room_id}] {player.name} 님의 페이즈 변경 -> {phase}")

    # 3. 클라이언트에 현재 턴 정보 전송 (페이즈 변경 알림은 항상 전송)
    emit_data = {
            "phase": phase,
            "timer": TURN_TIMER_SECONDS,
            "currentTurnUid": player.uid 
        }
    
    # 👈 [복구] DRAWING 단계일 때만 뽑을 수 있는 타일 정보 전송
    if phase == "DRAWING":
        available_piles = []
        if gs.piles["black"]: available_piles.append("black")
        if gs.piles["white"]: available_piles.append("white")
        emit_data["available_piles"] = available_piles

    socketio.emit("game:turn_phase_start", emit_data, room=room_id)

    # 4. 전체 상태 브로드캐스트 (옵션)
    if broadcast:
        broadcast_in_game_state(room_id)

    # 5. 새 타이머 시작 (ANIMATING_GUESS 제외)
    if phase != "ANIMATING_GUESS":
        gs.turn_start_time = time.time() # 🔥 [NEW] 턴 시작 시간 기록
        gs.turn_timer = Timer(
            TURN_TIMER_SECONDS,
            lambda: handle_timeout(room_id, player.uid, phase)
        )
        gs.turn_timer.start()


def handle_timeout(room_id: str, player_uid: str, expected_phase: TurnPhase):
    """(수정) 타임아웃 처리 -> 기권(탈주) 처리"""
    gs = rooms.get(room_id)

    if not gs:
        print(f"타임아웃 무시: room {room_id}가 이미 삭제됨.")
        return

    player = get_current_player(gs)

    if not player or player.uid != player_uid or gs.turn_phase != expected_phase:
        print(f"타임아웃 무시: (uid: {player_uid}, phase: {expected_phase})")
        return

    print(f"⏰ 타임아웃 발생! {player.name} / {expected_phase} -> 기권 처리")
    
    # 🔥 [수정] 시간 초과 시 강제 퇴장(패배) 처리
    # on_leave_game 로직을 재사용하기 위해 소켓 이벤트 핸들러 호출과 유사하게 처리
    # 단, request context가 없을 수 있으므로 로직을 분리하거나 직접 처리해야 함.
    # 여기서는 on_leave_game을 직접 호출하기 어려우므로(request.sid 의존), 
    # 핵심 로직을 수행하고 턴을 넘김.

    # 1. 모든 카드 공개
    for tile in player.hand:
        tile.revealed = True
    
    # 2. 탈락 처리
    if player.final_rank == 0:
        alive_players = get_alive_players(gs)
        alive_count = len(alive_players)
        player.final_rank = alive_count + 1
        
        socketio.emit("game:player_eliminated", {
            "uid": player.uid,
            "nickname": player.nickname,
            "rank": player.final_rank
        }, room=room_id)

        # 즉시 패배 정산
        if not player.settled:
            net_change = -player.bet_amount
            player.money += net_change
            player.settled = True
            
            # 🔥 [NEW] Firestore 업데이트 (타임아웃 패널티)
            if FIREBASE_AVAILABLE:
                try:
                    db = get_db()
                    if db:
                        user_ref = db.collection('users').document(player.uid)
                        user_ref.update({
                            'money': admin_firestore.Increment(net_change)
                        })
                        print(f"💰 Firestore updated (timeout): {player.nickname} {net_change:+d}")
                except Exception as e:
                    print(f"❌ Firestore error: {e}")
            
            socketio.emit("game:payout_result", [{
                "uid": player.uid,
                "nickname": player.nickname,
                "rank": player.final_rank,
                "bet": player.bet_amount,
                "net_change": net_change,
                "new_total": player.money
            }], room=room_id)

    # 3. 상태 업데이트 (카드 공개됨)
    broadcast_in_game_state(room_id)

    # 4. 게임 종료 여부 확인
    alive_players = get_alive_players(gs)
    if len(alive_players) <= 1:
        print(f"🏆 게임 종료! (시간 초과로 인한 종료)")
        if len(alive_players) == 1:
            survivor = alive_players[0]
            survivor.final_rank = 1
        
        handle_winnings(room_id)
        
        winner = next((p for p in gs.players if p.final_rank == 1), None)
        print(f"🏆 Sending game_over for {room_id}. Winner: {winner.nickname if winner else 'Unknown'}")
        socketio.emit("game_over", {
            "winner": {"name": winner.nickname if winner else "Unknown"}
        }, room=room_id)
        return

    # 5. 게임이 안 끝났다면 다음 턴으로
    start_next_turn(room_id)


# ... (이벤트 핸들러들 생략) ...

def handle_winnings(room_id: str):
    """(수정) 게임 종료 후 랭킹과 개인 베팅 금액에 따라 화폐를 계산하고 정산"""
    gs = get_room(room_id)
    if not gs: return

    # 1. 승리 시 1등(마지막 생존자)에게 1등 순위를 부여
    winner = next((p for p in gs.players if p.final_rank == 0), None)
    if winner:
        winner.final_rank = 1 

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

            # 🔥 [NEW] Firestore 업데이트
            if FIREBASE_AVAILABLE:
                try:
                    db = get_db()
                    if db:
                        user_ref = db.collection('users').document(player.uid)
                        user_ref.update({
                            'money': admin_firestore.Increment(net_change)
                        })
                        print(f"💰 Firestore updated: {player.nickname} {net_change:+d} → {player.money}")
                except Exception as e:
                    print(f"❌ Firestore error for {player.uid}: {e}")

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
        print(f"💸 Payout Results for {room_id}: {payout_results}")
        socketio.emit("game:payout_result", payout_results, room=room_id)
    else:
        print(f"⚠️ No payout results for {room_id} (maybe already settled?)")
    
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
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    
    if not gs or not player:
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
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    
    if not gs or not player:
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
    
    gs = get_room(room_id)
    guesser = find_player_by_sid(gs, request.sid)
    
    if not gs or not guesser:
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
    gs = get_room(room_id)
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
    
    gs = get_room(room_id)
    player = find_player_by_uid(gs, guesser_uid)
    
    # 검증: 현재 턴 플레이어만 이 신호를 보낼 수 있게 함 (중복 처리 방지)
    if not player or gs.players[gs.current_turn].uid != player.uid:
        return 

    if gs.turn_phase != "ANIMATING_GUESS":
        # 이미 처리되었거나 페이즈가 안 맞으면 무시
        return

    print(f"[{room_id}] {player.nickname} 애니메이션 완료. 결과: {correct}")

    # 1. 탈락자 처리 및 순위 산정
    alive_players = get_alive_players(gs)
    alive_count = len(alive_players)
    
    # 방금 탈락한 플레이어 찾기 (final_rank가 0인데 eliminated 상태인 경우)
    for p in gs.players:
        if p.final_rank == 0 and is_player_eliminated(p):
            # 탈락 확정!
            # 순위 부여: (현재 생존자 수 + 1) -> 왜냐하면 방금 탈락했으므로
            # 예: 4명 시작 -> 1명 탈락 -> 생존 3명 -> 탈락자는 4등
            # 예: 3명 생존 -> 1명 탈락 -> 생존 2명 -> 탈락자는 3등
            # 주의: alive_players에는 이미 p가 제외되어 있음.
            p.final_rank = alive_count + 1
            
            print(f"💀 플레이어 탈락: {p.nickname} (Rank: {p.final_rank})")
            socketio.emit("game:player_eliminated", {
                "uid": p.uid,
                "nickname": p.nickname,
                "rank": p.final_rank
            }, room=room_id)

            # 🔥 [NEW] 즉시 패배 정산 (돈 차감)
            if not p.settled:
                net_change = -p.bet_amount
                p.money += net_change
                p.settled = True
                
                print(f"💰 [Settlement] Player {p.nickname} eliminated. Bet: {p.bet_amount}, Net: {net_change}") # 🔥 [LOG]

                # Firestore 업데이트 (패배 패널티)
                if FIREBASE_AVAILABLE:
                    try:
                        db = get_db()
                        if db:
                            user_ref = db.collection('users').document(p.uid)
                            user_ref.update({
                                'money': admin_firestore.Increment(net_change)
                            })
                            print(f"💰 Firestore updated (eliminated): {p.nickname} {net_change:+d}")
                    except Exception as e:
                        print(f"❌ Firestore error: {e}")
                
                # 정산 결과 전송 -> GameOverModal 띄우기 위함
                socketio.emit("game:payout_result", [{
                    "uid": p.uid,
                    "nickname": p.nickname,
                    "rank": p.final_rank,
                    "bet": p.bet_amount,
                    "net_change": net_change,
                    "new_total": p.money
                }], room=room_id)

    # 2. 게임 종료 조건 확인 (생존자가 1명 이하일 때)
    # (2명 이상 게임이므로 1명이 남으면 종료)
    if alive_count <= 1:
        print(f"🏆 게임 종료! 생존자 수: {alive_count}")
        
        # 마지막 생존자에게 1등 부여
        if alive_count == 1:
            survivor = alive_players[0]
            survivor.final_rank = 1
        
        # 정산 및 종료 처리
        handle_winnings(room_id)
        
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
    """(신규) 플레이어가 게임 도중 나갔을 때 처리"""
    room_id = data.get("roomId")
    if not room_id: return

    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    if not gs or not player: return

    print(f"🚪 플레이어 퇴장: {player.nickname} ({player.uid})")

    # 1. 모든 카드 공개 처리
    for tile in player.hand:
        tile.revealed = True
    
    # 2. 탈락 처리 및 순위 산정
    if player.final_rank == 0:
        alive_players = get_alive_players(gs)
        alive_count = len(alive_players)
        player.final_rank = alive_count + 1
        
        socketio.emit("game:player_eliminated", {
            "uid": player.uid,
            "nickname": player.nickname,
            "rank": player.final_rank
        }, room=room_id)

        # 🔥 [추가] 즉시 패배 정산 (돈 차감)
        if not player.settled:
            net_change = -player.bet_amount
            player.money += net_change
            player.settled = True
            
            # 🔥 [NEW] Firestore 업데이트 (중도 퇴장 패널티)
            if FIREBASE_AVAILABLE:
                try:
                    db = get_db()
                    if db:
                        user_ref = db.collection('users').document(player.uid)
                        user_ref.update({
                            'money': admin_firestore.Increment(net_change)
                        })
                        print(f"💰 Firestore updated (leave): {player.nickname} {net_change:+d}")
                except Exception as e:
                    print(f"❌ Firestore error: {e}")
            
            # 나에게만(혹은 모두에게) 정산 결과 전송 -> GameOverModal 띄우기 위함
            socketio.emit("game:payout_result", [{
                "uid": player.uid,
                "nickname": player.nickname,
                "rank": player.final_rank,
                "bet": player.bet_amount,
                "net_change": net_change,
                "new_total": player.money
            }], room=room_id)

    # 3. 턴 넘기기 (만약 내 턴이었다면)
    if gs.players[gs.current_turn].sid == player.sid:
        print("내 턴에 나갔으므로 턴을 넘깁니다.")
        if gs.turn_timer: gs.turn_timer.cancel()
        start_next_turn(room_id)
    else:
        # 내 턴이 아니더라도 상태 업데이트는 필요 (카드 공개됨)
        broadcast_in_game_state(room_id)

    # 4. 게임 종료 조건 확인 (남은 사람이 1명 이하)
    alive_players = get_alive_players(gs)
    if len(alive_players) <= 1:
        print(f"🏆 게임 종료! (퇴장으로 인한 종료)")
        if len(alive_players) == 1:
            survivor = alive_players[0]
            survivor.final_rank = 1
        
        handle_winnings(room_id)
        
        winner = next((p for p in gs.players if p.final_rank == 1), None)
        print(f"🏆 Sending game_over for {room_id}. Winner: {winner.nickname if winner else 'Unknown'}")
        socketio.emit("game_over", {
            "winner": {"name": winner.nickname if winner else "Unknown"}
        }, room=room_id)