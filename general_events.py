# general_events.py
from flask import request
from extensions import socketio
from state import rooms, queue
from utils import find_player_by_sid, broadcast_in_game_state, serialize_state_for_lobby

# 🔥 Firebase Admin SDK 임포트 (game_events.py와 동일하게 추가)
try:
    from firebase_admin_config import get_db
    from firebase_admin import firestore as admin_firestore
    FIREBASE_AVAILABLE = True
except Exception as e:
    FIREBASE_AVAILABLE = False
    print(f"⚠️ Firebase Admin not available in general_events: {e}")


@socketio.on("connect")
def on_connect():
    print("🟢 connect:", request.sid)

@socketio.on("disconnect")
def on_disconnect(reason=None):  # 🔥 [FIXED] Flask-SocketIO passes reason parameter
    print("🔴 disconnect:", request.sid, f"({reason})" if reason else "")
    
    global queue
    original_len = len(queue)
    queue = [p for p in queue if p["sid"] != request.sid]


    queue = [p for p in queue if p["sid"] != sid]
    
    if len(queue) < original_len:
        print(f"👋 연결 끊김: 대기열에서 {sid} 제거됨.")
        broadcast_queue_status()

    for room_id, gs in list(rooms.items()):
        player = find_player_by_sid(gs, request.sid)
        if player:
            gs.players.remove(player) # 일단 목록에서 제거
            print(f"👤 {player.name} left room {room_id}")
            
            # ▼▼▼▼▼ (핵심 수정) ▼▼▼▼▼
            # [요청사항] 연결 끊김(새로고침/창닫기) 시 즉시 탈락 및 정산 처리
            
            # 1. 게임 중이라면 패배 처리 및 정산
            game_started = bool(gs.piles["black"] or gs.piles["white"])
            if game_started:
                print(f"👋 게임 중 이탈: {player.name} -> 즉시 탈락 및 정산")
                
                # (1) 모든 카드 공개
                for tile in player.hand:
                    tile.revealed = True
                
                # (2) 탈락 처리 및 순위 산정
                if player.final_rank == 0:
                    from game_logic import get_alive_players
                    alive_players = get_alive_players(gs)
                    # 나 자신은 아직 리스트에 있으므로 포함됨. 
                    # 하지만 '생존자 수' 기준으로 순위를 매겨야 함.
                    # 내가 나가면 생존자는 (현재 생존자 - 1)명이 됨.
                    # 내 순위는 (현재 생존자 수)가 됨.
                    # 예: 4명 생존 -> 내가 나감 -> 3명 남음 -> 나는 4등
                    player.final_rank = len(alive_players) 
                    
                    socketio.emit("game:player_eliminated", {
                        "uid": player.uid,
                        "nickname": player.nickname,
                        "rank": player.final_rank
                    }, room=room_id)

                    # (3) 즉시 패배 정산 (돈 차감)
                    if not player.settled:
                        net_change = -player.bet_amount
                        player.money += net_change
                        player.settled = True
                        
                        # Firestore 업데이트 (이탈 패널티)
                        if FIREBASE_AVAILABLE:
                            try:
                                from firebase_admin_config import get_db
                                from firebase_admin import firestore as admin_firestore
                                db = get_db()
                                if db:
                                    user_ref = db.collection('users').document(player.uid)
                                    user_ref.update({
                                        'money': admin_firestore.Increment(net_change)
                                    })
                                    print(f"💰 Firestore updated (disconnect): {player.nickname} {net_change:+d}")
                            except Exception as e:
                                print(f"❌ Firestore error: {e}")
                        
                        # 정산 결과 전송
                        socketio.emit("game:payout_result", [{
                            "uid": player.uid,
                            "nickname": player.nickname,
                            "rank": player.final_rank,
                            "bet": player.bet_amount,
                            "net_change": net_change,
                            "new_total": player.money
                        }], room=room_id)

                # (4) 턴 넘기기 (내 턴이었다면)
                if gs.players and gs.current_turn < len(gs.players):
                    if gs.players[gs.current_turn].sid == player.sid:
                        print(f"[{room_id}] 턴 플레이어 이탈 -> 턴 넘김")
                        if gs.turn_timer: gs.turn_timer.cancel()
                        from game_events import start_next_turn
                        socketio.start_background_task(start_next_turn, room_id)
                    else:
                        broadcast_in_game_state(room_id)

                # (5) 게임 종료 조건 확인
                from game_logic import get_alive_players
                # 여기서 player는 아직 gs.players에 있음. 하지만 eliminated 상태이거나 곧 제거됨.
                # get_alive_players는 final_rank==0인 사람만 셈.
                # 방금 final_rank를 설정했으므로 나는 제외됨.
                alive_players = get_alive_players(gs)
                
                if len(alive_players) <= 1:
                    print(f"🏆 게임 종료! (이탈로 인한 종료)")
                    if len(alive_players) == 1:
                        survivor = alive_players[0]
                        survivor.final_rank = 1
                    
                    from game_events import handle_winnings
                    handle_winnings(room_id)
                    
                    winner = next((p for p in gs.players if p.final_rank == 1), None)
                    socketio.emit("game_over", {
                        "winner": {"name": winner.nickname if winner else "Unknown"}
                    }, room=room_id)

            # 2. 플레이어 제거
            gs.players.remove(player)
            print(f"🗑️ {player.name} removed from room {room_id}")

            # 3. 방이 비었거나 로비 상태라면 정리
            if not game_started:
                if gs.players:
                    # [로비] ID 재정렬
                    for i, p in enumerate(gs.players):
                        p.id = i
                    socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)
                else:
                    print(f"🗑️ Room {room_id} is empty, deleting.")
                    if room_id in rooms:
                        del rooms[room_id]
            else:
                # 게임 중이었는데 다 나갔으면 삭제
                if not gs.players:
                    print(f"🗑️ Room {room_id} is empty (game ended), deleting.")
                    if room_id in rooms:
                        del rooms[room_id]
            
            break
            # ▲▲▲▲▲ (핵심 수정) ▲▲▲▲▲