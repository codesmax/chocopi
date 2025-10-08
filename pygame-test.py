#!/usr/bin/env python3
"""Minimal pygame test - works on both macOS and Raspberry Pi"""

import os
import platform
import sys

# Platform detection
IS_PI = platform.machine() in ['aarch64', 'armv7l']

print(f"Python: {sys.version}")
print(f"Platform: {platform.machine()}")

# Check pygame before importing
try:
    import pygame
    print(f"Pygame version: {pygame.version.ver}")
    print(f"SDL version: {pygame.version.SDL}")
except Exception as e:
    print(f"Error importing pygame: {e}")
    exit(1)

if IS_PI:
    print("🍓 Detected Raspberry Pi - setting up framebuffer")

    # Try different video drivers
    drivers_to_try = [
        ('fbcon', {'SDL_FBDEV': '/dev/fb1', 'SDL_VIDEODRIVER': 'fbcon'}),
        ('kmsdrm', {'SDL_FBDEV': '/dev/fb1', 'SDL_VIDEODRIVER': 'kmsdrm'}),
        ('directfb', {'SDL_FBDEV': '/dev/fb1', 'SDL_VIDEODRIVER': 'directfb'}),
        ('auto', {'SDL_FBDEV': '/dev/fb1'}),
    ]

    screen = None
    for driver_name, env_vars in drivers_to_try:
        print(f"\n🔍 Trying driver: {driver_name}")

        # Clean up previous attempt
        pygame.quit()

        # Set environment
        os.environ['SDL_AUDIODRIVER'] = 'dummy'
        if 'XDG_RUNTIME_DIR' not in os.environ:
            os.environ['XDG_RUNTIME_DIR'] = '/tmp'

        for key, value in env_vars.items():
            os.environ[key] = value

        try:
            # Initialize
            pygame.display.init()
            pygame.font.init()

            detected_driver = pygame.display.get_driver()
            print(f"   Detected driver: {detected_driver}")

            # Try to create display
            screen = pygame.display.set_mode((800, 480), pygame.FULLSCREEN)
            pygame.display.set_caption("Pygame Test")

            print(f"✅ Success with {driver_name}!")
            break

        except Exception as e:
            print(f"   ❌ Failed: {e}")
            continue

    if not screen:
        print("\n💥 All drivers failed!")
        print("\nDiagnostics:")
        print("=" * 50)

        # Check framebuffer devices
        print("\nFramebuffer devices:")
        os.system("ls -l /dev/fb*")

        # Check which TTY we're on
        print("\nCurrent TTY:")
        os.system("tty")

        # Check user groups
        print("\nUser groups:")
        os.system("groups")

        # Check framebuffer info
        print("\nFramebuffer info:")
        os.system("cat /sys/class/graphics/fb0/name 2>/dev/null || echo 'fb0 info not available'")
        os.system("cat /sys/class/graphics/fb1/name 2>/dev/null || echo 'fb1 info not available'")

        # Check loaded kernel modules
        print("\nFramebuffer kernel modules:")
        os.system("lsmod | grep -i fb")

        # Try to get SDL driver info
        print("\nTrying to list SDL drivers:")
        os.system("SDL_VIDEODRIVER=help python3 -c 'import pygame; pygame.init()' 2>&1")

        # Check how SDL was compiled
        print("\nSDL video drivers compiled in:")
        os.system("python3 -c 'import pygame; pygame.init(); print([d for d in dir(pygame) if \"video\" in d.lower()])' 2>&1")

        exit(1)

else:
    print("💻 Detected desktop - using windowed mode")
    pygame.init()
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
