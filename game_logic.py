# game_logic.py
import random
from typing import List, Literal, Optional
from models import Tile, Player, GameState, Color

def shuffle(arr):
    tmp = arr[:]
    random.shuffle(tmp)
    return tmp

def make_tile(gs: GameState, color: Color, value: Optional[int], is_joker: bool) -> Tile:
    t = Tile(
        id=gs.next_tile_id,
        color=color,
        value=value,
        is_joker=is_joker,
        revealed=False,
    )
    gs.next_tile_id += 1
    return t

def make_tiles_by_color(gs: GameState, color: Color) -> List[Tile]:
    arr: List[Tile] = []
    for v in range(0, 12):
        arr.append(make_tile(gs, color, v, False))
    arr.append(make_tile(gs, color, None, True))  # 조커
    return shuffle(arr)

def compare_tiles(a: Tile, b: Tile, same_number_order: str = "black-first") -> int:
    if a.is_joker and b.is_joker:
        return 0
    if a.is_joker:
        return 1
    if b.is_joker:
        return -1
    if a.value != b.value:
        return (a.value or 0) - (b.value or 0)
    if same_number_order == "black-first":
        return -1 if a.color == "black" else 1
    else:
        return -1 if a.color == "white" else 1

def sort_hand(gs: GameState, hand: List[Tile]) -> None:
    hand.sort(key=lambda t: (t.value if not t.is_joker else 999,
                             0 if t.color == "black" else 1))

def prepare_tiles(gs: GameState):
    gs.next_tile_id = 0
    gs.piles["black"] = make_tiles_by_color(gs, "black")
    gs.piles["white"] = make_tiles_by_color(gs, "white")

def deal_initial_hands(gs: GameState):
    num_players = len(gs.players)
    if num_players == 0:
        return
    initial_count = 3 if num_players == 4 else 4
    joker_buf = {"black": [], "white": []}
    for p in gs.players:
        p.hand = []
        while len(p.hand) < initial_count:
            first: Color = "black" if random.random() < 0.5 else "white"
            second: Color = "white" if first == "black" else "black"
            pile_first = gs.piles[first]
            pile_second = gs.piles[second]
            t = pile_first.pop() if pile_first else (pile_second.pop() if pile_second else None)
            if not t:
                break
            if t.is_joker:
                joker_buf[t.color].append(t)
                continue
            p.hand.append(t)
        sort_hand(gs, p.hand)
    gs.piles["black"] = shuffle(gs.piles["black"] + joker_buf["black"])
    gs.piles["white"] = shuffle(gs.piles["white"] + joker_buf["white"])

def auto_insert_index(gs: GameState, hand: List[Tile], tile: Tile) -> int:
    if tile.is_joker:
        return len(hand)
    numeric_idx = [i for i, t in enumerate(hand) if not t.is_joker]
    k = 0
    while k < len(numeric_idx):
        other = hand[numeric_idx[k]]
        if compare_tiles(tile, other, gs.same_number_order) < 0:
            break
        k += 1
    if not numeric_idx:
        return 0
    if k == len(numeric_idx):
        return numeric_idx[-1] + 1
    return numeric_idx[k]

def start_turn_from(gs: GameState, player: Player, color: Color) -> Optional[Tile]:
    if gs.pending_placement:
        return None
    pile = gs.piles[color]
    if not pile:
        other_color: Color = "white" if color == "black" else "black"
        pile = gs.piles[other_color]
        if not pile:
             return None
    t = pile.pop()
    gs.drawn_tile = t
    gs.pending_placement = True
    gs.can_place_anywhere = t.is_joker
    return t

def auto_place_drawn_tile(gs: GameState, player: Player):
    t = gs.drawn_tile
    if not t or t.is_joker:
        return
    idx = auto_insert_index(gs, player.hand, t)
    player.hand.insert(idx, t)
    player.last_drawn_index = idx
    gs.drawn_tile = None
    gs.pending_placement = False
    gs.can_place_anywhere = False

def guess_tile(gs: GameState, guesser: Player, target_id: int, index: int, value: Optional[int]):
    target = next((p for p in gs.players if p.id == target_id), None)
    if not target:
        return {"ok": False, "reason": "invalid-player"}
    if index < 0 or index >= len(target.hand):
        return {"ok": False, "reason": "invalid-index"}
    tile = target.hand[index]
    if tile.revealed:
        return {"ok": False, "reason": "already-revealed"}

    correct = tile.value == value
    if correct:
        tile.revealed = True
        return {"ok": True, "correct": True}
    
    unrevealed_cards = [t for t in guesser.hand if not t.revealed]
    if unrevealed_cards:
        card_to_reveal = random.choice(unrevealed_cards)
        card_to_reveal.revealed = True
    return {"ok": True, "correct": False}