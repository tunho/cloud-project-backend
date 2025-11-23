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
    bet_amount = int(data.get("betAmount", 10000)) # 🔥 [FIX] Ensure int
    
    # ▼▼▼ [추가된 필드 추출] ▼▼▼
    uid = data.get("uid")
    name = data.get("name") or f"Player_{sid[:4]}"
    
    # 🔥 [FIXED] nickname이 없거나 빈 문자열이면 name을 사용하지 않고 실제 사용자 정보에서 가져와야 함
    nickname = data.get("nickname") or name  # nickname이 없으면 name 사용
    email = data.get("email", "N/A")
    major = data.get("major", "N/A")
    try:
        money = int(data.get("money", 0))
    except:
        money = 0
    try:
        year = int(data.get("year", 0))
    except:
        year = 0
    if not uid:
        return


    # ▼▼▼ [수정] 이미 대기열에 있는 경우 SID 업데이트 ▼▼▼
    existing_player_index = next((i for i, p in enumerate(queue) if p["uid"] == uid), -1)
    if existing_player_index != -1:
        print(f"🔄 대기열 재접속: {nickname} (기존 SID: {queue[existing_player_index]['sid']} -> 신규 SID: {sid})")
        queue[existing_player_index]["sid"] = sid
        # 필요한 경우 다른 정보도 업데이트 (예: 돈, 닉네임 등 변경되었을 수 있음)
        queue[existing_player_index]["money"] = money
        queue[existing_player_index]["bet_amount"] = bet_amount
        
        broadcast_queue_status()
        return
    # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
    
    print(f"-> 큐 참가: {nickname} ({sid}) Bet: {bet_amount}")  # 🔥 name -> nickname
    queue.append({
        # ▼▼▼ [수정됨] sid와 uid를 명시적으로 저장 ▼▼▼
        "sid": sid,             # 👈 [필수] 이 키를 추가합니다.
        "uid": uid,             # 👈 [필수] 이 키도 추가합니다.
        # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲
        "name": name,
        "nickname": nickname,
        "email": email,
        "major": major,
        "money": money,
        "year": year,
        "bet_amount": bet_amount
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

# lobby_events.py

def check_queue_match():
    """대기열을 확인하여 4명이 모이면 게임을 시작시킴 (안전 버전)"""
    global queue
    
    if len(queue) >= 4:
        # 1. 일단 4명을 꺼냄
        players_to_match_data = [queue.pop(0) for _ in range(4)]
        
        room_id = str(uuid.uuid4())[:8]
        gs = get_room(room_id)
        
        players_to_match = []
        player_names = []
        valid_players_count = 0

        for i, player_data in enumerate(players_to_match_data):
            # Player 객체 생성
            player = Player(
                sid=player_data["sid"],
                uid=player_data["uid"], 
                id=i,
                name=player_data["name"],
                nickname=player_data["nickname"],
                email=player_data["email"],
                major=player_data["major"],
                money=player_data["money"],
                year=player_data["year"],
                bet_amount=player_data["bet_amount"],
                hand=[],
                last_drawn_index=None
            )
            
            # ▼▼▼ [중요] 강제 입장 시도 (예외 처리) ▼▼▼
            try:
                join_room(room_id, sid=player.sid)
                # 성공적으로 방에 들어간 경우에만 리스트에 추가
                players_to_match.append(player)
                player_names.append(player.nickname)
                valid_players_count += 1
                
                # 매칭 성공 메시지 전송
                match_data = {
                    "roomId": room_id,
                    "players": [] # 아직 다 안 찼으므로 나중에 보낼 수도 있음 (일단 비워둠 or 현재까지 이름)
                }
                # 여기서 보내지 말고 4명 다 성공하면 보내는 게 나음
                
            except KeyError:
                # 이미 연결이 끊긴 유령 플레이어
                print(f"⚠️ 매칭 실패: {player.name} ({player.sid}) 유저가 연결되지 않음.")
                # 이 유저는 버립니다.
            except Exception as e:
                print(f"⚠️ 입장 오류: {e}")

        # 2. 4명 모두 정상적으로 방에 들어갔는지 확인
        if valid_players_count == 4:
            print(f"🎉 매칭 확정! 방 ID: {room_id}")
            
            # GameState에 플레이어 등록
            gs.players = players_to_match
            
            # 각 플레이어에게 매칭 성공 신호 전송
            final_match_data = {
                "roomId": room_id,
                "players": player_names
            }
            socketio.emit("match:success", final_match_data, room=room_id)

            print(f"🚪 방 생성 {room_id}. 플레이어: {', '.join(player_names)}")
            broadcast_queue_status()

            # 게임 시작
            socketio.start_background_task(start_game_flow, room_id)
            
        else:
            # 🚨 4명이 안 모임 (누군가 튕김) -> 매칭 취소 및 롤백
            print("❌ 매칭 실패: 플레이어 중 일부가 연결이 끊겨 매칭이 취소되었습니다.")
            
            # 방금 만든 방 삭제
            if room_id in rooms:
                del rooms[room_id]
            
            # 정상적인 플레이어들은 다시 대기열의 '맨 앞'으로 돌려보냄 (우선순위 보장)
            # 거꾸로 넣어야 순서가 유지됨
            for p in reversed(players_to_match):
                # 원래 데이터 형태로 복구
                original_data = {
                    "sid": p.sid, "uid": p.uid, "name": p.name,
                    "nickname": p.nickname, "email": p.email, "major": p.major,
                    "money": p.money, "year": p.year, "bet_amount": p.bet_amount
                }
                queue.insert(0, original_data)
                
                # 방금 들어갔던 방에서 나오게 함
                leave_room(room_id, sid=p.sid)

            broadcast_queue_status()
            
            # (선택) 다시 매칭 시도할지 여부
            # check_queue_match() # 재귀 호출은 위험할 수 있으니 일단 대기


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
    """(수정) 플레이어가 방에 입장할 때"""
    print(f"📥 [DEBUG] enter_room received: {data}")
    
    room_id = data.get("roomId")
    uid = data.get("uid")
    
    # ▼▼▼ [추가된 필드 추출] ▼▼▼
    name = data.get("name") or f"Player_{request.sid[:4]}"
    nickname = data.get("nickname", name) or f"Player_{request.sid[:4]}"
    nickname = data.get("nickname", name)
    email = data.get("email", "N/A")
    major = data.get("major", "N/A")
    try:
        money = int(data.get("money", 0))
    except:
        money = 0
    try:
        year = int(data.get("year", 0))
    except:
        year = 0
    if not room_id or not uid or room_id not in rooms:
        return

    gs = get_room(room_id)
    existing_player = find_player_by_uid(gs, uid)
    
    game_started = bool(gs.piles["black"] or gs.piles["white"])

    # --------------------------
    # ① 재접속 처리
    # --------------------------
    if existing_player:
        # 🔥 [FIX] 같은 SID로 다시 들어오는 경우 (SPA 페이지 이동 등)는 패배 처리 하지 않음
        if existing_player.sid == request.sid:
             print(f"🔄 [SPA Navigation] {nickname} re-entered room {room_id} with same SID. Ignoring.")
             # 상태만 다시 전송
             if game_started:
                 broadcast_in_game_state(room_id)
             else:
                 socketio.emit("room_state", serialize_state_for_lobby(gs), room=room_id)
             return

        print(f"🔄 Reconnected: {nickname} to room {room_id} (GameStarted: {game_started})")
        
        # 🔥 [FIX] 사용자가 "새로고침 = 패배"를 원함.
        # 게임 중인데 final_rank가 0(생존)이라면, 이는 비정상 종료 후 재접속이므로 '패배' 처리.
        if game_started and existing_player.final_rank == 0:
            print(f"💀 {existing_player.nickname} 재접속 -> 즉시 패배 처리 (Refresh Rule)")
            
            # (1) 카드 공개
            for tile in existing_player.hand:
                tile.revealed = True
            
            # (2) 탈락 처리
            from game_logic import get_alive_players
            alive_players = get_alive_players(gs)
            existing_player.final_rank = len(alive_players)
            
            socketio.emit("game:player_eliminated", {
                "uid": existing_player.uid,
                "nickname": existing_player.nickname,
                "rank": existing_player.final_rank
            }, room=room_id)
            
            # (3) 정산
            if not existing_player.settled:
                net_change = -existing_player.bet_amount
                existing_player.money += net_change
                existing_player.settled = True
                
                # Firestore 업데이트
                try:
                    from firebase_admin_config import get_db
                    from firebase_admin import firestore as admin_firestore
                    db = get_db()
                    if db:
                        user_ref = db.collection('users').document(existing_player.uid)
                        user_ref.update({'money': admin_firestore.Increment(net_change)})
                        print(f"💰 Firestore updated (refresh-defeat): {existing_player.nickname} {net_change:+d}")
                except Exception as e:
                    print(f"❌ Firestore error: {e}")
                
                socketio.emit("game:payout_result", [{
                    "uid": existing_player.uid,
                    "nickname": existing_player.nickname,
                    "rank": existing_player.final_rank,
                    "bet": existing_player.bet_amount,
                    "net_change": net_change,
                    "new_total": existing_player.money
                }], room=room_id)
            
            # (4) 턴 넘기기 (내 턴이었다면)
            # 주의: SID 업데이트 전이므로 existing_player.sid는 구 SID임.
            if gs.players and gs.current_turn < len(gs.players):
                if gs.players[gs.current_turn].sid == existing_player.sid:
                    print(f"[{room_id}] 턴 플레이어 재접속(패배) -> 턴 넘김")
                    if gs.turn_timer: gs.turn_timer.cancel()
                    from game_events import start_next_turn
                    socketio.start_background_task(start_next_turn, room_id)
                else:
                    broadcast_in_game_state(room_id)
            
            # (5) 게임 종료 체크
            alive_players = get_alive_players(gs)
            if len(alive_players) <= 1:
                print(f"🏆 게임 종료! (재접속 패배로 인한 종료)")
                if len(alive_players) == 1:
                    alive_players[0].final_rank = 1
                
                from game_events import handle_winnings
                handle_winnings(room_id)
                
                winner = next((p for p in gs.players if p.final_rank == 1), None)
                socketio.emit("game_over", {
                    "winner": {"name": winner.nickname if winner else "Unknown"}
                }, room=room_id)

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
        return
    if game_started:
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
        bet_amount=data.get("betAmount", 0),  # 🔥 [FIX] 커스텀 게임은 기본값 0 (큐 매칭은 check_queue_match에서 설정됨)
    )
    gs.players.append(new_player)
    join_room(room_id, sid=request.sid)

    print(f"👤 {name} joined room {room_id} (현재 {len(gs.players)}명) Bet: {new_player.bet_amount}")
    
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


@socketio.on("start_game")
def on_start_game(data):
    """(수정) 커스텀 방 게임 시작"""
    room_id = data.get("roomId")
    if not room_id or room_id not in rooms:
        return

    gs = rooms[room_id]
    
    # 방장인지 확인 (id=0)
    player = find_player_by_sid(gs, request.sid)
    if not player or player.id != 0:
        return

    if len(gs.players) < 2:
        return

    print(f"🎮 게임 시작 요청: {player.name} (Room {room_id})")
    socketio.start_background_task(start_game_flow, room_id)