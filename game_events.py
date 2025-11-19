# game_events.py
import random
from threading import Timer
from flask import request
from flask_socketio import emit
from extensions import socketio
from state import rooms
from models import GameState, Player, Color, TurnPhase, Optional # 👈 TurnPhase 임포트
from utils import (
    find_player_by_sid, get_room, 
    broadcast_in_game_state, serialize_state_for_lobby
)
from game_logic import (
    prepare_tiles, deal_initial_hands, start_turn_from, 
    auto_place_drawn_tile, guess_tile
)







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
    """(수정) 다음 턴을 시작 (드로우 또는 추리)"""
    gs = get_room(room_id)
    if not gs: return


    # ... (게임 종료 조건 체크) ...
    
    gs.current_turn = (gs.current_turn + 1) % len(gs.players)
    player = get_current_player(gs)
    if not player: return

    print(f"--- 턴 시작 ({player.name}) ---")
    
    # [수정] 턴 페이즈 결정
    piles_empty = not gs.piles["black"] and not gs.piles["white"]
    
    if piles_empty:
        # 더미가 없으면 바로 '추리'
        set_turn_phase(room_id, "GUESSING")
    else:
        # 👈 [복구] 더미가 있으면 '드로우' 단계
        set_turn_phase(room_id, "DRAWING")

