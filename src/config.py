"""
Configuration management for the Terabox extractor bot.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration."""
    
    # Telegram
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    
    # Webhook settings (for Render)
    webhook_url: str = field(default_factory=lambda: os.getenv("RENDER_EXTERNAL_URL", ""))
    port: int = int(os.getenv("PORT", "10000"))
    
    # HTTP Settings
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    
    # Cookie/Token Settings
    cookie_refresh_interval: int = int(os.getenv("COOKIE_REFRESH_INTERVAL", "3600"))
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    @property
    def is_render(self) -> bool:
        """Check if running on Render."""
        return bool(self.webhook_url)
    
    def validate(self) -> bool:
        """Validate required configuration."""
        if not self.bot_token:
            raise ValueError("BOT_TOKEN is required")
        return True


config = Config()
