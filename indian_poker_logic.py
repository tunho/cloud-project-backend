import random

class IndianPokerLogic:
    def __init__(self, players):
        print(f"🃏 [IndianPokerLogic] Initializing with {len(players)} players")
        self.players = players # List of Player objects
        self.deck = []
        self.chips = {p.uid: 100 for p in players} # Initial chips
        print(f"🃏 [IndianPokerLogic] Initial chips: {self.chips}")
        self.current_round = 0
        self.max_rounds = 10
        self.pot = 0
        self.current_bets = {p.uid: 0 for p in players} # Bets in current round
        self.hands = {p.uid: None for p in players} # Current card
        self.dealer_index = 0 # Who acts first
        self.current_turn_index = 0
        self.phase = 'BETTING' # BETTING, SHOWDOWN, GAME_OVER
        self.winner = None
        self.game_over = False
        self.game_started = False # 🔥 Added for consistency
        self.last_action = None # {uid, action, amount}
        self.min_bet = 1
        self.betting_history = [] # List of actions in current round

        self.start_round()

    def start_round(self):
        print(f"🃏 [IndianPokerLogic] start_round called. Current: {self.current_round}, Max: {self.max_rounds}")
        
        # 🔥 [FIX] Ensure round starts at 1
        if self.current_round == 0:
             self.current_round = 0 # Will be incremented to 1 below
             
        if self.current_round >= self.max_rounds or any(c <= 0 for c in self.chips.values()):
            print(f"🃏 [IndianPokerLogic] Game Over condition met. Chips: {self.chips}")
            self.game_over = True
            self.phase = 'GAME_OVER'
            self._determine_final_winner()
            return

        self.current_round += 1
        print(f"🃏 [IndianPokerLogic] Round started: {self.current_round}")
        self.deck = [i for i in range(1, 11)] * 2 # 1-10, 2 sets
        random.shuffle(self.deck)
        
        # Deal cards
        for p in self.players:
            self.hands[p.uid] = self.deck.pop()
            
        # Ante (Basic bet)
        self.pot = 0
        self.current_bets = {p.uid: 0 for p in self.players}
        for p in self.players:
            ante = 1
            if self.chips[p.uid] >= ante:
                self.chips[p.uid] -= ante
                self.current_bets[p.uid] = ante
                self.pot += ante
            else:
                # All-in for ante (rare but possible)
                self.current_bets[p.uid] = self.chips[p.uid]
                self.pot += self.chips[p.uid]
                self.chips[p.uid] = 0

        self.phase = 'BETTING'
        self.current_turn_index = self.dealer_index
        self.betting_history = []
        
        # Dealer rotates each round
        self.dealer_index = (self.dealer_index + 1) % len(self.players)

    def get_current_player(self):
        if not self.players:
            return None
        if self.current_turn_index >= len(self.players):
            self.current_turn_index = 0
        return self.players[self.current_turn_index]

    def switch_turn(self):
        self.current_turn_index = (self.current_turn_index + 1) % len(self.players)

    def process_bet(self, uid, action, amount=0, bet_label=None):
        player = next((p for p in self.players if p.uid == uid), None)
        opponent = next((p for p in self.players if p.uid != uid), None)
        
        if not player or not opponent:
            return False, "Player or Opponent not found"
        
        current_max_bet = max(self.current_bets.values())
        my_current_bet = self.current_bets[uid]
        call_amount = current_max_bet - my_current_bet

        if action == 'FOLD':
            self.phase = 'SHOWDOWN'
            self.winner = opponent # Opponent wins immediately
            self.last_action = {'uid': uid, 'action': 'FOLD', 'amount': 0}
            self._end_round(fold_winner=opponent)
            return True, "Fold"

        elif action == 'CALL':
            cost = call_amount
            print(f"🃏 [Logic] CALL/CHECK: uid={uid}, cost={cost}, chips={self.chips[uid]}")
            
            if self.chips[uid] < cost:
                cost = self.chips[uid] # All-in call
            
            self.chips[uid] -= cost
            self.current_bets[uid] += cost
            self.pot += cost
            self.last_action = {'uid': uid, 'action': 'CALL', 'amount': cost, 'bet_label': bet_label}
            self.betting_history.append({'uid': uid, 'action': 'CALL', 'amount': cost, 'bet_label': bet_label})
            
            print(f"🃏 [Logic] History: {self.betting_history}")
            print(f"🃏 [Logic] Bets: {self.current_bets}")

            # If bets are equal, betting ends (unless it was the first bet of round)
            # Check (Call 0) is valid.
            if self.current_bets[uid] == self.current_bets[opponent.uid] and len(self.betting_history) > 1:
                 print("🃏 [Logic] Bets matched & History > 1 -> SHOWDOWN")
                 self.phase = 'SHOWDOWN'
                 self._resolve_showdown()
            else:
                print("🃏 [Logic] Switching Turn")
                self.switch_turn()
            return True, "Call"

        elif action == 'RAISE':
            # Raise amount is ON TOP of the call amount
            # Total bet = Current Max + Raise Amount
            total_cost = call_amount + amount
            
            if self.chips[uid] < total_cost:
                return False, "Not enough chips"
            
            self.chips[uid] -= total_cost
            self.current_bets[uid] += total_cost
            self.pot += total_cost
            self.last_action = {'uid': uid, 'action': 'RAISE', 'amount': total_cost, 'bet_label': bet_label}
            self.betting_history.append({'uid': uid, 'action': 'RAISE', 'amount': total_cost, 'bet_label': bet_label})
            self.switch_turn()
            return True, "Raise"
            
        elif action == 'ALLIN':
            cost = self.chips[uid]
            self.chips[uid] = 0
            self.current_bets[uid] += cost
            self.pot += cost
            self.last_action = {'uid': uid, 'action': 'ALLIN', 'amount': cost, 'bet_label': bet_label}
            self.betting_history.append({'uid': uid, 'action': 'ALLIN', 'amount': cost, 'bet_label': bet_label})
            
            # If opponent is already all-in or bets matched, showdown
            if self.chips[opponent.uid] == 0 or self.current_bets[uid] == self.current_bets[opponent.uid]:
                self.phase = 'SHOWDOWN'
                self._resolve_showdown()
            else:
                self.switch_turn()
            return True, "All-in"

        return False, "Invalid Action"

    def _resolve_showdown(self):
        p1 = self.players[0]
        p2 = self.players[1]
        v1 = self.hands[p1.uid]
        v2 = self.hands[p2.uid]
        
        winner = None
        if v1 > v2:
            winner = p1
        elif v2 > v1:
            winner = p2
        else:
            # Draw - Split pot
            pass
            
        self._end_round(winner)

    def _end_round(self, fold_winner=None):
        if fold_winner:
            # Fold winner takes all
            self.chips[fold_winner.uid] += self.pot
            self.winner = fold_winner
        else:
            # Showdown
            if self.winner:
                self.chips[self.winner.uid] += self.pot
            else:
                # Draw - Return bets (simplified) or split pot
                half_pot = self.pot // 2
                for p in self.players:
                    self.chips[p.uid] += half_pot
        
        # Check for game over (bankruptcy or max rounds)
        if any(c <= 0 for c in self.chips.values()) or self.current_round >= self.max_rounds:
            self.game_over = True
            self.phase = 'GAME_OVER'
            self._determine_final_winner()
        else:
            # Prepare next round (frontend will trigger start_round via timer/click)
            pass

    def _determine_final_winner(self):
        p1 = self.players[0]
        p2 = self.players[1]
        c1 = self.chips[p1.uid]
        c2 = self.chips[p2.uid]
        
        if c1 > c2:
            self.winner = p1
        elif c2 > c1:
            self.winner = p2
        else:
            self.winner = None # Draw
