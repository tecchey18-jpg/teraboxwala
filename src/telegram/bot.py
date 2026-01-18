"""
Telegram bot with webhook support for Render deployment.
"""
import asyncio
import logging
import os
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from ..config import config
from ..extractor.terabox import TeraboxExtractor
from ..extractor.token_manager import TokenManager
from .handlers import setup_handlers

logger = logging.getLogger(__name__)


class TeraboxBot:
    """Main bot class with webhook support for Render."""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or config.bot_token
        
        if not self.token:
            raise ValueError("Bot token is required")
        
        # Initialize bot
        self.bot = Bot(
            token=self.token,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML,
                link_preview_is_disabled=True,
            )
        )
        
        self.dp = Dispatcher()
        
        # Initialize extractor
        self.token_manager = TokenManager(
            refresh_interval=config.cookie_refresh_interval
        )
        self.extractor = TeraboxExtractor(
            token_manager=self.token_manager,
            timeout=config.request_timeout
        )
        
        # Setup handlers
        setup_handlers(self.dp, self.extractor)
        
        # Webhook configuration
        self.webhook_path = f"/webhook/{self.token}"
        self.webhook_url = config.webhook_url
        self.port = config.port
        
        logger.info("TeraboxBot initialized")
    
    async def on_startup(self, app: web.Application):
        """Set webhook when app starts."""
        # Initialize extractor session
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await self.token_manager.initialize_session(session)
        
        # Set webhook
        if self.webhook_url:
            full_webhook_url = f"{self.webhook_url}{self.webhook_path}"
            await self.bot.set_webhook(
                url=full_webhook_url,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
            )
            logger.info(f"Webhook set: {full_webhook_url}")
    
    async def on_shutdown(self, app: web.Application):
        """Cleanup on shutdown."""
        logger.info("Shutting down...")
        await self.bot.delete_webhook()
        await self.extractor.close()
        await self.bot.session.close()
    
    async def health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint for Render."""
        return web.json_response({
            "status": "ok",
            "service": "terabox-bot"
        })
    
    async def root_handler(self, request: web.Request) -> web.Response:
        """Root endpoint."""
        return web.json_response({
            "name": "Terabox Extractor Bot",
            "status": "running",
            "version": "1.0.0"
        })
    
    def create_app(self) -> web.Application:
        """Create the web application."""
        app = web.Application()
        
        # Health check routes
        app.router.add_get("/", self.root_handler)
        app.router.add_get("/health", self.health_check)
        
        # Webhook handler
        webhook_handler = SimpleRequestHandler(
            dispatcher=self.dp,
            bot=self.bot,
        )
        webhook_handler.register(app, path=self.webhook_path)
        
        # Lifecycle handlers
        app.on_startup.append(self.on_startup)
        app.on_shutdown.append(self.on_shutdown)
        
        # Setup aiogram app
        setup_application(app, self.dp, bot=self.bot)
        
        return app
    
    def run_webhook(self):
        """Run the bot with webhook (for Render)."""
        app = self.create_app()
        logger.info(f"Starting webhook server on port {self.port}")
        web.run_app(app, host="0.0.0.0", port=self.port)
    
    async def run_polling(self):
        """Run the bot with polling (for local development)."""
        logger.info("Starting polling mode...")
        
        # Initialize session
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await self.token_manager.initialize_session(session)
        
        try:
            await self.dp.start_polling(
                self.bot,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True,
            )
        finally:
            await self.extractor.close()
            await self.bot.session.close()
    
    def run(self):
        """Run bot - auto-detect webhook or polling mode."""
        if config.is_render:
            # Running on Render - use webhooks
            logger.info("Detected Render environment - using webhooks")
            self.run_webhook()
        else:
            # Local development - use polling
            logger.info("Local environment - using polling")
            asyncio.run(self.run_polling())
