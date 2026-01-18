"""
Main Telegram bot implementation.
"""
import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from ..config import config
from ..extractor.terabox import TeraboxExtractor
from ..extractor.token_manager import TokenManager
from .handlers import setup_handlers

logger = logging.getLogger(__name__)


class TeraboxBot:
    """Main bot class managing the Telegram interface."""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or config.bot_token
        
        if not self.token:
            raise ValueError("Bot token is required")
        
        # Initialize bot with HTML parse mode
        self.bot = Bot(
            token=self.token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=True,
            )
        )
        
        self.dp = Dispatcher()
        
        # Initialize extractor components
        self.token_manager = TokenManager(
            refresh_interval=config.cookie_refresh_interval
        )
        self.extractor = TeraboxExtractor(
            token_manager=self.token_manager,
            timeout=config.request_timeout
        )
        
        # Setup handlers
        setup_handlers(self.dp, self.extractor)
        
        logger.info("TeraboxBot initialized")
    
    async def start(self):
        """Start the bot polling."""
        logger.info("Starting bot...")
        
        try:
            # Initialize session before starting
            import aiohttp
            async with aiohttp.ClientSession() as session:
                await self.token_manager.initialize_session(session)
            
            await self.dp.start_polling(
                self.bot,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
            )
        except asyncio.CancelledError:
            logger.info("Bot polling cancelled")
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the bot and cleanup."""
        logger.info("Stopping bot...")
        await self.extractor.close()
        await self.bot.session.close()
        logger.info("Bot stopped")
    
    def run(self):
        """Run the bot synchronously."""
        try:
            asyncio.run(self.start())
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user")
