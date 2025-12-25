# loderunner_min.py
# Minimal Lode Runner–style grid engine:
# - Tile map (8x8-ish logic but here tile size is 32 for visibility)
# - Player movement: walk, climb, rope, gravity
# - Dig left/right: remove BRICK -> HOLE with regen timer
# - Enemies chase player with simple rule-based AI (no pathfinding)
#
# Controls:
#   Arrow keys: move
#   Z: dig left
#   X: dig right
#   R: reset level
#   ESC: quit

import pygame
from dataclasses import dataclass
from typing import List, Tuple, Optional

# ----------------------------
# Config
# ----------------------------
TILE = 32
FPS = 60

# Tile IDs
EMPTY = 0
BRICK = 1
LADDER = 2
ROPE = 3
GOLD = 4
EXIT = 5

# Dig behavior
HOLE_REGEN_FRAMES = 240  # 4 seconds @ 60fps

# Enemy speed (move every N frames - higher = slower)
ENEMY_MOVE_INTERVAL = 10  # Enemies move every 6 frames (much slower)

# Colors (simple)
COLORS = {
    EMPTY: (25, 25, 35),
    BRICK: (140, 70, 50),
    LADDER: (220, 200, 80),
    ROPE: (200, 200, 220),
    GOLD: (240, 200, 0),
    EXIT: (80, 200, 120),
}

PLAYER_COLOR = (120, 170, 255)
ENEMY_COLOR = (255, 120, 120)

# ----------------------------
# Level (data-driven)
# ----------------------------
LEVEL_STR = [
    "####################",
    "#...........G......#",
    "#..====............#",
    "#..=..=.....HHH....#",
    "#..=..=.....H.H....#",
    "#..=..=..G..H.H....#",
    "#..=..=.....H.H....#",
    "#..=..=.....HHH....#",
    "#..=..=............#",
    "#..=..=.....G......#",
    "#..=..=............#",
    "#..=..=......E.....#",
    "#..=..=............#",
    "#..=..=............#",
    "#..=..=............#",
    "#..........P.......#",
    "####################",
]

# Legend:
#   . empty
#   # brick
#   H ladder
#   = rope
#   G gold
#   P player start
#   E exit

def parse_level(lines: List[str]) -> Tuple[List[List[int]], Tuple[int, int], Tuple[int, int], List[Tuple[int, int]]]:
    grid: List[List[int]] = []
    player_start = (1, 1)
    exit_pos = (1, 1)
    gold_positions: List[Tuple[int, int]] = []

    for y, row in enumerate(lines):
        r: List[int] = []
        for x, ch in enumerate(row):
            if ch == ".":
                r.append(EMPTY)
            elif ch == "#":
                r.append(BRICK)
            elif ch == "H":
                r.append(LADDER)
            elif ch == "=":
                r.append(ROPE)
            elif ch == "G":
                r.append(GOLD)
                gold_positions.append((x, y))
            elif ch == "P":
                r.append(EMPTY)
                player_start = (x, y)
            elif ch == "E":
                r.append(EXIT)
                exit_pos = (x, y)
            else:
                r.append(EMPTY)
        grid.append(r)

    return grid, player_start, exit_pos, gold_positions

# ----------------------------
# Helpers
# ----------------------------
def in_bounds(grid, x, y) -> bool:
    return 0 <= y < len(grid) and 0 <= x < len(grid[0])

def tile_at(grid, x, y) -> int:
    if not in_bounds(grid, x, y):
        return BRICK  # treat out-of-bounds as solid
    return grid[y][x]

def is_solid(t: int) -> bool:
    return t == BRICK

def is_climbable(t: int) -> bool:
    return t == LADDER

def is_rope(t: int) -> bool:
    return t == ROPE

def is_walkable(t: int) -> bool:
    # player can occupy these
    return t in (EMPTY, LADDER, ROPE, GOLD, EXIT)

def to_px(x, y) -> Tuple[int, int]:
    return x * TILE, y * TILE

# ----------------------------
# Entities
# ----------------------------
@dataclass
class Hole:
    x: int
    y: int
    timer: int  # frames until regen

@dataclass
class Player:
    x: int
    y: int
    gold: int = 0

@dataclass
class Enemy:
    x: int
    y: int
    respawn: Tuple[int, int]

