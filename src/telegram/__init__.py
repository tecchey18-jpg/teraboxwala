"""Telegram bot module."""
from .bot import TeraboxBot
from .handlers import setup_handlers

__all__ = ["TeraboxBot", "setup_handlers"]