def set_turn_phase(room_id: str, phase: TurnPhase):
    """
    (수정) 지정된 페이즈로 상태 변경 (DRAWING 로직 포함)
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

    # 3. 클라이언트에 현재 턴 정보 전송
    emit_data = {
            "phase": phase,
            "timer": TURN_TIMER_SECONDS,
            "currentTurnUid": player.uid # 👈 누가 턴인지 명시 (프론트에서 내 턴인지 구분용)
        }
    
    # 👈 [복구] DRAWING 단계일 때만 뽑을 수 있는 타일 정보 전송
    if phase == "DRAWING":
        available_piles = []
        if gs.piles["black"]: available_piles.append("black")
        if gs.piles["white"]: available_piles.append("white")
        emit_data["available_piles"] = available_piles

    socketio.emit("game:turn_phase_start", emit_data, room=room_id)
    
    # 4. 전체 상태 브로드캐스트
    broadcast_in_game_state(room_id)

    # 5. 새 타이머 시작
    gs.turn_timer = Timer(
        TURN_TIMER_SECONDS,
        lambda: handle_timeout(room_id, player.uid, phase)
    )
    gs.turn_timer.start()

def handle_timeout(room_id: str, player_uid: str, expected_phase: TurnPhase):
    """(수정) 20초 타임아웃 처리 (DRAWING 타임아웃 복구)"""
    gs = rooms.get(room_id)

    if not gs:
        print(f"타임아웃 무시: room {room_id}가 이미 삭제됨.")
        return

    player = get_current_player(gs)

    if not player or player.uid != player_uid or gs.turn_phase != expected_phase:
        print(f"타임아웃 무시: (uid: {player_uid}, phase: {expected_phase})")
        return

    print(f"⏰ 타임아웃 발생! {player.name} / {expected_phase}")
    
    # 👈 [복구] 드로우 타임아웃 로직
    if expected_phase == "DRAWING":
        # 1. 강제 드로우 (남아있는 색상 중 랜덤)
        color: Color = "black"
        available_piles = []
        if gs.piles["black"]: available_piles.append("black")
        if gs.piles["white"]: available_piles.append("white")
        
        if available_piles:
            color = random.choice(available_piles)
        
        t = start_turn_from(gs, player, color)
        if t and not t.is_joker:
            auto_place_drawn_tile(gs, player)
            set_turn_phase(room_id, "GUESSING")
        elif t and t.is_joker:
            # 조커는 강제로 맨 뒤에 배치 (타임아웃 시)
            player.hand.append(t)
            gs.drawn_tile = None
            gs.pending_placement = False
            set_turn_phase(room_id, "GUESSING")
        else:
            set_turn_phase(room_id, "GUESSING")
            
    elif expected_phase == "PLACE_JOKER":
        # 2. 조커 강제 배치 (맨 뒤)
        t = gs.drawn_tile
        if t:
            player.hand.append(t)
        set_turn_phase(room_id, "GUESSING")

    elif expected_phase == "GUESSING" or expected_phase == "POST_SUCCESS_GUESS":
        # 3. 추리/연속추리 타임아웃 -> 턴 강제 종료
        socketio.emit("game:action_timeout", 
                      {"message": "시간 초과! 턴이 종료됩니다."}, 
                      to=player.sid)
        start_next_turn(room_id)


# --- 클라이언트 이벤트 핸들러 ---

@socketio.on("start_game")
def on_start_game(data):
    """방장이 게임 시작 버튼을 눌렀을 때"""
    # 1. [수정] room_id 변수 정의 (여기서 에러가 났었습니다)
    room_id = data.get("roomId")
    
    if not room_id:
        return
        
    gs = get_room(room_id)
    # request를 사용하기 위해 상단에 from flask import request 확인 필요
    player = find_player_by_sid(gs, request.sid)

    if not player:
        return
        
    # 방장 권한 확인 (id가 0번인 플레이어)
    if player.id != 0:
        emit("error_message", {"message": "방장만 게임을 시작할 수 있습니다."})
        return
        
    # 최소 인원 확인
    if len(gs.players) < 2:
        emit("error_message", {"message": "최소 2명 이상이어야 시작할 수 있습니다."})
        return
    
    # 2. 백그라운드에서 게임 시작 흐름 실행
    # (이제 room_id가 정의되었으므로 에러가 나지 않습니다)
    socketio.start_background_task(start_game_flow, room_id)


# ▼▼▼ [핸들러 복구] ▼▼▼
@socketio.on("draw_tile")
def on_draw_tile(data):
    """(복구) 플레이어가 타일 색상을 선택"""
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

        
    # 3. 다음 페이즈 결정 (요청대로 즉시 다음 단계로)
    if t.is_joker:
        # 조커 -> 배치 단계
        set_turn_phase(room_id, "PLACE_JOKER")
        broadcast_in_game_state(room_id)
    else:
        # 일반 타일 -> 자동 배치 후 추리 단계
        auto_place_drawn_tile(gs, player)
        set_turn_phase(room_id, "GUESSING")
        broadcast_in_game_state(room_id)
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲


@socketio.on("place_joker")
def on_place_joker(data):
    """(복구) 플레이어가 조커 위치를 선택하여 배치"""
    room_id = data.get("roomId")
    index = data.get("index")
    
    # 1. 데이터 유효성 검사
    if not room_id or index is None: 
        return
        
    gs = get_room(room_id)
    # request.sid를 사용하므로 상단에 from flask import request 필요
    player = find_player_by_sid(gs, request.sid)
    
    # 2. 턴 및 페이즈 검증
    # 내 턴인지 확인 (현재 턴 플레이어의 sid와 요청자의 sid 비교)
    current_turn_player = gs.players[gs.current_turn % len(gs.players)]
    if not player or current_turn_player.sid != player.sid:
        emit("error_message", {"message": "당신 턴이 아닙니다."}, to=request.sid)
        return
        
    # 조커 배치 단계인지, 그리고 배치할 타일(drawn_tile)이 실제로 있는지 확인
    if gs.turn_phase != "PLACE_JOKER" or not gs.drawn_tile:
        emit("error_message", {"message": "지금은 조커를 놓을 수 없습니다."}, to=request.sid)
        return

    # 3. 타이머 중지 (행동을 완료했으므로)
    if gs.turn_timer: 
        gs.turn_timer.cancel()
        gs.turn_timer = None
        
    # 4. 조커 배치 로직 수행
    t = gs.drawn_tile
    
    # 인덱스 범위 안전 장치 (0 ~ 현재 패의 길이 사이로 제한)
    # 예: 패가 3장인데 index 100을 보내면 3(맨 뒤)으로 보정
    insert_idx = max(0, min(int(index), len(player.hand)))
    
    player.hand.insert(insert_idx, t)
    player.last_drawn_index = insert_idx # 방금 놓은 타일(조커) 위치 표시
    
    # 5. 임시 상태 초기화
    gs.drawn_tile = None
    gs.pending_placement = False
    gs.can_place_anywhere = False # 조커 배치 완료했으므로 플래그 해제
    
    print(f"[{room_id}] {player.name}님이 조커를 인덱스 {insert_idx}에 배치함.")
    
    # 6. 다음 단계(추리)로 이동
    set_turn_phase(room_id, "GUESSING")


@socketio.on("guess_value")
def on_guess_value(data):
    """(수정) 추리 (요청 사항 반영)"""
    room_id = data.get("roomId")
    if not room_id: return
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)
    
    if not player or gs.players[gs.current_turn].sid != player.sid:
        return emit("error_message", {"message": "당신 턴이 아닙니다."})
    if gs.turn_phase not in ["GUESSING", "POST_SUCCESS_GUESS"]:
        return emit("error_message", {"message": "지금은 추리할 수 없습니다."})

    if gs.turn_timer: gs.turn_timer.cancel()

    target_id = data.get("targetId")
    index = data.get("index")
    value = data.get("value")

    result = guess_tile(gs, player, target_id, index, value)
    
    # [수정] 결과 브로드캐스트 (카드 공개 처리용)
    socketio.emit("game:guess_result", {
        "guesser_id": player.id,
        "target_id": target_id,
        "index": index,
        "value": value,
        "correct": result["correct"]
    }, room=room_id)

    broadcast_in_game_state(room_id) # 갱신된 카드 상태 전송

    if result["correct"]:
        # 3-1. (성공) -> 연속 추리 단계
        set_turn_phase(room_id, "POST_SUCCESS_GUESS")
        # [요청 사항] 프론트에 "계속 하시겠습니까?" 프롬프트 표시 요청
        socketio.emit("game:prompt_continue", 
                      {"timer": TURN_TIMER_SECONDS}, 
                      to=player.sid)
    else:
        # 3-2. (실패) -> 다음 턴
        start_next_turn(room_id)


@socketio.on("stop_guessing")
def on_stop_guessing(data):
    """(복구) 추리 성공 후 '턴 넘기기'를 선택"""
    room_id = data.get("roomId")
    if not room_id: return
    
    gs = get_room(room_id)
    player = find_player_by_sid(gs, request.sid)

    if not player or gs.players[gs.current_turn].sid != player.sid: return
    if gs.turn_phase != "POST_SUCCESS_GUESS": return

    if gs.turn_timer: gs.turn_timer.cancel()
    
    print(f"{player.name} 님이 추리를 중단하고 턴을 넘깁니다.")
    
    start_next_turn(room_id)


def handle_winnings(room_id: str):
    """(수정) 게임 종료 후 랭킹과 개인 베팅 금액에 따라 화폐를 계산하고 정산"""
    gs = get_room(room_id)
    if not gs: return

    # 1. 승리 시 1등(마지막 생존자)에게 1등 순위를 부여
    winner = next((p for p in gs.players if p.final_rank == 0), None)
    if winner:
        winner.final_rank = 1 

    payout_results = []
    # 랭킹별 순위를 명확히 하기 위해 정렬 (만약 랭킹 부여 로직이 있다면)
    # 현재는 final_rank가 1~4로 부여되었다고 가정합니다.

    # 2. 계산
    for player in gs.players:
        bet = player.bet_amount
        net_change = 0
        rank = player.final_rank

        if rank == 1:
            net_change = +bet # 1등은 베팅 금액만큼 획득
        elif rank == 2:
            net_change = +bet # 2등은 베팅 금액만큼 획득 (요청 사항)
        elif rank == 3 or rank == 4:
            net_change = -bet # 3, 4등은 베팅 금액만큼 차감
        else:
            # 게임이 중간에 취소되거나 순위가 미정인 경우 (0)
            net_change = 0 
        
        # 3. Player.money 업데이트
        player.money += net_change

        # 4. 프론트엔드/DB 업데이트를 위한 결과 저장
        payout_results.append({
            "uid": player.uid,
            "nickname": player.nickname,
            "rank": rank,
            "bet": bet,
            "net_change": net_change,
            "new_total": player.money
        })

    # 5. 모든 클라이언트에게 정산 결과 브로드캐스트
    socketio.emit("game:payout_result", payout_results, room=room_id)
    
    print(f"[{room_id}] 게임 정산 완료. 순위별 정산 처리됨.")