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


    if len(queue) < original_len:
        print(f"👋 연결 끊김: 대기열에서 {request.sid} 제거됨.")
        # 🔥 [FIX] lobby_events에서 가져오거나 직접 구현
        try:
            from lobby_events import broadcast_queue_status
            broadcast_queue_status()
        except ImportError:
            print("⚠️ broadcast_queue_status import failed")

    for room_id, gs in list(rooms.items()):
        player = find_player_by_sid(gs, request.sid)
        if player:
            
            # ▼▼▼▼▼ (핵심 수정) ▼▼▼▼▼
            # [요청사항] 연결 끊김(새로고침/창닫기) 시 즉시 탈락 및 정산 처리
            
            # 1. 게임 중이라면 패배 처리 및 정산
            # 🔥 [FIX] 더미가 비어있어도 게임 중일 수 있음. gs.game_started 플래그 또는 패를 가지고 있는지 확인
            has_cards = len(player.hand) > 0
            game_started = gs.game_started or (gs.turn_phase != "INIT") or has_cards

            if game_started:
                print(f"⚠️ {player.nickname} 님이 이탈하여 패배 처리되고 배팅 금액을 모두 잃습니다.")
                
                # (1) 모든 카드 공개
                for tile in player.hand:
                    tile.revealed = True
                print(f"🃏 [Disconnect] Revealed hand for {player.nickname}") # Debug
                
                # (2) 탈락 처리 및 순위 산정
                if player.final_rank == 0:
                    from game_logic import get_alive_players
                    alive_players = get_alive_players(gs)
                    # 남은 생존자 수 + 1 = 내 순위 (예: 2명 남았을 때 죽으면 3등)
                    # 하지만 이미 alive_players에는 내가 포함되어 있을 수 있음 (아직 remove 안했으므로)
                    # get_alive_players는 final_rank==0인 사람만 반환함.
                    # 내가 아직 final_rank가 0이면 alive_players에 포함됨.
                    
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
                                    print(f"💀 {player.nickname} 님이 새로고침/연결 끊김으로 패배 처리됨. ({net_change:+d})")
                            except Exception as e:
                                print(f"❌ Firestore error: {e}")
                        
                        # 정산 결과 저장 및 전송
                        payout_data = {
                            "uid": player.uid,
                            "nickname": player.nickname,
                            "rank": player.final_rank,
                            "bet": player.bet_amount,
                            "net_change": net_change,
                            "new_total": player.money
                        }
                        gs.payout_results.append(payout_data) # 🔥 [FIX] 정산 결과 저장 (재접속 시 전송용)
                        
                        socketio.emit("game:payout_result", [payout_data], room=room_id)

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
                alive_players = get_alive_players(gs)
                
                # 나를 제외한 생존자가 1명 이하면 게임 종료
                # (내가 이미 final_rank가 설정되었으므로 get_alive_players에는 포함되지 않음)
                
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

            # 2. 플레이어 제거 (게임 중이 아닐 때만!)
            print(f"🔍 [Disconnect] game_started={game_started}, phase={gs.turn_phase}") # Debug
            if not game_started:
                if player in gs.players:
                    gs.players.remove(player)
                    print(f"🗑️ {player.name} removed from room {room_id}")

                # 3. 방이 비었거나 로비 상태라면 정리
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
                print(f"🚫 게임 중이므로 {player.nickname}를 목록에서 제거하지 않음 (재접속/정산 보존)")
            
            break
            # ▲▲▲▲▲ (핵심 수정) ▲▲▲▲▲