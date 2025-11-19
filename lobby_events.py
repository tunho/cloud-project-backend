# lobby_events.py
import uuid
from flask import request
from flask_socketio import emit, join_room, leave_room
from extensions import socketio
from state import rooms, queue
# ▼▼▼ (수정) find_player_by_uid 임포트 ▼▼▼
from utils import (
    get_room, find_player_by_sid, find_player_by_uid, 
    broadcast_in_game_state, serialize_state_for_lobby
)
from models import Player, GameState, Optional
from game_events import start_game_flow

def broadcast_queue_status():
    """현재 대기열에 있는 모든 플레이어에게 최신 큐 상태를 전송"""
    global queue
    count = len(queue)
    print(f"Broadcasting queue status: {count} players")
    
    for p in queue:
        emit("queue_status", 
             {"status": "waiting", "count": count, "max": 4}, 
             to=p["sid"])

@socketio.on("join_queue")
def on_join_queue(data):
    global queue
    sid = request.sid
    bet_amount = data.get("betAmount", 0) # 기본값 100으로 가정
    
    # ▼▼▼ [추가된 필드 추출] ▼▼▼
    uid = data.get("uid")
    name = data.get("name") or f"Player_{sid[:4]}"
    
    nickname = data.get("nickname", name) 
    email = data.get("email", "N/A")
    major = data.get("major", "N/A")
    money = data.get("money", 0)  # 👈 money 추출
    year = data.get("year", 0)
    if not uid:
        emit("error_message", {"message": "UID가 필요합니다."})
        return


    if any(p["uid"] == uid for p in queue): # sid가 아닌 uid로 중복 체크
        print(f"이미 대기열에 있음: {name}")
        return
    
    print(f"-> 큐 참가: {name} ({sid})")
    queue.append({
        # ... (기존 필드) ...
        "major": major,
        "money": money,
        "year": year,
        "bet_amount": bet_amount # 👈 큐에 저장
    })
    
    broadcast_queue_status()
    check_queue_match()

@socketio.on("leave_queue")
def on_leave_queue():
    """플레이어가 '대기 취소'를 눌렀을 때"""
    global queue
    sid = request.sid
    queue = [p for p in queue if p["sid"] != sid]
    print(f"<- 큐 이탈: {sid}")
    emit("queue_status", {"status": "idle"}, to=sid)
    broadcast_queue_status()

def check_queue_match():
    """대기열을 확인하여 4명이 모이면 게임을 시작시킴"""
    global queue
    
    if len(queue) >= 4:
        print("🎉 매칭 성공! 4명 대기 중.")
        
        players_to_match_data = [queue.pop(0) for _ in range(4)]
        
        room_id = str(uuid.uuid4())[:8]
        gs = get_room(room_id)
        
        players_to_match = []
        player_names = []
        
        for i, player_data in enumerate(players_to_match_data):
            player = Player(
                sid=player_data["sid"],
                uid=player_data["uid"], 
                id=i,
                name=player_data["name"],
                
                # ▼▼▼ [Player 객체에 money 반영] ▼▼▼
                nickname=player_data["nickname"],
                email=player_data["email"],
                major=player_data["major"],
                money=player_data["money"],  # 👈 money 반영
                year=player_data["year"],
                bet_amount=player_data["bet_amount"], # 👈 Player에게 할당
                # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
                
                hand=[],
                last_drawn_index=None
            )
            players_to_match.append(player)
            
        gs.players = players_to_match
        
        for player in players_to_match:
            join_room(room_id, sid=player.sid)
            match_data = {
                "roomId": room_id,
                "players": player_names 
            }
            emit("match:success", match_data, to=player.sid)

        print(f"🚪 방 생성 {room_id}. 플레이어: {', '.join(player_names)}")

        broadcast_queue_status()

        socketio.start_background_task(start_game_flow, room_id)


@socketio.on("create_room")
def on_create_room(data):
    """(수정) 플레이어가 '방 만들기'를 요청할 때"""
    sid = request.sid
    uid = data.get("uid")
    
    # ▼▼▼ [추가된 필드 추출] ▼▼▼
    name = data.get("name") or f"Player_{sid[:4]}"
    nickname = data.get("nickname", name)
    email = data.get("email", "N/A")
    major = data.get("major", "N/A")
    money = data.get("money", 0)  # 👈 money 추출
    year = data.get("year", 0)

    if not uid:
        emit("error_message", {"message": "UID가 필요합니다."})
        return

    room_id = str(uuid.uuid4())[:6]
    while room_id in rooms:
        room_id = str(uuid.uuid4())[:6]
        
    print(f"✨ 방 생성 요청: {name} -> new room {room_id}")

    gs = get_room(room_id)
    host_player = Player(
        sid=sid,
        uid=uid, 
        id=0, 
        name=name,
        nickname=nickname,
        email=email,
        major=major,
        money=money,  # 👈 money 반영
        year=year,
        hand=[],
        last_drawn_index=None,
        bet_amount=0,  # 👈 커스텀 방이므로 베팅 금액은 0
    )
    gs.players.append(host_player)
    
    join_room(room_id, sid=sid)
    emit("room_created", {"roomId": room_id}, to=sid)
    socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)


# ▼▼▼ (수정) 로컬 정의 삭제 (utils에서 임포트) ▼▼▼
# def find_player_by_uid(gs: GameState, uid: str) -> Optional[Player]:
#     ...


