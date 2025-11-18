# game_events.py
import random
from threading import Timer
from state import rooms
from flask import request
from flask_socketio import emit
from extensions import socketio
from models import GameState, Player, Color, TurnPhase
from utils import (
    find_player_by_sid, get_room, 
    broadcast_in_game_state, serialize_state_for_lobby 
)
from game_logic import (
    prepare_tiles, deal_initial_hands, start_turn_from, 
    auto_place_drawn_tile, guess_tile
)
from typing import Optional


TURN_TIMER_SECONDS = 30.0

# --- 헬퍼: 턴 관리 ---

def get_current_player(gs: GameState) -> Optional[Player]:
    """현재 턴인 플레이어 객체 반환 (게임 종료 시 None)"""
    if not gs.players:
        return None
    return gs.players[gs.current_turn]

def start_game_flow(room_id: str):
    """(백그라운드) 게임 시작 로직"""
    gs = get_room(room_id)
    if not gs: return

    print(f"🚀 게임 시작 (방장 호출): {room_id}")
    prepare_tiles(gs)
    deal_initial_hands(gs)
    gs.current_turn = -1 # (start_next_turn에서 0으로 보정됨)
    gs.game_started = True
    
    # (중요) 프론트의 LobbyView -> GameView로 이동 신호
    socketio.emit("game_started", {"roomId": room_id}, room=room_id)
    socketio.sleep(1) # 프론트가 씬을 로드할 시간
    
    start_next_turn(room_id)


def start_next_turn(room_id: str):
    """다음 플레이어의 턴을 시작합니다."""
    gs = get_room(room_id)
    if not gs: return

    # 1. (TODO) 게임 종료 조건 체크
    #    (예: 활성 플레이어가 1명만 남았는지)
    
    # 2. 다음 턴으로 설정
    gs.current_turn = (gs.current_turn + 1) % len(gs.players)
    player = get_current_player(gs)
    if not player:
        print(f"[{room_id}] 게임 종료: 플레이어 없음")
        return

    print(f"--- 턴 시작 ({player.name}) ---")
    
    # 3. 턴 페이즈 결정: 더미가 비었는지 확인
    piles_empty = not gs.piles["black"] and not gs.piles["white"]
    
    if piles_empty:
        # 더미가 없으면 바로 '추리'
        set_turn_phase(room_id, "GUESSING")
    else:
        # 더미가 있으면 '드로우'
        set_turn_phase(room_id, "DRAWING")

