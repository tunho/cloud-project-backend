from threading import Timer
from flask_socketio import emit
from extensions import socketio
from handlers.base_handler import GameHandler
from utils import get_room, find_player_by_sid

class IndianPokerHandler(GameHandler):
    def start_turn(self, room_id: str, gs, force_hidden=False):
        print(f"🎬 [Handler] start_turn called for {room_id}")
        logic = gs.game_state
        
        # 🔥 [FIX] Sync Logic Players with Room Players (Handle Reconnects/Replacements)
        room_uids = [p.uid for p in gs.players]
        logic_uids = [p.uid for p in logic.players]
        
        if set(room_uids) != set(logic_uids):
            print(f"⚠️ [Sync] Player mismatch detected! Room: {room_uids}, Logic: {logic_uids}")
            logic.players = gs.players # Update reference
            
            # Sync Chips & Hands
            for p in gs.players:
                if p.uid not in logic.chips:
                    logic.chips[p.uid] = 100 # Default for new player
                if p.uid not in logic.hands:
                    logic.hands[p.uid] = None
            
            # Remove stale data
            logic.chips = {k: v for k, v in logic.chips.items() if k in room_uids}
            logic.hands = {k: v for k, v in logic.hands.items() if k in room_uids}
            logic.current_bets = {k: v for k, v in logic.current_bets.items() if k in room_uids}
            
            print(f"✅ [Sync] Logic state updated. Chips keys: {list(logic.chips.keys())}")

        # If round just ended, wait a bit then start new round
        if logic.phase == 'SHOWDOWN':
             # Logic to auto-start next round or wait for user is handled in client/events
             pass
        
        current_player = logic.get_current_player()
        
        # Start Timer
        if logic.phase == 'BETTING':
            # Cancel existing timer if any
            if hasattr(gs, 'turn_timer') and gs.turn_timer:
                gs.turn_timer.cancel()
            
            gs.turn_timer = Timer(30.0, self._handle_timeout, [room_id, gs])
            gs.turn_timer.start()

        # Broadcast state individually to show opponent's card but hide own
        for player in gs.players:
            print(f"📤 [Handler] Preparing state for {player.nickname} (SID: {player.sid})")
            # Construct hands view for this player
            hands_view = {}
            if logic.phase == 'SHOWDOWN' and not force_hidden:
                hands_view = logic.hands
            else:
                for p in gs.players:
                    if p.uid == player.uid:
                        hands_view[p.uid] = 'HIDDEN' # Hide my card
                    else:
                        hands_view[p.uid] = logic.hands.get(p.uid) # Show opponent card
            
            # Serialize players for frontend
            serialized_players = []
            for p in gs.players:
                # 🔥 [DEBUG] Log player data
                print(f"👤 [IndianPoker] Serializing {p.nickname}: Bet={p.bet_amount}, Char={p.character is not None}")
                
                serialized_players.append({
                    "uid": p.uid,
                    "nickname": p.nickname,
                    "character": p.character if p.character else {}, # 🔥 [FIX] Ensure dict
                    "sid": p.sid,
                    "money": p.money, 
                    "betAmount": logic.current_bets.get(p.uid, 0),
                    "entryBet": p.bet_amount # 🔥 [FIX] Send raw bet amount (default 10000 for custom)
                })

            print(f"📡 [IndianPoker] Sending update_state to {player.nickname}: Round={logic.current_round}, Phase={logic.phase}")
            print(f"💰 [IndianPoker] Chips: {logic.chips}, Pot: {logic.pot}")

            socketio.emit("indian_poker:update_state", {
                "round": logic.current_round,
                "pot": logic.pot,
                "chips": logic.chips,
                "currentBets": logic.current_bets,
                "currentTurnUid": current_player.uid,
                "phase": logic.phase,
                "hands": hands_view,
                "lastAction": logic.betting_history[-1] if logic.betting_history else None,
                "timeLeft": 30,
                "players": serialized_players # 🔥 Send players info
            }, room=player.sid)

    def handle_action(self, room_id: str, action: str, data: dict, sid: str):
        if action == "bet":
            self._handle_bet(room_id, data, sid)
        elif action == "next_round":
            self._start_next_round(room_id, sid)

    def _handle_bet(self, room_id: str, data: dict, sid: str):
        gs = get_room(room_id)
        player = find_player_by_sid(gs, sid)
        logic = gs.game_state
        
        if logic.get_current_player().uid != player.uid:
            return

        action = data.get('action')
        amount = data.get('amount', 0)
        bet_label = data.get('betLabel') # Extract bet label (Quarter, Half, etc.)

        if not action:
            return

        success, message = logic.process_bet(player.uid, action, amount, bet_label)
        
        if success:
            # Always broadcast state first to show the action (Call, Fold, etc.)
            # Force hidden hands even if phase is SHOWDOWN, to delay reveal until round_result
            self.start_turn(room_id, gs, force_hidden=True)

            if logic.phase == 'SHOWDOWN' or logic.phase == 'GAME_OVER':
                # Round/Game Ended
                self._broadcast_result(room_id, gs, logic)

    def _broadcast_result(self, room_id: str, gs, logic):
        # Reveal all cards
        socketio.emit("indian_poker:round_result", {
            "hands": logic.hands,
            "winnerUid": logic.winner.uid if logic.winner else None,
            "pot": logic.pot,
            "chips": logic.chips,
            "gameOver": logic.game_over,
            "round": logic.current_round
        }, room=room_id)
        
        if logic.game_over:
            self._handle_game_over(room_id, gs, logic)
    def _handle_timeout(self, room_id, gs):
        # with socketio.app.app_context(): # 🔥 Removed incorrect app context usage
        logic = gs.game_state
        current_player = logic.get_current_player()
        
        if not current_player:
            print(f"⚠️ Timeout triggered but no current player found in room {room_id}")
            return

        print(f"⏰ Turn Timeout: {current_player.nickname}")
        
        # Auto Fold on timeout
        self._handle_bet(room_id, {'action': 'FOLD'}, current_player.sid)
    def _start_next_round(self, room_id: str, sid):
        gs = get_room(room_id)
        logic = gs.game_state
        # Only host or auto-trigger? Let's allow any player to trigger for now or auto
        logic.start_round()
        self.start_turn(room_id, gs)

    def _handle_game_over(self, room_id: str, gs, logic):
        # Final Payout Logic
        winner = logic.winner
        if winner:
            winner.final_rank = 1
            loser = gs.players[1] if winner == gs.players[0] else gs.players[0]
            loser.final_rank = 2
            
            from game_events import handle_winnings
            payout_results = handle_winnings(room_id)
            
            # Determine Reason
            reason = "normal"
            if logic.current_round >= 10:
                reason = "turn_limit"
            elif any(p.money <= 0 for p in logic.players):
                reason = "bankruptcy"

            socketio.emit("game_over", {
                "winner": {"uid": winner.uid, "nickname": winner.nickname, "character": winner.character}, # 🔥 Send character too
                "payouts": payout_results,
                "reason": reason
            }, room=room_id)
