class OmokLogic:
    def __init__(self, players):
        self.players = players # List of Player objects
        self.board_size = 15
        self.board = [[0 for _ in range(self.board_size)] for _ in range(self.board_size)]
        self.current_turn_index = 0 # 0: Black, 1: White
        self.phase = 'PLAYING' # PLAYING, GAME_OVER
        self.winner = None
        self.pot = 0
        
        # Assign colors (Player 0: Black, Player 1: White)
        # Assuming players list is shuffled or fixed order.
        # Black goes first.
        
        # Calculate pot (e.g., ante)
        # For simplicity, let's say ante is handled outside or passed in.
        # But here we can just track it if needed.
        # Let's assume ante was deducted before start or we deduct here.
        self.ante = 1000
        for p in self.players:
            if p.money >= self.ante:
                p.money -= self.ante
                p.bet_amount = self.ante
                self.pot += self.ante
            else:
                p.bet_amount = p.money
                self.pot += p.money
                p.money = 0

    def get_state(self):
        return {
            'players': [p.to_dict() for p in self.players],
            'board': self.board,
            'currentTurn': self.players[self.current_turn_index].id,
            'phase': self.phase,
            'winner': self.winner.to_dict() if self.winner else None,
            'pot': self.pot
        }

    def place_stone(self, player_sid, x, y):
        if self.phase != 'PLAYING':
            return False, "Game is over"
            
        current_player = self.players[self.current_turn_index]
        
        if current_player.sid != player_sid:
            return False, "Not your turn"
            
        if not (0 <= x < self.board_size and 0 <= y < self.board_size):
            return False, "Invalid position"
            
        if self.board[y][x] != 0:
            return False, "Position already taken"
            
        # Place stone (1 for Black, 2 for White)
        stone_color = self.current_turn_index + 1
        self.board[y][x] = stone_color
        
        # Check win
        if self.check_win(x, y, stone_color):
            self.end_game(current_player)
        else:
            self.switch_turn()
            
        return True, None

    def switch_turn(self):
        self.current_turn_index = (self.current_turn_index + 1) % len(self.players)

    def check_win(self, x, y, color):
        directions = [
            (1, 0), # Horizontal
            (0, 1), # Vertical
            (1, 1), # Diagonal \
            (1, -1) # Diagonal /
        ]
        
        for dx, dy in directions:
            count = 1
            
            # Check forward
            nx, ny = x + dx, y + dy
            while 0 <= nx < self.board_size and 0 <= ny < self.board_size and self.board[ny][nx] == color:
                count += 1
                nx += dx
                ny += dy
                
            # Check backward
            nx, ny = x - dx, y - dy
            while 0 <= nx < self.board_size and 0 <= ny < self.board_size and self.board[ny][nx] == color:
                count += 1
                nx -= dx
                ny -= dy
                
            if count >= 5:
                return True
                
        return False

    def end_game(self, winner):
        self.phase = 'GAME_OVER'
        self.winner = winner
        winner.money += self.pot