def set_turn_phase(room_id: str, phase: TurnPhase):
    """
    지정된 페이즈로 상태를 변경하고, 타이머를 시작하며, 클라이언트에 알립니다.
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
    gs.drawn_tile = None # 페이즈 변경 시 초기화
    gs.pending_placement = False
    gs.can_place_anywhere = False
    
    print(f"[{room_id}] {player.name} 님의 페이즈 변경 -> {phase}")

    # 3. 클라이언트에 현재 턴 정보 전송 (UI 변경용)
    available_piles = []
    if gs.piles["black"]: available_piles.append("black")
    if gs.piles["white"]: available_piles.append("white")

    emit_data = {
        "phase": phase,
        "timer": TURN_TIMER_SECONDS,
        "available_piles": available_piles # (DRAWING 페이즈용)
    }
    socketio.emit("game:turn_phase_start", emit_data, to=player.sid)
    
    # 4. 전체 상태 브로드캐스트 (누구 턴인지 등)
    broadcast_in_game_state(room_id)

    # 5. 새 타이머 시작
    gs.turn_timer = Timer(
        TURN_TIMER_SECONDS,
        lambda: handle_timeout(room_id, player.uid, phase)
    )
    gs.turn_timer.start()

def handle_timeout(room_id: str, player_uid: str, expected_phase: TurnPhase):
    """20초 타임아웃 처리"""
    gs = rooms.get(room_id)
    player = get_current_player(gs)

    # (방어 코드) 타이머가 실행되는 시점에 이미 턴이 넘어갔거나 상태가 다르면 무시
    if not gs or not player or player.uid != player_uid or gs.turn_phase != expected_phase:
        print(f"타임아웃 무시: (uid: {player_uid}, phase: {expected_phase})")
        return

    print(f"⏰ 타임아웃 발생! {player.name} / {expected_phase}")
    
    if expected_phase == "DRAWING":
        # 1. 강제 드로우 (남아있는 색상 중 랜덤)
        color: Color = "black"
        if gs.piles["black"] and gs.piles["white"]:
            color = "black" if random.random() < 0.5 else "white"
        elif gs.piles["white"]:
            color = "white"
        
        t = start_turn_from(gs, player, color)
        if t and not t.is_joker:
            auto_place_drawn_tile(gs, player)
            set_turn_phase(room_id, "GUESSING")
        elif t and t.is_joker:
            # 조커는 강제로 맨 뒤에 배치
            player.hand.append(t)
            gs.drawn_tile = None
            gs.pending_placement = False
            set_turn_phase(room_id, "GUESSING")
        else:
            # (이론상) 타일이 없으면 바로 추리
            set_turn_phase(room_id, "GUESSING")
            
    elif expected_phase == "PLACE_JOKER":
        # 2. 조커 강제 배치 (맨 뒤)
        t = gs.drawn_tile
        if t:
            player.hand.append(t)
        set_turn_phase(room_id, "GUESSING")

    elif expected_phase == "GUESSING" or expected_phase == "POST_SUCCESS_GUESS":
        # 3. 추리/연속추리 타임아웃 -> 턴 강제 종료 (벌칙 X)
        socketio.emit("game:action_timeout", 
                      {"message": "시간 초과! 턴이 종료됩니다."}, 
                      to=player.sid)
        start_next_turn(room_id)


# --- 클라이언트 이벤트 핸들러 (수정됨) ---

@socketio.on("start_game")
def on_start_game(data):
    """(수정) '게임 시작' 버튼 (타이머 로직으로 연결)"""
    room_id = data.get("roomId")
    if not room_id: return
        
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    if not player: return
        
    if player.id != 0:
        emit("error_message", {"message": "방장만 게임을 시작할 수 있습니다."})
        return
    if len(gs.players) < 2:
        emit("error_message", {"message": "최소 2명 이상이어야 시작할 수 있습니다."})
        return
    
    # (중요) 즉시 실행하지 않고 백그라운드 태스크로 시작
    socketio.start_background_task(start_game_flow, room_id)

@socketio.on("draw_tile")
def on_draw_tile(data):
    """(수정) 플레이어가 타일 색상을 선택 (타이머 중지)"""
    room_id = data.get("roomId")
    color: Color = data.get("color", "black")
    if not room_id: return
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    
    # 턴/페이즈 검증
    if not player or gs.players[gs.current_turn].sid != player.sid:
        return emit("error_message", {"message": "당신 턴이 아닙니다."})
    if gs.turn_phase != "DRAWING":
        return emit("error_message", {"message": "지금은 타일을 뽑을 수 없습니다."})
        
    # 1. 타이머 취소
    if gs.turn_timer: gs.turn_timer.cancel()

    # 2. 타일 뽑기
    t = start_turn_from(gs, player, color)
    if not t:
        return emit("error_message", {"message": "더 이상 뽑을 타일이 없습니다."})
        
    # 3. 다음 페이즈 결정
    if t.is_joker:
        # 조커 -> 배치 단계
        set_turn_phase(room_id, "PLACE_JOKER")
    else:
        # 일반 타일 -> 자동 배치 후 추리 단계
        auto_place_drawn_tile(gs, player)
        set_turn_phase(room_id, "GUESSING")

@socketio.on("place_joker")
def on_place_joker(data):
    """(수정) 조커 배치 (타이머 중지)"""
    room_id = data.get("roomId")
    index = data.get("index")
    if not room_id or index is None: return
        
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    
    # 턴/페이즈 검증
    if not player or gs.players[gs.current_turn].sid != player.sid: return
    if gs.turn_phase != "PLACE_JOKER" or not gs.drawn_tile:
        return emit("error_message", {"message": "지금은 조커를 놓을 수 없습니다."})

    # 1. 타이머 취소
    if gs.turn_timer: gs.turn_timer.cancel()
        
    # 2. (기존 로직) 조커 배치
    t = gs.drawn_tile
    i = max(0, min(index, len(player.hand)))
    player.hand.insert(i, t)
    player.last_drawn_index = i
    
    # 3. 다음 페이즈 (추리)
    set_turn_phase(room_id, "GUESSING")


@socketio.on("guess_value")
def on_guess_value(data):
    """(수정) 추리 (타이머 중지 및 결과에 따른 분기)"""
    room_id = data.get("roomId")
    if not room_id: return
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    
    # 턴/페이즈 검증
    if not player or gs.players[gs.current_turn].sid != player.sid:
        return emit("error_message", {"message": "당신 턴이 아닙니다."})
    if gs.turn_phase not in ["GUESSING", "POST_SUCCESS_GUESS"]:
        return emit("error_message", {"message": "지금은 추리할 수 없습니다."})

    # 1. 타이머 취소
    if gs.turn_timer: gs.turn_timer.cancel()

    target_id = data.get("targetId")
    index = data.get("index")
    value = data.get("value")

    # 2. 추리 실행
    result = guess_tile(gs, player, target_id, index, value)
    
    # 3. 결과 브로드캐스트 (맞았는지, 틀렸는지)
    # (프론트가 이 이벤트를 받고 카드 공개 처리를 해야 함)
    socketio.emit("game:guess_result", {
        "guesser_id": player.id,
        "target_id": target_id,
        "index": index,
        "value": value,
        "correct": result["correct"]
    }, room=room_id)

    # 4. 상태 브로드캐스트 (공개된 카드 반영)
    broadcast_in_game_state(room_id)

    if result["correct"]:
        # 3-1. (성공) -> 연속 추리 단계
        set_turn_phase(room_id, "POST_SUCCESS_GUESS")
        # 프론트에 "계속 하시겠습니까?" 프롬프트 표시 요청
        socketio.emit("game:prompt_continue", 
                      {"timer": TURN_TIMER_SECONDS}, 
                      to=player.sid)
    else:
        # 3-2. (실패) -> 다음 턴
        start_next_turn(room_id)


@socketio.on("stop_guessing")
def on_stop_guessing(data):
    """(신규) 추리 성공 후 '턴 넘기기'를 선택"""
    room_id = data.get("roomId")
    if not room_id: return
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)

    # 턴/페이즈 검증
    if not player or gs.players[gs.current_turn].sid != player.sid: return
    if gs.turn_phase != "POST_SUCCESS_GUESS": return

    # 1. 타이머 취소
    if gs.turn_timer: gs.turn_timer.cancel()
    
    print(f"{player.name} 님이 추리를 중단하고 턴을 넘깁니다.")
    
    # 2. 다음 턴
    start_next_turn(room_id)