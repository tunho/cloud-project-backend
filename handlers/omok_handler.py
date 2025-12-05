from threading import Timer
from flask_socketio import emit
from extensions import socketio
from handlers.base_handler import GameHandler
from utils import get_room, find_player_by_sid

class OmokHandler(GameHandler):
    def start_turn(self, room_id: str, gs):
        omok_logic = gs.game_state
        current_player = omok_logic.players[omok_logic.current_turn_index]
        
        print(f"--- [Omok] {current_player.nickname} 님의 턴 시작 ---")
        
        socketio.emit("omok:turn_start", {
            "currentTurnUid": current_player.uid,
            "timer": 30
        }, room=room_id)

        if omok_logic.turn_timer:
            omok_logic.turn_timer.cancel()
        
        # Import handle_timeout locally to avoid circular import
        from game_events import handle_timeout
        omok_logic.turn_timer = Timer(30, handle_timeout, [room_id, current_player.uid, omok_logic.phase])
        omok_logic.turn_timer.start()

    def handle_action(self, room_id: str, action: str, data: dict, sid: str):
        if action == "place_stone":
            self._place_stone(room_id, data, sid)

    def _place_stone(self, room_id: str, data: dict, sid: str):
        x = data.get("x")
        y = data.get("y")
        
        gs = get_room(room_id)
        player = find_player_by_sid(gs, sid)
        
        if not gs or not player or not gs.game_state:
            return
            
        omok_logic = gs.game_state
        
        success, message = omok_logic.place_stone(player.sid, x, y)
        
        if success:
            socketio.emit("omok:update_board", {
                "board": omok_logic.board,
                "lastMove": {"x": x, "y": y, "color": omok_logic.board[y][x]}
            }, room=room_id)
            
            if omok_logic.phase == 'GAME_OVER':
                self._handle_game_over(room_id, gs, omok_logic)
            else:
                self.start_turn(room_id, gs)
        else:
            emit("error_message", {"message": message})
            import traceback
            traceback.print_exc()

    def leave_game(self, room_id: str, sid: str):
        """플레이어 이탈 처리"""
        gs = get_room(room_id)
        if not gs or not gs.game_state:
            return

        omok_logic = gs.game_state
        player = find_player_by_sid(gs, sid)
        
        if not player:
            return

        print(f"🚪 [Omok] Player {player.nickname} leaving game.")
        
        # Determine winner (Opponent)
        opponent = next((p for p in gs.players if p.uid != player.uid), None)
        
        if opponent:
            print(f"🏆 [Omok] Opponent {opponent.nickname} wins by default.")
            omok_logic.winner = opponent
            omok_logic.phase = 'GAME_OVER'
            omok_logic.winning_line = [] # No line for forfeit
            
            # End game immediately
            self._handle_game_over(room_id, gs, omok_logic, reason="player_left")

    def on_disconnect(self, room_id: str, sid: str):
        """플레이어 연결 끊김 처리"""
        print(f"🔌 [Omok] on_disconnect: {sid} in room {room_id}")
        self.leave_game(room_id, sid)

    def _handle_game_over(self, room_id: str, gs, omok_logic, reason=None):
        winner = omok_logic.winner
        print(f"🏆 [Omok] Game Over! Winner: {winner.nickname}")
        
        winner.final_rank = 1
        loser = next(p for p in gs.players if p != winner)
        loser.final_rank = 2
        
        from game_events import handle_winnings
        payout_results = handle_winnings(room_id)
        
        # 🔥 [FIX] Use serialize_player to send full winner data (including SID and Character)
        from utils import serialize_player
        serialized_winner = serialize_player(winner)
        
        # Determine reason if not provided
        if not reason:
             reason = "player_left" if omok_logic.phase == 'GAME_OVER' and not omok_logic.winning_line else "normal"

        print(f"🏆 [OMOK] Emitting game_over with winningLine: {omok_logic.winning_line}, Reason: {reason}")
        socketio.emit("game_over", {
            "winner": serialized_winner, 
            "payouts": payout_results,
            "winningLine": omok_logic.winning_line,
            "reason": reason
        }, room=room_id)
