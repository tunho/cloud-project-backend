# general_events.py
from flask import request
from extensions import socketio
from state import rooms, queue
from utils import find_player_by_sid, broadcast_in_game_state, serialize_state_for_lobby, update_user_money_async

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
            try:
                # ▼▼▼▼▼ (핵심 수정) ▼▼▼▼▼
                # [요청사항] 연결 끊김(새로고침/창닫기) 시 즉시 탈락 및 정산 처리
                
                # 1. 게임 중이라면 패배 처리 및 정산
                # 1. 게임 중이라면 패배 처리 및 정산
                # 🔥 [FIX] Handle Room object
                game_state = gs.game_state if hasattr(gs, 'game_state') else gs
                
                has_cards = len(player.hand) > 0
                print(f"🔍 [Disconnect Debug] uid={player.uid}, has_cards={has_cards}, hand_len={len(player.hand)}")
                
                # Check game_started based on game type
                game_started = False
                if getattr(gs, 'game_type', 'davinci') == 'omok':
                     if game_state and getattr(game_state, 'phase', 'INIT') != 'INIT':
                         game_started = True
                     # 🔥 [FIX] Call Omok Handler
                     from handlers.omok_handler import OmokHandler
                     OmokHandler().on_disconnect(room_id, request.sid)
                     return # 🔥 [FIX] Exit early, let handler handle it
                     
                elif getattr(gs, 'game_type', 'davinci') == 'indian_poker':
                     # 🔥 [FIX] Call Indian Poker Handler
                     from handlers.indian_poker_handler import IndianPokerHandler
                     IndianPokerHandler().on_disconnect(room_id, request.sid)
                     return # 🔥 [FIX] Exit early, let handler handle it
                     
                else:
                    # Davinci
                    if game_state: # 🔥 [FIX] Check if game_state exists
                        if hasattr(game_state, 'game_started') and game_state.game_started:
                             game_started = True
                        elif hasattr(game_state, 'turn_phase'):
                            game_started = (game_state.turn_phase != "INIT") or has_cards
                
                if game_started:
                    print(f"⚠️ {player.nickname} 님이 이탈하여 패배 처리되고 배팅 금액을 모두 잃습니다.")
                    
                    # (1) 모든 카드 공개
                    for tile in player.hand:
                        tile.revealed = True
                    print(f"🃏 [Disconnect] Revealed hand for {player.nickname}") # Debug
                    
                    # (2) 탈락 처리 및 순위 산정
                    if player.final_rank == 0:
                        if getattr(gs, 'game_type', 'davinci') == 'omok':
                             # Omok: Alive if final_rank is 0
                             alive_players = [p for p in gs.players if p.final_rank == 0]
                             # If 2 players, alive=2. Leaver gets rank 2.
                             player.final_rank = len(alive_players)
                        else:
                            from game_logic import get_alive_players
                            alive_players = get_alive_players(gs)
                            # 남은 생존자 수 + 1 = 내 순위 (예: 2명 남았을 때 죽으면 3등)
                            # 하지만 이미 alive_players에는 내가 포함되어 있을 수 있음 (아직 remove 안했으므로)
                            # get_alive_players는 final_rank==0인 사람만 반환함.
                            # 내가 아직 final_rank가 0이면 alive_players에 포함됨.
                            
                            player.final_rank = len(alive_players) + 1 # 🔥 [FIX] +1 
                        
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
                            
                            # 정산 결과 저장 및 전송 (UI 먼저!)
                            payout_data = {
                                "uid": player.uid,
                                "nickname": player.nickname,
                                "rank": player.final_rank,
                                "bet": player.bet_amount,
                                "net_change": net_change,
                                "new_total": player.money
                            }
                            if game_state and hasattr(game_state, 'payout_results'):
                                game_state.payout_results.append(payout_data) # 🔥 [FIX] 정산 결과 저장 (재접속 시 전송용)
                            
                            socketio.emit("game:payout_result", [payout_data], room=room_id)

                            # (3.5) 상태 브로드캐스트 (카드 공개 및 탈락 반영)
                            broadcast_in_game_state(room_id)

                            # Firestore 업데이트 (이탈 패널티 - 비동기)
                            if FIREBASE_AVAILABLE:
                                update_user_money_async(player.uid, net_change, player.nickname)
    
                    # (4) 턴 넘기기 (내 턴이었다면)
                    is_omok = getattr(gs, 'game_type', 'davinci') == 'omok'
                    should_pass_turn = False
                    
                    if is_omok:
                        omok_logic = gs.game_state
                        if omok_logic and omok_logic.players:
                             # OmokLogic players might be different objects if re-instantiated, but usually same list ref
                             # Use index to be safe
                             if omok_logic.current_turn_index < len(omok_logic.players):
                                 current_player = omok_logic.players[omok_logic.current_turn_index]
                                 if current_player.sid == player.sid:
                                     should_pass_turn = True
                    else:
                        if game_state and hasattr(game_state, 'current_turn') and game_state.players:
                            if game_state.current_turn < len(game_state.players):
                                if game_state.players[game_state.current_turn].sid == player.sid:
                                    should_pass_turn = True

                    if should_pass_turn:
                        print(f"[{room_id}] 턴 플레이어 이탈 -> 턴 넘김 (Direct Call)")
                        if game_state and hasattr(game_state, 'turn_timer') and game_state.turn_timer:
                             game_state.turn_timer.cancel()
                        
                        if is_omok:
                            # Switch turn index (0->1, 1->0)
                            omok_logic.current_turn_index = 1 - omok_logic.current_turn_index
                            from game_events import start_omok_turn
                            try:
                                start_omok_turn(room_id)
                            except Exception as e:
                                print(f"❌ start_omok_turn failed: {e}")
                        else:
                            from game_events import start_next_turn
                            try:
                                start_next_turn(room_id)
                            except Exception as e:
                                print(f"❌ start_next_turn failed: {e}")
    
                    # (5) 게임 종료 조건 확인
                    # Recalculate alive players (since one might have been eliminated above)
                    if is_omok:
                         alive_players = [p for p in gs.players if p.final_rank == 0]
                    else:
                        from game_logic import get_alive_players
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
                        
                        if is_omok:
                            gs.game_state.phase = 'GAME_OVER'
                            gs.game_state.winner = winner
                            # Broadcast state so OmokView sees phase change
                            broadcast_in_game_state(room_id)
    
                # 2. 플레이어 제거 (게임 중이 아닐 때만!)
                phase = getattr(game_state, 'turn_phase', 'Unknown') if game_state else 'Unknown'
                print(f"🔍 [Disconnect] game_started={game_started}, phase={phase}") # Debug
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
            except Exception as e:
                print(f"❌ Error in on_disconnect for {player.nickname}: {e}")
                import traceback
                traceback.print_exc()