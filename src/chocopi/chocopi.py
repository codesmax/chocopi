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

    async def run(self):
        """Run the main application loop"""
        logger.info("✨ Choco is ready! Say one of '%s' to start or end a conversation.", ', '.join(self.wake_words))

        # Start display task if enabled
        display_task = None
        if self.display:
            display_task = asyncio.create_task(self.display.run())

        try:
            while True:
                # Listen for wake word
                wake_word = await self.wake_word_detector.listen()
                lang = self._wake_word_language(wake_word)

                # Wake up display
                if self.display:
                    self.display.set_active(True)

                AUDIO.start_playing(CONFIG['sounds']['awake'], blocking=True)

                # Run conversation session
                session = ConversationSession(lang, display=self.display)
                await session.run()

                AUDIO.start_playing(CONFIG['sounds']['bye'], blocking=True)
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
            if display_task:
                self.display.is_running = False
                display_task.cancel()
                try:
                    await display_task
                except asyncio.CancelledError:
                    pass


def main():
    app = ChocoPi()

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, app._signal_handler)
    signal.signal(signal.SIGINT, app._signal_handler)

    asyncio.run(app.run())

if __name__ == '__main__':
    main()
