"""
Helper utility functions.
"""
import re
from typing import Optional


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes <= 0:
        return "Unknown"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max length."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def escape_markdown(text: str, version: int = 2) -> str:
    """Escape special characters for Telegram markdown."""
    if version == 2:
        # MarkdownV2 special characters
        special_chars = r'\_*[]()~`>#+-=|{}.!'
        return re.sub(f'([{re.escape(special_chars)}])', r'\\\1', text)
    else:
        # Original Markdown
        special_chars = r'_*`['
        return re.sub(f'([{re.escape(special_chars)}])', r'\\\1', text)


def parse_resolution(width: int, height: int) -> str:
    """Get resolution label from dimensions."""
    if height >= 2160:
        return "4K UHD"
    elif height >= 1440:
        return "2K QHD"
    elif height >= 1080:
        return "1080p FHD"
    elif height >= 720:
        return "720p HD"
    elif height >= 480:
        return "480p SD"
    elif height >= 360:
        return "360p"
    else:
        return f"{width}x{height}"


def format_duration(seconds: int) -> str:
    """Format seconds to HH:MM:SS."""
    if seconds <= 0:
        return "Unknown"
    
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"
