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

# game_logic.py

def guess_tile(gs: GameState, guesser: Player, target_id: int, index: int, value: Optional[int]):
    target = next((p for p in gs.players if p.id == target_id), None)
    
    # 1. 에러 처리 (correct: False 포함)
    if not target:
        return {"ok": False, "reason": "invalid-player", "correct": False}
    if index < 0 or index >= len(target.hand):
        return {"ok": False, "reason": "invalid-index", "correct": False}
    tile = target.hand[index]
    if tile.revealed:
        return {"ok": False, "reason": "already-revealed", "correct": False}

    # 2. 정답 여부 확인
    correct = tile.value == value
    
    if correct:
        tile.revealed = True
        # ▼▼▼ [수정] 정답 시 실제 타일 정보(actual_tile) 반환 ▼▼▼
        return {
            "ok": True, 
            "correct": True, 
            "actual_tile": tile  # (Tile 객체 그대로 반환, emit 시 to_dict 처리됨)
        }
    
    # 3. 오답 처리 (페널티)
    penalty_tile = None
    unrevealed_cards = [t for t in guesser.hand if not t.revealed]
    
    if unrevealed_cards:
        # 내 카드 중 하나를 랜덤으로 공개
        card_to_reveal = random.choice(unrevealed_cards)
        card_to_reveal.revealed = True
        penalty_tile = card_to_reveal # 페널티 타일 정보 저장

    # ▼▼▼ [수정] 오답 시 페널티 타일 정보 반환 ▼▼▼
    # (주의: 오답일 때는 target의 actual_tile을 반환하면 안 됩니다! 보안상 클라이언트가 몰라야 함)
    return {
        "ok": True, 
        "correct": False, 
        "penalty_tile": penalty_tile 
    }