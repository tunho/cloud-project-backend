# general_events.py
from flask import request
from extensions import socketio
from state import rooms, queue
from utils import find_player_by_sid, broadcast_in_game_state, serialize_state_for_lobby


@socketio.on("connect")
def on_connect():
    print("🟢 connect:", request.sid)

@socketio.on("disconnect")
def on_disconnect():
    print("🔴 disconnect:", request.sid)
    
    global queue
    queue = [p for p in queue if p["sid"] != request.sid]

    for room_id, gs in list(rooms.items()):
        player = find_player_by_sid(gs, request.sid)
        if player:
            gs.players.remove(player) # 일단 목록에서 제거
            print(f"👤 {player.name} left room {room_id}")
            
            # ▼▼▼▼▼ (핵심 수정) ▼▼▼▼▼
            game_started = bool(gs.piles["black"] or gs.piles["white"])

            if gs.players: # 방에 아직 사람이 남았다면
                
                # [게임 승리 판정]
                # 게임 중이었고, 1명만 남았다면
                if game_started and len(gs.players) == 1:
                    winner = gs.players[0]
                    print(f"🏆 게임 종료! 승자: {winner.name}")
                    
                    # (신규 이벤트) "game_over" 전송
                    socketio.emit("game_over", {
                        "winner": { "id": winner.id, "name": winner.name }
                    }, room=room_id)
                    
                    # 방 삭제
                    del rooms[room_id]

                # [일반 턴/로비 처리]
                # (승리자가 아니면) 기존 로직 수행
                elif game_started:
                    # [인게임] ID 유지, 턴 보정
                    print("게임 중 플레이어 이탈. ID 유지.")
                    gs.current_turn %= len(gs.players) 
                    broadcast_in_game_state(room_id) # "state_update" 전송
                else:
                    # [로비] ID 재정렬
                    print("로비에서 플레이어 이탈. ID 재정렬.")
                    for i, p in enumerate(gs.players):
                        p.id = i
                    socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)
                            
            else:
                # 방이 비었으면 제거
                print(f"🗑️ Room {room_id} is empty, deleting.")
                if room_id in rooms:
                    del rooms[room_id]
            break
            # ▲▲▲▲▲ (핵심 수정) ▲▲▲▲▲