# ----------------------------
# Core game logic (NES-ish)
# ----------------------------
class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        self.grid, pstart, self.exit_pos, _ = parse_level(LEVEL_STR)
        self.player = Player(*pstart)
        self.enemies = [
            Enemy(self.player.x + 6, self.player.y - 6, (self.player.x + 6, self.player.y - 6)),
        ]
        self.holes: List[Hole] = []
        self.won = False
        self.dead = False
        self.countdown = 300  # 5 seconds at 60fps
        self.enemy_frame_counter = 0  # Counter to slow down enemy movement

    def tile(self, x, y) -> int:
        return tile_at(self.grid, x, y)

    def set_tile(self, x, y, t: int):
        if in_bounds(self.grid, x, y):
            self.grid[y][x] = t

    def gravity_applies(self, x, y) -> bool:
        """True if entity at (x,y) should fall."""
        under = self.tile(x, y + 1)
        here = self.tile(x, y)
        # if standing on rope, don't fall
        if is_rope(here):
            return False
        # if on ladder, you can "stick" (classic lode runner)
        if is_climbable(here):
            return False
        # fall if tile below is not solid and not a ladder top supporting you
        return not is_solid(under) and not is_climbable(under)

    def try_move(self, ent, dx: int, dy: int):
        nx, ny = ent.x + dx, ent.y + dy
        if is_walkable(self.tile(nx, ny)):
            ent.x, ent.y = nx, ny
            return True
        return False
    
    def try_move_enemy(self, e: Enemy, dx: int, dy: int):
        """Try to move an enemy, but prevent overlapping with other enemies."""
        nx, ny = e.x + dx, e.y + dy
        
        # Check if target tile is walkable
        if not is_walkable(self.tile(nx, ny)):
            return False
        
        # Check if another enemy is already at the target position
        for other in self.enemies:
            if other is not e and (other.x, other.y) == (nx, ny):
                return False
        
        # Move is valid
        e.x, e.y = nx, ny
        return True

    def collect_gold(self):
        if self.tile(self.player.x, self.player.y) == GOLD:
            self.set_tile(self.player.x, self.player.y, EMPTY)
            self.player.gold += 1

    def dig(self, direction: int):
        """
        direction: -1 left, +1 right
        NES-style: dig diagonally down (x+dir, y+1) only if it's BRICK
        and the adjacent side tile is empty/walkable (so you can dig into it).
        Can dig even when dead or during countdown.
        """
        # Allow digging even when dead or during countdown
        px, py = self.player.x, self.player.y
        target_x, target_y = px + direction, py + 1
        # must be brick to dig
        if self.tile(target_x, target_y) != BRICK:
            return
        # must have space beside player (classic rule; simplified)
        if not is_walkable(self.tile(px + direction, py)):
            return

        # create hole: replace BRICK with EMPTY, track regen timer
        self.set_tile(target_x, target_y, EMPTY)
        self.holes.append(Hole(target_x, target_y, HOLE_REGEN_FRAMES))

    def update_holes(self):
        # decrement timers; regen bricks; kill enemies trapped inside when regen happens
        for h in self.holes[:]:
            h.timer -= 1
            if h.timer <= 0:
                # if an enemy is in the hole tile, "crush" them and respawn
                for e in self.enemies:
                    if (e.x, e.y) == (h.x, h.y):
                        e.x, e.y = e.respawn
                self.set_tile(h.x, h.y, BRICK)
                self.holes.remove(h)

    def enemy_ai_step(self, e: Enemy):
        """
        Rule-based chase (no pathfinding):
        Priority:
          1) If enemy is above player and standing on ladder or ladder is here -> go down/up ladder toward player
          2) If same row -> move horizontally toward player
          3) Else if gravity -> fall (handled outside)
          4) Small fallback: try to align horizontally
        """
        px, py = self.player.x, self.player.y
        ex, ey = e.x, e.y

        here = self.tile(ex, ey)
        up = self.tile(ex, ey - 1)
        down = self.tile(ex, ey + 1)

        # Ladder chase if possible
        if is_climbable(here) or is_climbable(down) or is_climbable(up):
            if py < ey and is_walkable(up) and (is_climbable(here) or is_climbable(up)):
                self.try_move_enemy(e, 0, -1)
                return
            if py > ey and is_walkable(down) and (is_climbable(here) or is_climbable(down)):
                self.try_move_enemy(e, 0, 1)
                return

        # Horizontal chase if on same row
        if py == ey:
            if px < ex:
                self.try_move_enemy(e, -1, 0)
            elif px > ex:
                self.try_move_enemy(e, 1, 0)
            return

        # Fallback: try to move toward player horizontally if not blocked
        if px < ex:
            self.try_move_enemy(e, -1, 0)
        elif px > ex:
            self.try_move_enemy(e, 1, 0)

    def handle_player_move(self, dx: int, dy: int):
        """Handle a single player movement input (one tile at a time)."""
        if self.won or self.dead or self.countdown > 0:
            return
        
        # For vertical movement, check if it's allowed
        # (can move to walkable tiles, or from ladder/rope to adjacent tiles)
        if dy != 0:
            current_tile = self.tile(self.player.x, self.player.y)
            target_tile = self.tile(self.player.x, self.player.y + dy)
            
            # Allow if target is walkable OR we're on a climbable surface
            if not is_walkable(target_tile):
                # Only allow if we're on a ladder or rope (can move from them)
                if not (is_climbable(current_tile) or is_rope(current_tile)):
                    return

        # Apply horizontal movement
        if dx != 0:
            if self.try_move(self.player, dx, 0):
                self.collect_gold()
        
        # Apply vertical movement
        if dy != 0:
            if self.try_move(self.player, 0, dy):
                self.collect_gold()

    def update_entities(self):
        if self.won or self.dead:
            return
        
        # During countdown, prevent all movement (player and enemies)
        if self.countdown > 0:
            return

        # Gravity (one tile per frame max, like grid-step)
        # Only apply gravity if player is not on solid ground
        if self.gravity_applies(self.player.x, self.player.y):
            self.try_move(self.player, 0, 1)

        # Collect gold
        self.collect_gold()

        # Win condition: reach exit after collecting all gold (simplified)
        any_gold_left = any(GOLD in row for row in self.grid)
        if not any_gold_left and (self.player.x, self.player.y) == self.exit_pos:
            self.won = True

        # --- Enemies ---
        # Only move enemies every N frames to slow them down
        self.enemy_frame_counter += 1
        if self.enemy_frame_counter >= ENEMY_MOVE_INTERVAL:
            self.enemy_frame_counter = 0
            for e in self.enemies:
                # gravity for enemy
                if self.gravity_applies(e.x, e.y):
                    self.try_move_enemy(e, 0, 1)
                else:
                    self.enemy_ai_step(e)

        # Check collision with player (always check, not just when enemies move)
        for e in self.enemies:
            if (e.x, e.y) == (self.player.x, self.player.y):
                self.dead = True

    def step(self):
        # Decrement countdown
        if self.countdown > 0:
            self.countdown -= 1
        
        self.update_holes()
        self.update_entities()

