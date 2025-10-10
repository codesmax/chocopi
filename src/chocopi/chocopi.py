"""Main orchestrator for ChocoPi voice assistant"""
import asyncio
import signal
import logging
from chocopi.config import CONFIG
from chocopi.audio import AUDIO
from chocopi.wakeword import WakeWordDetector
from chocopi.conversation import ConversationSession
from chocopi.display import create_display_manager

logger = logging.getLogger(__name__)


class ChocoPi:
    def __init__(self):
        self.wake_word_detector = WakeWordDetector()
        self.wake_words = [lang_config['wake_word'].lower() for lang_config in CONFIG['languages'].values()]
        self.display = create_display_manager(CONFIG)

    def _wake_word_language(self, wake_word):
        """Get language configuration based on detected wake word"""
        for lang, config in CONFIG['languages'].items():
            if wake_word == config['model'] and lang != CONFIG['native_language']:
                logger.info("⚙️  Session configured for: %s", config['language_name'])
                return lang

        default_lang = list(CONFIG['languages'].keys())[0]
        logger.error("⚠️  Unknown wake word: '%s'. Using default language: %s", wake_word, default_lang)

        return default_lang

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals by raising SystemExit"""
        logger.info("\n🛑 Received signal %s, shutting down gracefully...", signum)
        raise SystemExit(0)

    def run(self):
        """Run the main application loop"""
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info("✨ Choco is ready! Say one of '%s' to start or end a conversation.", ', '.join(self.wake_words))

        # Start display if enabled
        if self.display:
            self.display.start()

        try:
            while True:
                # Listen for wake word (blocking)
                wake_word = self.wake_word_detector.listen()
                lang = self._wake_word_language(wake_word)

                # Wake up display
                if self.display:
                    self.display.set_active(True)

                AUDIO.start_playing(CONFIG['sounds']['awake'])

                # Run conversation session
                session = ConversationSession(lang, display=self.display)
                asyncio.run(session.run())

                AUDIO.start_playing(CONFIG['sounds']['bye'])
                logger.info("✅ Session ended.\n")

                # Put display to sleep
                if self.display:
                    self.display.set_active(False)

        except (KeyboardInterrupt, SystemExit):
            logger.info("\n👋 Shutting down...")
        except Exception as e:
            logger.error("\n❌ Unexpected error: %s", e)
        finally:
            logger.info("🧹 Cleaning up...")
            if self.display:
                self.display.stop()


def main():
    app = ChocoPi()
    app.run()

if __name__ == '__main__':
    main()
