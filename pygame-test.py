#!/usr/bin/env python3
"""Minimal pygame test - works on both macOS and Raspberry Pi"""

import os
import platform
import pygame

# Platform detection
IS_PI = platform.machine() in ['aarch64', 'armv7l']

if IS_PI:
    print("🍓 Detected Raspberry Pi - setting up framebuffer")
    # Set XDG_RUNTIME_DIR
    if 'XDG_RUNTIME_DIR' not in os.environ:
        os.environ['XDG_RUNTIME_DIR'] = '/tmp'

    # Disable SDL audio
    os.environ['SDL_AUDIODRIVER'] = 'dummy'

    # Point to framebuffer device
    os.environ['SDL_FBDEV'] = '/dev/fb1'  # Change to /dev/fb0 if needed

    # Let SDL auto-detect video driver
    if 'SDL_VIDEODRIVER' in os.environ:
        del os.environ['SDL_VIDEODRIVER']
else:
    print("💻 Detected desktop - using windowed mode")

# Initialize pygame
pygame.init()

# Create display
if IS_PI:
    screen = pygame.display.set_mode((800, 480), pygame.FULLSCREEN)
else:
    screen = pygame.display.set_mode((800, 480))

pygame.display.set_caption("Pygame Test")

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)

# Font
font = pygame.font.SysFont('dejavusans', 36)

print(f"✅ Display initialized: {pygame.display.get_driver()}")

# Main loop
clock = pygame.time.Clock()
running = True
frame = 0

try:
    while running:
        # Handle events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE or event.key == pygame.K_q:
                    running = False

        # Clear screen
        screen.fill(BLACK)

        # Draw some shapes
        pygame.draw.circle(screen, RED, (200, 240), 50)
        pygame.draw.rect(screen, GREEN, (300, 190, 100, 100))
        pygame.draw.polygon(screen, BLUE, [(500, 290), (550, 190), (600, 290)])

        # Animated circle
        x = 400 + int(100 * (frame % 60) / 60)
        pygame.draw.circle(screen, WHITE, (x, 400), 20)

        # Text
        text = font.render(f"Pygame Test - Frame {frame}", True, WHITE)
        screen.blit(text, (50, 50))

        # Update display
        pygame.display.flip()

        # Cap at 30 FPS
        clock.tick(30)
        frame += 1

except KeyboardInterrupt:
    print("\n👋 Interrupted by user")

finally:
    pygame.quit()
    print("✅ Pygame cleaned up")