# ----------------------------
# Rendering
# ----------------------------
def draw(game: Game, screen: pygame.Surface, font):
    screen.fill((10, 10, 15))

    h = len(game.grid)
    w = len(game.grid[0])

    # Tiles
    for y in range(h):
        for x in range(w):
            t = game.grid[y][x]
            if t != EMPTY:
                pygame.draw.rect(screen, COLORS[t], pygame.Rect(x*TILE, y*TILE, TILE, TILE))

            # ladders/ropes as thin lines for readability
            if t == LADDER:
                pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(x*TILE + TILE//3, y*TILE, TILE//3, TILE), 0)
            if t == ROPE:
                pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(x*TILE, y*TILE + TILE//2 - 2, TILE, 4), 0)

    # Holes overlay
    for h0 in game.holes:
        pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(h0.x*TILE, h0.y*TILE, TILE, TILE))
        # small timer bar
        bar_w = int(TILE * (h0.timer / HOLE_REGEN_FRAMES))
        pygame.draw.rect(screen, (80, 80, 100), pygame.Rect(h0.x*TILE, h0.y*TILE + TILE - 6, bar_w, 6))

    # Player
    px, py = to_px(game.player.x, game.player.y)
    pygame.draw.rect(screen, PLAYER_COLOR, pygame.Rect(px + 6, py + 6, TILE - 12, TILE - 12))

    # Enemies
    for e in game.enemies:
        ex, ey = to_px(e.x, e.y)
        pygame.draw.rect(screen, ENEMY_COLOR, pygame.Rect(ex + 6, ey + 6, TILE - 12, TILE - 12))

    # HUD
    msg = f"Gold: {game.player.gold}   Holes: {len(game.holes)}"
    if game.countdown > 0:
        countdown_seconds = (game.countdown // FPS) + 1
        msg += f"   Starting in {countdown_seconds}..."
    elif game.won:
        msg += "   YOU WIN! (R to reset)"
    elif game.dead:
        msg += "   YOU DIED! (R to reset)"

    text = font.render(msg, True, (220, 220, 230))
    screen.blit(text, (10, 8))
    
    # Display large countdown in center of screen
    if game.countdown > 0:
        countdown_seconds = (game.countdown // FPS) + 1
        try:
            large_font = pygame.font.SysFont("Arial", 72, bold=True)
        except:
            large_font = pygame.font.SysFont("Arial", 72)
        countdown_text = large_font.render(str(countdown_seconds), True, (255, 255, 0))
        text_rect = countdown_text.get_rect(center=(w // 2, h // 2))
        # Draw semi-transparent background
        overlay = pygame.Surface((text_rect.width + 40, text_rect.height + 40))
        overlay.set_alpha(180)
        overlay.fill((0, 0, 0))
        screen.blit(overlay, (text_rect.x - 20, text_rect.y - 20))
        screen.blit(countdown_text, text_rect)

    hint = font.render("Arrows move | Z dig left | X dig right | R reset | ESC quit", True, (170, 170, 190))
    screen.blit(hint, (10, 30))

# ----------------------------
# Main
# ----------------------------
def main():
    pygame.init()
    grid, _, _, _ = parse_level(LEVEL_STR)
    w, h = len(grid[0]) * TILE, len(grid) * TILE
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("Lode Runner–style Mini Engine (Python/Pygame)")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 18)

    game = Game()

    running = True
    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    game.reset()
                elif event.key == pygame.K_z:
                    game.dig(-1)
                elif event.key == pygame.K_x:
                    game.dig(1)
                elif event.key == pygame.K_LEFT:
                    game.handle_player_move(-1, 0)
                elif event.key == pygame.K_RIGHT:
                    game.handle_player_move(1, 0)
                elif event.key == pygame.K_UP:
                    game.handle_player_move(0, -1)
                elif event.key == pygame.K_DOWN:
                    game.handle_player_move(0, 1)

        game.step()
        draw(game, screen, font)
        pygame.display.flip()

    pygame.quit()

if __name__ == "__main__":
    main()
