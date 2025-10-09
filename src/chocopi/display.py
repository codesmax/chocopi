import os
import platform
import threading
import time
import pygame
from threading import Lock
from chocopi.config import IMAGES_PATH, FONTS_PATH

# Platform detection for event handling
IS_MACOS = platform.system() == 'Darwin'


class DisplayManager:
    """Manages visual display with sprite animations and transcript"""

    def __init__(self, config):
        self.config = config['display']
        self.images_path = IMAGES_PATH
        self.fonts_path = FONTS_PATH

        # Computed dimensions based on config
        self.screen_width = self.config['width']
        self.screen_height = self.config['height']
        self.pane_width = self.screen_width // 2  # Split screen in half
        self.graphics_width = self.pane_width
        self.transcript_width = self.pane_width
        self.gradient_width = 200  # Gradient spans from 1/4 to 1/2 of screen
        self.gradient_start = self.pane_width - self.gradient_width
        self.transcript_margin = 10

        # Thread safety
        self.lock = Lock()
        self.running = False
        self.thread = None

        # State
        self.is_active = False  # False = sleeping (dimmed), True = awake
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
        self.gradient = None

    def _init_pygame(self):
        """Initialize pygame in the display thread"""
        try:
            pygame.init()

            # Check if display is available
            if driver := pygame.display.get_driver():
                print(f"✅ Display driver: {driver}")
            else:
                print("⚠️  No display driver available, disabling visual output")
                return False

            # Set up full-screen display on Linux/Pi
            is_pi = platform.machine().lower() in ['aarch64', 'armv7l']
            self.screen = pygame.display.set_mode(
                (self.screen_width, self.screen_height),
                pygame.FULLSCREEN if is_pi else pygame.RESIZABLE
            )
            pygame.display.set_caption("Choco")
            pygame.mouse.set_visible(False)

            # Load sprites
            self._load_sprites()

            # Load font - try bundled multilingual font first, then system fallbacks
            self.font = self._load_font()

            # Create gradient for pane transition
            self._create_gradient()

            print(f"✅ Display initialized: {self.config['width']}x{self.config['height']}")
            return True

        except Exception as e:
            print(f"❌ Failed to initialize display: {e}")
            return False

    def _load_font(self):
        """Load font with multilingual support"""
        font_size = self.config['font_size']

        # Try bundled Noto Sans CJK font (supports CJK + Latin)
        bundled_font = os.path.join(self.fonts_path, 'NotoSansCJK-VF.otf.ttc')
        if os.path.exists(bundled_font):
            print(f"📝 Using bundled font: {bundled_font}")
            return pygame.font.Font(bundled_font, font_size)

        # Fallback to system fonts with multilingual support
        system_fonts = [
            'notosans', 'notosanscjk', 'arial unicode ms',  # Multilingual
            'arial', 'helvetica', 'freesans'  # Basic fallbacks
        ]
        print(f"📝 Using system font fallback")
        return pygame.font.SysFont(system_fonts, font_size)

    def _load_sprites(self):
        """Load idle and speaking sprites"""
        # Load idle sprite - use smoothscale for better quality
        idle_path = os.path.join(self.images_path, 'choco.png')
        idle_img = pygame.image.load(idle_path)
        self.idle_sprite = pygame.transform.smoothscale(idle_img, (self.pane_width, self.screen_height))

        # Load speaking spritesheet (horizontal layout: 4 frames)
        speaking_path = os.path.join(self.images_path, 'choco-speaking.png')
        spritesheet = pygame.image.load(speaking_path)

        # Split into 4 frames - use smoothscale for better quality
        frame_width = spritesheet.get_width() // 4
        frame_height = spritesheet.get_height()

        for i in range(4):
            frame = spritesheet.subsurface((i * frame_width, 0, frame_width, frame_height))
            scaled_frame = pygame.transform.smoothscale(frame, (self.pane_width, self.screen_height))
            self.speaking_frames.append(scaled_frame)

    def _create_gradient(self):
        """Create gradient surface for smooth transition between panes"""
        self.gradient = pygame.Surface((self.gradient_width, self.screen_height), pygame.SRCALPHA)

        # Get pane colors
        graphics_bg = pygame.Color(self.config['colors']['graphics_bg'])
        transcript_bg = pygame.Color(self.config['colors']['transcript_bg'])

        # Create vertical gradient from graphics_bg to transcript_bg
        for x in range(self.gradient_width):
            # Interpolate between colors
            ratio = x / self.gradient_width
            r = int(graphics_bg.r + (transcript_bg.r - graphics_bg.r) * ratio)
            g = int(graphics_bg.g + (transcript_bg.g - graphics_bg.g) * ratio)
            b = int(graphics_bg.b + (transcript_bg.b - graphics_bg.b) * ratio)

            pygame.draw.line(self.gradient, (r, g, b), (x, 0), (x, self.screen_height))

    def _render_frame(self):
        """Render one frame"""
        with self.lock:
            is_active = self.is_active
            is_speaking = self.is_speaking
            animation_frame = self.animation_frame

        if not is_active:
            # Sleeping state - show dimmed blank screen
            dim_color = (20, 20, 20)  # Very dark gray
            self.screen.fill(dim_color)
            pygame.display.flip()
            return

        # Awake state - show normal UI
        # Parse colors
        graphics_bg = pygame.Color(self.config['colors']['graphics_bg'])
        transcript_bg = pygame.Color(self.config['colors']['transcript_bg'])

        # Clear graphics area (left pane)
        self.screen.fill(graphics_bg, (0, 0, self.pane_width, self.screen_height))

        # Draw gradient FIRST so sprite renders on top
        self.screen.blit(self.gradient, (self.gradient_start, 0))

        # Clear transcript area (right pane)
        self.screen.fill(transcript_bg, (self.pane_width, 0, self.transcript_width, self.screen_height))

        # Draw sprite in left half (renders on top of gradient)
        if is_speaking:
            # Animate through ping-pong frames
            frame_idx = self.ping_pong_frames[animation_frame]
            self.screen.blit(self.speaking_frames[frame_idx], (0, 0))
        else:
            self.screen.blit(self.idle_sprite, (0, 0))

        # Render transcripts
        self._render_transcripts()

        pygame.display.flip()

    def _render_transcripts(self):
        """Render transcript text in right half with scrolling"""
        with self.lock:
            if not self.transcripts:
                return

            # Make a copy of transcripts for rendering
            transcripts_copy = list(self.transcripts)

        # Parse colors
        choco_color = pygame.Color(self.config['colors']['choco_text'])
        user_color = pygame.Color(self.config['colors']['user_text'])

        # Start from bottom and work up
        y = self.screen_height - self.transcript_margin
        line_height = self.config['font_size'] + 6  # 6px line spacing

        # Render transcripts from most recent backwards
        for speaker, text in reversed(transcripts_copy):
            # Choose color and prefix based on speaker
            if speaker == "user":
                color = user_color
                prefix = "You: "
            else:
                color = choco_color
                prefix = "Choco: "

            # Word wrap text to fit transcript width minus margins
            max_width = self.transcript_width - (self.transcript_margin * 2)
            wrapped_lines = self._wrap_text(prefix + text, max_width)

            # Render lines from bottom up
            for line in reversed(wrapped_lines):
                text_surface = self.font.render(line, True, color)

                # Check if we're out of space at top
                if y - text_surface.get_height() < 0:
                    return

                # Draw text
                self.screen.blit(text_surface, (self.pane_width + self.transcript_margin, y - text_surface.get_height()))
                y -= line_height

    def _wrap_text(self, text, max_width):
        """Wrap text to fit within max_width pixels"""
        words = text.split(' ')
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            test_surface = self.font.render(test_line, True, (255, 255, 255))

            if test_surface.get_width() <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

        return lines

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
        print("🎬 Display thread starting...")

        # On Linux/Pi, initialize pygame in this thread (EGL context requirement)
        # On macOS, pygame was already initialized on main thread
        if not IS_MACOS:
            if not self._init_pygame():
                print("❌ Display initialization failed")
                return

        self.running = True
        clock = pygame.time.Clock()
        frame_count = 0

        print("🔄 Display loop starting...")
        try:
            while self.running:
                # Handle pygame events (on Linux/Pi only - macOS requires main thread)
                if not IS_MACOS:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            self.running = False

                # Update animation
                self._update_animation()

                # Render frame
                self._render_frame()

                # Variable FPS: 30 when awake, 1 when sleeping
                with self.lock:
                    fps = 30 if self.is_active else 1
                clock.tick(fps)

                frame_count += 1
                if frame_count == 1:
                    print("✅ First frame rendered")
                elif frame_count % 300 == 0:  # Every 10 seconds
                    print(f"🎬 Display running... {frame_count} frames rendered")

        finally:
            print("🛑 Display loop ending")
            if not IS_MACOS:
                pygame.quit()

    def start(self):
        """Start the display (pygame init on main thread for macOS, worker thread for Pi)"""
        if self.thread is not None:
            print("⚠️  Display thread already running")
            return

        # On macOS, initialize pygame on main thread (required for Cocoa)
        # On Pi/Linux, init happens in worker thread (required for EGL context)
        if IS_MACOS:
            print("🎬 Initializing pygame on main thread (macOS)...")
            if not self._init_pygame():
                print("❌ Display initialization failed")
                return

        print("🚀 Starting display thread...")
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        time.sleep(0.5)  # Give it time to initialize
        print("✅ Display thread launched")

    def stop(self):
        """Stop the display (must be called from main thread on macOS)"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None

        # On macOS, quit pygame on main thread
        if IS_MACOS:
            pygame.quit()

    def set_active(self, active):
        """Set display active state (True = awake, False = sleeping)"""
        with self.lock:
            self.is_active = active
            if not active:
                # Clear transcripts when going to sleep
                self.transcripts = []
                self.is_speaking = False

    def set_speaking(self, speaking):
        """Update speaking state (thread-safe)"""
        with self.lock:
            was_speaking = self.is_speaking
            self.is_speaking = speaking
            if speaking and not was_speaking:
                self.animation_frame = 0  # Reset animation
                self.last_frame_time = time.time()  # Reset timer
                print("🎬 Animation started")

    def add_transcript(self, speaker, text):
        """Add a transcript line (thread-safe)"""
        with self.lock:
            # Replace newlines with spaces since we do our own word wrapping
            filtered_text = text.replace('\n', ' ').replace('\r', ' ')
            self.transcripts.append((speaker, filtered_text))
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
