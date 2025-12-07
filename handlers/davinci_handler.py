from flask_socketio import emit
from extensions import socketio
from handlers.base_handler import GameHandler
from utils import get_room, find_player_by_sid, find_player_by_uid, broadcast_in_game_state
from game_logic import start_turn_from, auto_place_drawn_tile, guess_tile, is_player_eliminated
import time

class DavinciHandler(GameHandler):
    def start_turn(self, room_id: str, gs):
        # Import locally to avoid circular import
        from game_events import start_next_turn
        start_next_turn(room_id)

    def handle_action(self, room_id: str, action: str, data: dict, sid: str):
        if action == "draw_tile":
            self._draw_tile(room_id, data, sid)
        elif action == "place_joker":
            self._place_joker(room_id, data, sid)
        elif action == "guess_value":
            self._guess_value(room_id, data, sid)
        elif action == "stop_guessing":
            self._stop_guessing(room_id, data, sid)
        elif action == "animation_done":
            self._animation_done(room_id, data, sid)

    def _draw_tile(self, room_id: str, data: dict, sid: str):
        color = data.get("color")
        room = get_room(room_id)
        if not room: return
        gs = room.game_state
        if not gs: return
        
        player = find_player_by_sid(gs, sid)
        if not player: return
        
        if gs.turn_phase != "DRAWING": return
        if gs.players[gs.current_turn].sid != player.sid: return
        
        tile = start_turn_from(gs, player, color)
        if not tile: return
        
        from game_events import set_turn_phase
        if tile.is_joker:
            set_turn_phase(room_id, "PLACE_JOKER")
        else:
            auto_place_drawn_tile(gs, player)
            set_turn_phase(room_id, "GUESSING")

    def _place_joker(self, room_id: str, data: dict, sid: str):
        index = data.get("index")
        room = get_room(room_id)
        if not room: return
        gs = room.game_state
        if not gs: return

        player = find_player_by_sid(gs, sid)
        if not player: return
        
        if gs.turn_phase != "PLACE_JOKER": return
        if gs.players[gs.current_turn].sid != player.sid: return
        
        if gs.drawn_tile and gs.drawn_tile.is_joker:
            player.hand.insert(index, gs.drawn_tile)
            player.last_drawn_index = index
            gs.drawn_tile = None
            gs.pending_placement = False
            gs.can_place_anywhere = False
            
            from game_events import set_turn_phase
            set_turn_phase(room_id, "GUESSING")

    def _guess_value(self, room_id: str, data: dict, sid: str):
        target_id = data.get("targetId")
        index = data.get("index")
        value = data.get("value")
        
        room = get_room(room_id)
        if not room: return
        gs = room.game_state
        if not gs: return

        guesser = find_player_by_sid(gs, sid)
        if not guesser: return
        
        if gs.turn_phase not in ["GUESSING", "POST_SUCCESS_GUESS"]: return
        if gs.players[gs.current_turn].sid != guesser.sid: return
        
        result = guess_tile(gs, guesser, target_id, index, value)
        if not result.get("ok"): return
        
        from game_events import set_turn_phase
        set_turn_phase(room_id, "ANIMATING_GUESS", broadcast=False)
        
        socketio.emit("game:start_guess_animation", {
            "guesser_id": guesser.uid,
            "target_id": target_id,
            "index": index,
            "value": value,
            "correct": result.get("correct")
        }, room=room_id)

    def _stop_guessing(self, room_id: str, data: dict, sid: str):
        room = get_room(room_id)
        if not room: return
        gs = room.game_state
        if not gs: return
        
        player = find_player_by_sid(gs, sid)
        if not player: return
        
        if gs.players[gs.current_turn].sid != player.sid: return
        
        print(f"[{room_id}] {player.nickname} 턴 패스")
        
        from game_events import start_next_turn
        start_next_turn(room_id)

    def _animation_done(self, room_id: str, data: dict, sid: str):
        guesser_uid = data.get("guesserUid") 
        correct = data.get("correct") 
        
        if not room_id or not guesser_uid: return
        
        room = get_room(room_id)
        if not room: return
        gs = room.game_state
        if not gs: return
        player = find_player_by_uid(gs, guesser_uid)
        
        if not player or gs.players[gs.current_turn].uid != player.uid: return 
        if gs.turn_phase != "ANIMATING_GUESS": return
        
        gs.turn_phase = "PROCESSING"
        print(f"[{room_id}] {player.nickname} 애니메이션 완료. 결과: {correct}")

        unranked_players = [p for p in gs.players if p.final_rank == 0]
        unranked_count = len(unranked_players)
        
        for p in gs.players:
            if p.final_rank == 0 and is_player_eliminated(p):
                p.final_rank = unranked_count
                unranked_count -= 1
                for tile in p.hand:
                    tile.revealed = True
                
                socketio.emit("game:player_eliminated", {
                    "uid": p.uid,
                    "nickname": p.nickname,
                    "rank": p.final_rank
                }, room=room_id)
                
                broadcast_in_game_state(room_id)
                
                if not p.settled:
                    net_change = -p.bet_amount
                    p.money += net_change
                    p.settled = True
                    
                    payout_data = {
                        "uid": p.uid,
                        "nickname": p.nickname,
                        "rank": p.final_rank,
                        "bet": p.bet_amount,
                        "net_change": net_change,
                        "new_total": p.money
                    }
                    if gs.payout_results is None: gs.payout_results = []
                    gs.payout_results.append(payout_data)
                    socketio.emit("game:payout_result", [payout_data], room=room_id)
                    
                    from game_events import FIREBASE_AVAILABLE, update_user_money_async
                    if FIREBASE_AVAILABLE:
                        update_user_money_async(p.uid, net_change, p.nickname)
                
                broadcast_in_game_state(room_id)

        broadcast_in_game_state(room_id)
        socketio.sleep(0.3)

        if unranked_count <= 1:
            if unranked_count == 1:
                remaining_unranked = [p for p in gs.players if p.final_rank == 0]
                if remaining_unranked:
                    winner = remaining_unranked[0]
                    winner.final_rank = 1
            
            from game_events import handle_winnings
            handle_winnings(room_id)
            broadcast_in_game_state(room_id)
            socketio.sleep(0.5)
            
            winner = next((p for p in gs.players if p.final_rank == 1), None)
            socketio.emit("game_over", {
                "winner": {"name": winner.nickname if winner else "Unknown"}
            }, room=room_id)
            return

        broadcast_in_game_state(room_id)

        from game_events import start_next_turn, set_turn_phase, TURN_TIMER_SECONDS
        if correct:
            if is_player_eliminated(player):
                 start_next_turn(room_id)
            else:
                set_turn_phase(room_id, "POST_SUCCESS_GUESS")
                gs.turn_start_time = time.time()
                socketio.emit("game:prompt_continue", 
                              {"timer": 60}, 
                              to=player.sid)
        else:
            start_next_turn(room_id)
