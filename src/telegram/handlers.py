"""
Telegram bot message handlers.
"""
import asyncio
import logging
import re
from typing import Optional

from aiogram import Router, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.exceptions import TelegramBadRequest

from ..extractor.terabox import TeraboxExtractor, VideoInfo, TeraboxAPIError
from ..domains.resolver import DomainResolver
from ..utils.helpers import format_size, escape_markdown, truncate_text

logger = logging.getLogger(__name__)

router = Router()

# Store extractor reference
_extractor: Optional[TeraboxExtractor] = None


def setup_handlers(dp: Dispatcher, extractor: TeraboxExtractor):
    """Setup all message handlers."""
    global _extractor
    _extractor = extractor
    dp.include_router(router)


@router.message(CommandStart())
async def start_handler(message: Message):
    """Handle /start command."""
    welcome_text = """
🎬 <b>Terabox Video Extractor Bot</b>

Send me any Terabox link and I'll extract the direct video URL for you!

<b>Supported domains:</b>
• terabox.com
• teraboxapp.com  
• 1024tera.com
• 4funbox.co
• mirrobox.com
• nephobox.com
• momerybox.com
• tibibox.com
• freeterabox.com
• And many more mirrors!

<b>How to use:</b>
Just send me a Terabox share link and I'll do the rest!

Example: <code>https://terabox.com/s/xxxxx</code>
    """
    await message.answer(welcome_text)


@router.message(Command("help"))
async def help_handler(message: Message):
    """Handle /help command."""
    help_text = """
📖 <b>Help & Commands</b>

<b>/start</b> - Start the bot
<b>/help</b> - Show this help message
<b>/ping</b> - Check if bot is alive

<b>Usage:</b>
Simply send any Terabox link to extract the video.

<b>Supported link formats:</b>
• https://terabox.com/s/xxxxx
• https://www.terabox.com/sharing/link?surl=xxxxx  
• https://1024tera.com/s/xxxxx
• Any other Terabox mirror domain

<b>What you'll get:</b>
• 📹 Direct playable video URL
• 📊 File size information
• 🎞 Resolution (if available)
• ⬇️ Option to send video directly (if under 50MB)

<b>Note:</b>
Large files may take longer to process. Please be patient!
    """
    await message.answer(help_text)


@router.message(Command("ping"))
async def ping_handler(message: Message):
    """Handle /ping command."""
    await message.answer("🏓 Pong! Bot is alive and running.")


@router.message(F.text)
async def link_handler(message: Message):
    """Handle Terabox links."""
    if not message.text:
        return
    
    text = message.text.strip()
    
    # Check if it's a Terabox URL
    if not DomainResolver.is_terabox_url(text):
        # Check if message contains a URL
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, text)
        
        terabox_urls = [url for url in urls if DomainResolver.is_terabox_url(url)]
        
        if not terabox_urls:
            # Not a Terabox URL, ignore or send help
            if text.startswith(('http://', 'https://')):
                await message.answer(
                    "❌ This doesn't appear to be a Terabox link.\n"
                    "Please send a valid Terabox share URL."
                )
            return
        
        text = terabox_urls[0]
    
    # Send processing message
    processing_msg = await message.answer("⏳ <i>Processing your link...</i>")
    
    try:
        if _extractor is None:
            await processing_msg.edit_text("❌ Bot is not properly initialized. Please try again later.")
            return
        
        # Extract video info
        video_info = await _extractor.extract(text)
        
        # Format response
        response = format_video_response(video_info)
        
        # Create keyboard with buttons
        keyboard = create_video_keyboard(video_info)
        
        # Send response
        await processing_msg.edit_text(
            response,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        
        # Try to send video directly if small enough (Telegram limit: 50MB)
        if video_info.stream_url and video_info.size > 0 and video_info.size <= 50 * 1024 * 1024:
            try:
                await message.answer("📤 <i>Attempting to send video directly...</i>")
                await send_video_directly(message, video_info)
            except Exception as e:
                logger.warning(f"Could not send video directly: {e}")
                await message.answer(
                    "ℹ️ Could not send video directly. Please use the link above to download/stream."
                )
        
    except TeraboxAPIError as e:
        error_msg = f"❌ <b>Extraction failed:</b>\n{e}"
        await processing_msg.edit_text(error_msg)
        logger.error(f"Extraction error for {text}: {e}")
        
    except asyncio.TimeoutError:
        await processing_msg.edit_text(
            "⏱ <b>Request timed out.</b>\n"
            "The server might be slow. Please try again later."
        )
        
    except Exception as e:
        await processing_msg.edit_text(
            f"❌ <b>An error occurred:</b>\n{type(e).__name__}: {str(e)[:200]}"
        )
        logger.exception(f"Unexpected error for {text}")


def format_video_response(video_info: VideoInfo) -> str:
    """Format video info into a nice message."""
    parts = ["✅ <b>Video Extracted Successfully!</b>\n"]
    
    # Title/Filename
    title = truncate_text(video_info.title or video_info.filename, 100)
    parts.append(f"📹 <b>Title:</b> <code>{title}</code>")
    
    # File size
    if video_info.size > 0:
        size_str = format_size(video_info.size)
        parts.append(f"📊 <b>Size:</b> {size_str}")
    
    # Resolution
    if video_info.resolution:
        parts.append(f"🎞 <b>Resolution:</b> {video_info.resolution}")
    
    # Add separator
    parts.append("")
    
    # Stream URL (main output)
    if video_info.stream_url:
        parts.append("🔗 <b>Direct Stream URL:</b>")
        # Truncate very long URLs for display but include full URL
        display_url = truncate_text(video_info.stream_url, 500)
        parts.append(f"<code>{display_url}</code>")
    
    # Download URL if different
    if video_info.download_url and video_info.download_url != video_info.stream_url:
        parts.append("")
        parts.append("⬇️ <b>Download URL:</b>")
        parts.append(f"<code>{truncate_text(video_info.download_url, 500)}</code>")
    
    return "\n".join(parts)


def create_video_keyboard(video_info: VideoInfo) -> InlineKeyboardMarkup:
    """Create inline keyboard with action buttons."""
    buttons = []
    
    # Stream button
    if video_info.stream_url:
        buttons.append([
            InlineKeyboardButton(
                text="▶️ Open Stream URL",
                url=video_info.stream_url[:2048]  # Telegram URL limit
            )
        ])
    
    # Download button (if different from stream)
    if video_info.download_url and video_info.download_url != video_info.stream_url:
        buttons.append([
            InlineKeyboardButton(
                text="⬇️ Download",
                url=video_info.download_url[:2048]
            )
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_video_directly(message: Message, video_info: VideoInfo):
    """Attempt to send video directly via Telegram."""
    try:
        if not video_info.stream_url:
            return
        
        caption = f"📹 {truncate_text(video_info.title, 200)}"
        if video_info.size > 0:
            caption += f"\n📊 {format_size(video_info.size)}"
        
        await message.answer_video(
            video=video_info.stream_url,
            caption=caption,
            supports_streaming=True,
            read_timeout=120,
            write_timeout=120,
        )
        
    except TelegramBadRequest as e:
        if "file is too big" in str(e).lower():
            raise Exception("File too large for direct Telegram upload")
        raise
