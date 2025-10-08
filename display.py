import os
import threading
import time
import pygame
from threading import Lock


class DisplayManager:
    """Manages visual display with sprite animations and transcript"""

    def __init__(self, config):
        self.config = config['display']
        self.script_path = os.path.dirname(os.path.realpath(__file__))
        self.images_path = os.path.join(self.script_path, 'images')

        # Thread safety
        self.lock = Lock()
        self.running = False
        self.thread = None

        # State
        self.is_speaking = False
        self.transcripts = []  # List of (speaker, text) tuples

        # Animation
        self.animation_frame = 0
        self.ping_pong_frames = [0, 1, 2, 3, 2, 1]  # Ping-pong pattern
        self.last_frame_time = 0

        # Pygame surfaces (initialized in thread)
        self.screen = None
        self.idle_sprite = None
        self.speaking_frames = []
        self.font = None

    def _init_pygame(self):
        """Initialize pygame in the display thread"""
        try:
            # Disable SDL audio (we use sounddevice instead)
            os.environ['SDL_AUDIODRIVER'] = 'dummy'

            # Point SDL to the correct framebuffer device (DSI display on fb1)
            os.environ['SDL_FBDEV'] = '/dev/fb1'

            # Let SDL auto-detect the video driver (will use kmsdrm on Pi 5)
            if 'SDL_VIDEODRIVER' in os.environ:
                del os.environ['SDL_VIDEODRIVER']

            pygame.init()

            # Check if display is available
            if not pygame.display.get_driver():
                print("⚠️  No display available, disabling visual output")
                return False

            # Create fullscreen display
            self.screen = pygame.display.set_mode(
                (self.config['width'], self.config['height']),
                pygame.FULLSCREEN
            )
            pygame.display.set_caption("Choco")
            pygame.mouse.set_visible(False)

            # Load sprites
            self._load_sprites()

            # Load font
            self.font = pygame.font.SysFont('dejavusans', self.config['font_size'])

            print(f"✅ Display initialized: {self.config['width']}x{self.config['height']}")
            return True

        except Exception as e:
            print(f"❌ Failed to initialize display: {e}")
            return False

    def _load_sprites(self):
        """Load idle and speaking sprites"""
        # Load idle sprite
        idle_path = os.path.join(self.images_path, 'choco.png')
        self.idle_sprite = pygame.image.load(idle_path)
        # Scale to fit graphics area (640x480)
        self.idle_sprite = pygame.transform.scale(self.idle_sprite, (640, 480))

        # Load speaking spritesheet (horizontal layout: 4 frames)
        speaking_path = os.path.join(self.images_path, 'choco-speaking.png')
        spritesheet = pygame.image.load(speaking_path)

        # Split into 4 frames
        frame_width = spritesheet.get_width() // 4
        frame_height = spritesheet.get_height()

        for i in range(4):
            frame = spritesheet.subsurface((i * frame_width, 0, frame_width, frame_height))
            # Scale to fit graphics area
            frame = pygame.transform.scale(frame, (640, 480))
            self.speaking_frames.append(frame)

    def _render_frame(self):
        """Render one frame"""
        # Parse colors
        graphics_bg = pygame.Color(self.config['colors']['graphics_bg'])
        transcript_bg = pygame.Color(self.config['colors']['transcript_bg'])
        text_color = pygame.Color(self.config['colors']['text'])

        # Clear graphics area
        self.screen.fill(graphics_bg, (0, 0, 640, 480))

        # Draw sprite
        with self.lock:
            if self.is_speaking:
                # Animate through ping-pong frames
                frame_idx = self.ping_pong_frames[self.animation_frame]
                self.screen.blit(self.speaking_frames[frame_idx], (0, 0))
            else:
                self.screen.blit(self.idle_sprite, (0, 0))

        # Clear transcript area
        self.screen.fill(transcript_bg, (0, 480, 800, 160))

        # Render transcripts
        self._render_transcripts(text_color)

        pygame.display.flip()

    def _render_transcripts(self, text_color):
        """Render transcript text in bottom area"""
        with self.lock:
            if not self.transcripts:
                return

            # Start from bottom of transcript area and work up
            y = 480 + self.config['transcript_height'] - 10  # 10px bottom margin
            line_height = self.config['font_size'] + 4  # 4px line spacing

            # Render transcripts from most recent backwards
            for speaker, text in reversed(self.transcripts):
                # Format with speaker prefix
                prefix = "🗣️  " if speaker == "user" else "🤖 "
                line = f"{prefix}{text}"

                # Render text
                text_surface = self.font.render(line, True, text_color)

                # Check if we're out of space
                if y - text_surface.get_height() < 480:
                    break

                # Draw text
                self.screen.blit(text_surface, (10, y - text_surface.get_height()))
                y -= line_height

    def _update_animation(self):
        """Update animation frame based on FPS"""
        current_time = time.time()
        frame_duration = 1.0 / self.config['animation_fps']

        if current_time - self.last_frame_time >= frame_duration:
            with self.lock:
                if self.is_speaking:
                    # Advance ping-pong frame
                    self.animation_frame = (self.animation_frame + 1) % len(self.ping_pong_frames)

            self.last_frame_time = current_time

    def _run(self):
        """Main display loop (runs in thread)"""
        if not self._init_pygame():
            return

        self.running = True
        clock = pygame.time.Clock()

        try:
            while self.running:
                # Handle pygame events (required for display to work)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False

                # Update animation
                self._update_animation()

                # Render frame
                self._render_frame()

                # Cap at 30 FPS (independent of animation FPS)
                clock.tick(30)

        finally:
            pygame.quit()

    def start(self):
        """Start the display in a separate thread"""
        if self.thread is not None:
            return

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        time.sleep(0.5)  # Give it time to initialize

    def stop(self):
        """Stop the display"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None

    def set_speaking(self, speaking):
        """Update speaking state (thread-safe)"""
        with self.lock:
            self.is_speaking = speaking
            if speaking:
                self.animation_frame = 0  # Reset animation

    def add_transcript(self, speaker, text):
        """Add a transcript line (thread-safe)"""
        with self.lock:
            self.transcripts.append((speaker, text))
            # Keep only last 10 transcripts
            if len(self.transcripts) > 10:
                self.transcripts.pop(0)


def create_display_manager(config):
    """Factory function to create display manager if enabled"""
    if not config.get('display', {}).get('enabled', False):
        return None

    try:
        return DisplayManager(config)
    except Exception as e:
        print(f"⚠️  Failed to create display manager: {e}")
        return None
