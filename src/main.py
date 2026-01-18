#!/usr/bin/env python3
"""
Terabox Extractor Bot - Main Entry Point
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import config
from src.telegram.bot import TeraboxBot


def setup_logging():
    """Configure logging."""
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)


def main():
    """Main entry point."""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 50)
    logger.info("Starting Terabox Extractor Bot")
    logger.info("=" * 50)
    
    if config.is_render:
        logger.info(f"Platform: Render")
        logger.info(f"Webhook URL: {config.webhook_url}")
        logger.info(f"Port: {config.port}")
    else:
        logger.info("Platform: Local (Polling Mode)")
    
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Config error: {e}")
        sys.exit(1)
    
    bot = TeraboxBot()
    
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
