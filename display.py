import os
import platform
import time
import pygame

class DisplayManager:
    """Manages visual display with sprite animations and transcript"""

    def __init__(self, config):
        self.config = config['display']
        self.script_path = os.path.dirname(os.path.realpath(__file__))
        self.images_path = os.path.join(self.script_path, 'images')
        self.fonts_path = os.path.join(self.script_path, 'fonts')

        # State
        self.is_active = False  # False = sleeping (dimmed), True = awake
        self.is_speaking = False
        self.transcripts = []  # List of (speaker, text) tuples

        # Animation
        self.animation_frame = 0
        self.ping_pong_frames = [0, 1, 2, 3, 2, 1]  # Ping-pong pattern
        self.last_frame_time = 0

        # Pygame surfaces (initialized on start)
        self.screen = None
        self.idle_sprite = None
        self.speaking_frames = []
        self.font = None
        self.gradient = None
        self.initialized = False

    def _init_pygame(self):
        """Initialize pygame in the display thread"""
        try:
            pygame.init()

            # Check if display is available
            if not pygame.display.get_driver():
                print("⚠️  No display available, disabling visual output")
                return False

            # Set up full-screen display on Linux/Pi
            is_pi = platform.machine().lower() in ['aarch64', 'armv7l']
            self.screen = pygame.display.set_mode(
                (self.config['width'], self.config['height']),
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
        """Load idle and speaking sprites (images should be pre-sized to 400x480)"""
        # Load idle sprite - use smoothscale for better quality
        idle_path = os.path.join(self.images_path, 'choco.png')
        idle_img = pygame.image.load(idle_path)
        self.idle_sprite = pygame.transform.smoothscale(idle_img, (400, 480))

        # Load speaking spritesheet (horizontal layout: 4 frames)
        speaking_path = os.path.join(self.images_path, 'choco-speaking.png')
        spritesheet = pygame.image.load(speaking_path)

        # Split into 4 frames - use smoothscale for better quality
        frame_width = spritesheet.get_width() // 4
        frame_height = spritesheet.get_height()

        for i in range(4):
            frame = spritesheet.subsurface((i * frame_width, 0, frame_width, frame_height))
            scaled_frame = pygame.transform.smoothscale(frame, (400, 480))
            self.speaking_frames.append(scaled_frame)

    def _create_gradient(self):
        """Create gradient surface for smooth transition between panes"""
        gradient_width = 200  # Width of gradient (x=200 to x=400)
        self.gradient = pygame.Surface((gradient_width, 480), pygame.SRCALPHA)

        # Get pane colors
        graphics_bg = pygame.Color(self.config['colors']['graphics_bg'])
        transcript_bg = pygame.Color(self.config['colors']['transcript_bg'])

        # Create vertical gradient from graphics_bg to transcript_bg
        for x in range(gradient_width):
            # Interpolate between colors
            ratio = x / gradient_width
            r = int(graphics_bg.r + (transcript_bg.r - graphics_bg.r) * ratio)
            g = int(graphics_bg.g + (transcript_bg.g - graphics_bg.g) * ratio)
            b = int(graphics_bg.b + (transcript_bg.b - graphics_bg.b) * ratio)

            pygame.draw.line(self.gradient, (r, g, b), (x, 0), (x, 480))

    def _render_frame(self):
        """Render one frame"""
        if not self.is_active:
            # Sleeping state - show dimmed blank screen
            dim_color = (20, 20, 20)  # Very dark gray
            self.screen.fill(dim_color)
            pygame.display.flip()
            return

        # Awake state - show normal UI
        # Parse colors
        graphics_bg = pygame.Color(self.config['colors']['graphics_bg'])
        transcript_bg = pygame.Color(self.config['colors']['transcript_bg'])

        # Clear graphics area (left half: 400x480)
        self.screen.fill(graphics_bg, (0, 0, 400, 480))

        # Draw gradient FIRST (x=200 to x=400) so sprite renders on top
        self.screen.blit(self.gradient, (200, 0))

        # Clear transcript area (right half: 400x480)
        self.screen.fill(transcript_bg, (400, 0, 400, 480))

        # Draw sprite in left half (renders on top of gradient)
        if self.is_speaking:
            # Animate through ping-pong frames
            frame_idx = self.ping_pong_frames[self.animation_frame]
            self.screen.blit(self.speaking_frames[frame_idx], (0, 0))
        else:
            self.screen.blit(self.idle_sprite, (0, 0))

        # Render transcripts
        self._render_transcripts()

        pygame.display.flip()

    def _render_transcripts(self):
        """Render transcript text in right half with scrolling"""
        if not self.transcripts:
            return

        # Parse colors
        choco_color = pygame.Color(self.config['colors']['choco_text'])
        user_color = pygame.Color(self.config['colors']['user_text'])

        # Start from bottom and work up
        y = 480 - 10  # 10px bottom margin
        line_height = self.config['font_size'] + 6  # 6px line spacing
        margin = 10

        # Render transcripts from most recent backwards
        for speaker, text in reversed(self.transcripts):
            # Choose color and prefix based on speaker
            if speaker == "user":
                color = user_color
                prefix = "You: "
            else:
                color = choco_color
                prefix = "Choco: "

            # Word wrap text to fit in 380px width (400 - 20px margins)
            wrapped_lines = self._wrap_text(prefix + text, 380)

            # Render lines from bottom up
            for line in reversed(wrapped_lines):
                text_surface = self.font.render(line, True, color)

                # Check if we're out of space at top
                if y - text_surface.get_height() < 0:
                    return

                # Draw text
                self.screen.blit(text_surface, (400 + margin, y - text_surface.get_height()))
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
            if self.is_speaking:
                # Advance ping-pong frame
                self.animation_frame = (self.animation_frame + 1) % len(self.ping_pong_frames)
            self.last_frame_time = current_time

    def initialize(self):
        """Initialize pygame and display (call from main thread)"""
        if self.initialized:
            return True

        if self._init_pygame():
            self.initialized = True
            return True
        return False

    def render_frame(self):
        """Render one frame (call this from event loop)"""
        if not self.initialized:
            return

        # Update animation
        self._update_animation()

        # Render frame
        self._render_frame()

    def cleanup(self):
        """Clean up pygame resources"""
        if self.initialized:
            pygame.quit()
            self.initialized = False

    def set_active(self, active):
        """Set display active state (True = awake, False = sleeping)"""
        self.is_active = active
        if not active:
            # Clear transcripts when going to sleep
            self.transcripts = []
            self.is_speaking = False

    def set_speaking(self, speaking):
        """Update speaking state"""
        was_speaking = self.is_speaking
        self.is_speaking = speaking
        if speaking and not was_speaking:
            self.animation_frame = 0  # Reset animation
            self.last_frame_time = time.time()  # Reset timer
            print("🎬 Animation started")

    def add_transcript(self, speaker, text):
        """Add a transcript line"""
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
