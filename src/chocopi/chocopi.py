"""Main orchestrator for ChocoPi voice assistant"""
import asyncio
import signal
from chocopi.config import CONFIG
from chocopi.audio import AUDIO
from chocopi.wakeword import WakeWordDetector
from chocopi.conversation import ConversationSession
from chocopi.display import create_display_manager


class ChocoPi:
    def __init__(self):
        self.wake_word_detector = WakeWordDetector()
        self.wake_words = [lang_config['wake_word'].lower() for lang_config in CONFIG['languages'].values()]
        self.display = create_display_manager(CONFIG)

    def _get_wake_word_language(self, wake_word):
        """Get language configuration based on detected wake word"""
        for lang, config in CONFIG['languages'].items():
            if wake_word == config['model'] and lang != CONFIG['native_language']:
                print(f"⚙️  Session configured for: {config['language_name']}")
                return lang

        default_lang = list(CONFIG['languages'].keys())[0]
        print(f"⚠️  Unknown wake word: '{wake_word}'. Using default language: {default_lang}")

        return default_lang

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals by raising SystemExit"""
        print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
        raise SystemExit(0)

    def run(self):
        """Run the main application loop"""
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        print(f"✨ Choco is ready! Say one of '{', '.join(self.wake_words)}' to start or end a conversation.")

        # Start display if enabled
        if self.display:
            self.display.start()

        try:
            while True:
                # Listen for wake word (blocking)
                wake_word = self.wake_word_detector.listen_for_wake_word()
                lang = self._get_wake_word_language(wake_word)

                # Wake up display
                if self.display:
                    self.display.set_active(True)

                AUDIO.start_playing(CONFIG['sounds']['awake'])

                # Run conversation session
                session = ConversationSession(lang, display_manager=self.display)
                asyncio.run(session.run())

                AUDIO.start_playing(CONFIG['sounds']['bye'])
                print("✅ Session ended.\n")

                # Put display to sleep
                if self.display:
                    self.display.set_active(False)

        except (KeyboardInterrupt, SystemExit):
            print("\n👋 Shutting down...")
        except Exception as e:
            print(f"\n❌ Unexpected error: {e}")
        finally:
            print("🧹 Cleaning up...")
            if self.display:
                self.display.stop()


def main():
    app = ChocoPi()
    app.run()

if __name__ == '__main__':
    main()
