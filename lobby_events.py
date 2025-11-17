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
    """(수정) 플레이어가 '게임 찾기'를 눌렀을 때 (uid 안전 처리)"""
    global queue
    sid = request.sid
    name = data.get("name") or f"Player_{sid[:4]}"
    uid = data.get("uid")
    if not uid:
        emit("error_message", {"message": "UID가 필요합니다."})
        return


    if any(p["uid"] == uid for p in queue): # sid가 아닌 uid로 중복 체크
        print(f"이미 대기열에 있음: {name}")
        return
    
    print(f"-> 큐 참가: {name} ({sid})")
    queue.append({"sid": sid, "name": name, "uid": uid})
    
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
                uid=player_data["uid"], # uid 포함
                id=i,
                name=player_data["name"],
                hand=[],
                last_drawn_index=None
            )
            players_to_match.append(player)
            player_names.append(player.name)
            
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
    name = data.get("name") or f"Player_{sid[:4]}"
    uid = data.get("uid")

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
        hand=[],
        last_drawn_index=None
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
    name = data.get("name") or f"Player_{request.sid[:4]}"

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
        hand=[],
        last_drawn_index=None
    )
    gs.players.append(new_player)
    join_room(room_id, sid=request.sid)

    print(f"👤 {name} joined room {room_id} (현재 {len(gs.players)}명)")
    
    # (핵심) 방에 있는 모든 사람에게 로비 상태 갱신
    socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)


@socketio.on("leave_room")
def on_leave_room(data):
    """(수정) 플레이어가 '방 나가기'를 눌렀을 때 (버그 수정)"""
    room_id = data.get("roomId")
    uid = data.get("uid") 
    
    if not room_id or not uid or room_id not in rooms:
        return

    gs = rooms.get(room_id)
    player = find_player_by_uid(gs, uid)
    
    if not player:
        return # 방에 없는 유저
            
    game_started = bool(gs.piles["black"] or gs.piles["white"])
    
    # (수정) sid가 아니라 player.sid를 사용
    leave_room(room_id, sid=player.sid)
    gs.players.remove(player)
    print(f"<- 방 이탈: {player.name} left room {room_id}")

    # (수정) 'pass' 대신 실제 로직 채움
    if game_started:
        if gs.players:
            if len(gs.players) == 1:
                # [승리 처리]
                winner = gs.players[0]
                print(f"🏆 게임 종료! 승자: {winner.name}")
                socketio.emit("game_over", {"winner": {"id": winner.id, "name": winner.name}}, room=room_id)
                del rooms[room_id]
            else:
                # [턴 보정]
                gs.current_turn %= len(gs.players)
                broadcast_in_game_state(room_id) # (수정) room_id 전달
        else:
            if room_id in rooms: del rooms[room_id]
    else: 
        if gs.players:
            # [로비: 방장 위임]
            for i, p in enumerate(gs.players):
                p.id = i
            socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)
        else:
            if room_id in rooms: del rooms[room_id]