@socketio.on("enter_room")
def on_enter_room(data):
    """(수정) 플레이어가 방에 입장 (로직 정리)"""
    room_id = data.get("roomId")
    uid = data.get("uid")
    
    # ▼▼▼ [추가된 필드 추출] ▼▼▼
    name = data.get("name") or f"Player_{request.sid[:4]}"
    nickname = data.get("nickname", name)
    email = data.get("email", "N/A")
    major = data.get("major", "N/A")
    money = data.get("money", 0)  # 👈 money 추출
    year = data.get("year", 0)
    if not room_id or not uid or room_id not in rooms:
        emit("error_message", {"message": "존재하지 않는 방입니다."})
        return

    gs = get_room(room_id)
    existing_player = find_player_by_uid(gs, uid)
    
    game_started = bool(gs.piles["black"] or gs.piles["white"])

    # --------------------------
    # ① 재접속 처리
    # --------------------------
    if existing_player:
        print(f"🔄 Reconnected: {name} to room {room_id}")
        existing_player.sid = request.sid
        join_room(room_id, sid=request.sid)
        
        # (수정) 로직 정리: 상태 확인 후 1번만 전송
        if game_started:
            broadcast_in_game_state(room_id)
        else:
            socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)
        return

    # --------------------------
    # ② 신규 입장
    # --------------------------
    if len(gs.players) >= 4:
        emit("error_message", {"message": "방이 꽉 찼습니다."})
        return
    if game_started:
        emit("error_message", {"message": "이미 시작된 게임입니다."})
        return

    new_player = Player(
        sid=request.sid,
        uid=uid,
        id=len(gs.players),
        name=name,
        nickname=nickname,
        email=email,
        major=major,
        money=money,  # 👈 money 반영
        year=year,
        hand=[],
        last_drawn_index=None,
        bet_amount=0,  # 👈 커스텀 방이므로 베팅 금액은 0
    )
    gs.players.append(new_player)
    join_room(room_id, sid=request.sid)

    print(f"👤 {name} joined room {room_id} (현재 {len(gs.players)}명)")
    
    # (핵심) 방에 있는 모든 사람에게 로비 상태 갱신
    socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)


@socketio.on("leave_room")
def on_leave_room(data):
    """(수정) 플레이어가 '방 나가기'를 눌렀을 때 (타이머 연동)"""
    room_id = data.get("roomId")
    uid = data.get("uid") 
    
    if not room_id or not uid or room_id not in rooms:
        return

    gs: GameState = rooms.get(room_id) # 👈 GameState 타입 힌트
    if not gs: return

    player_to_remove = find_player_by_uid(gs, uid)
    if not player_to_remove:
        return # 방에 없는 유저

    # [수정] 명시적인 game_started 플래그 사용
    game_started = gs.game_started
    player_was_on_turn = False
    
    # [중요] 플레이어가 방을 나가기 *전에* 현재 턴이었는지 확인
    if game_started and gs.players and len(gs.players) > 0:
        if gs.players[gs.current_turn].uid == player_to_remove.uid:
            player_was_on_turn = True
            
            # [중요] 현재 턴 플레이어가 나갔으므로, 타이머 즉시 중지
            if gs.turn_timer:
                gs.turn_timer.cancel()
                gs.turn_timer = None
                print(f"[{room_id}] 턴 타이머 중지 (플레이어 퇴장).")
            
    # --- 플레이어 제거 ---
    leave_room(room_id, sid=player_to_remove.sid)
    gs.players.remove(player_to_remove)
    print(f"<- 방 이탈: {player_to_remove.name} left room {room_id}")
    # ---------------------

    # --- 후속 처리 ---
    if game_started:
        if len(gs.players) == 1:
            # [승리 처리] 1명 남음
            winner = gs.players[0]
            print(f"🏆 게임 종료! 승자: {winner.name}")
            socketio.emit("game_over", {"winner": {"id": winner.id, "name": winner.name}}, room=room_id)
            
            # [요청 사항] 방을 삭제하지 않고 게임 종료 상태로 둡니다.
            gs.game_started = False
            gs.turn_phase = "INIT"

        elif len(gs.players) > 1:
            # [게임 속행] 2명 이상 남음
            # 턴 인덱스 보정 (나간 플레이어보다 뒷 순서였을 경우)
            gs.current_turn %= len(gs.players)
            
            if player_was_on_turn:
                # 턴 진행 중인 플레이어가 나갔으므로, 즉시 다음 턴 시작
                print(f"[{room_id}] 턴 플레이어가 나갔으므로 다음 턴 시작.")
                # (중요) 바로 다음 턴 함수 호출 (백그라운드)
                socketio.start_background_task(start_next_turn, room_id)
            else:
                # 턴 진행 중이 아닌 플레이어가 나갔으므로, 상태만 갱신
                broadcast_in_game_state(room_id)
        
        else:
            # [방 삭제] 0명 남음 (게임 중)
            print(f"[{room_id}] (게임 중) 모든 플레이어가 나가서 방 삭제")
            if room_id in rooms: 
                del rooms[room_id]

    else: 
        # (게임 시작 전 로비)
        if gs.players:
            # [로비: 방장 위임] 1명 이상 남음
            for i, p in enumerate(gs.players):
                p.id = i
            socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)
        
        else:
            # [방 삭제] 0명 남음 (로비)
            print(f"[{room_id}] (로비) 모든 플레이어가 나가서 방 삭제")
            if room_id in rooms: 
                del rooms[room_id]