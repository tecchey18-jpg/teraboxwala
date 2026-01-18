"""
Token and cookie management for Terabox API.
Handles session management, CSRF tokens, and cookie refresh.
"""
import asyncio
import time
import re
import hashlib
import random
import string
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, field
import logging
import aiohttp
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)


@dataclass
class SessionData:
    """Holds session-related data."""
    cookies: Dict[str, str] = field(default_factory=dict)
    js_token: Optional[str] = None
    bdstoken: Optional[str] = None
    csrf_token: Optional[str] = None
    logid: Optional[str] = None
    timestamp: int = 0
    expires: int = 0
    user_agent: str = ""
    
    def is_expired(self) -> bool:
        """Check if session is expired."""
        return time.time() > self.expires if self.expires else True


class TokenManager:
    """
    Manages authentication tokens, cookies, and session data for Terabox.
    """
    
    def __init__(self, refresh_interval: int = 3600):
        self.refresh_interval = refresh_interval
        self._session_data: Optional[SessionData] = None
        self._lock = asyncio.Lock()
        self._ua = UserAgent(browsers=['chrome', 'edge'])
        
    def _generate_logid(self) -> str:
        """Generate a dplogid like Terabox does."""
        timestamp = int(time.time() * 1000)
        random_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"{timestamp}{random_str}"
    
    def _generate_device_id(self) -> str:
        """Generate a device fingerprint ID."""
        chars = string.ascii_letters + string.digits
        return ''.join(random.choices(chars, k=32))
    
    def _generate_browser_id(self) -> str:
        """Generate browser ID similar to Terabox's fingerprinting."""
        base = f"{time.time()}{random.random()}"
        return hashlib.md5(base.encode()).hexdigest()[:24]
    
    def get_user_agent(self) -> str:
        """Get a realistic user agent."""
        try:
            return self._ua.chrome
        except:
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    
    def get_default_headers(self) -> Dict[str, str]:
        """Get default request headers that mimic a real browser."""
        ua = self.get_user_agent()
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Cache-Control": "max-age=0",
        }
    
    def get_api_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "User-Agent": self._session_data.user_agent if self._session_data else self.get_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Requested-With": "XMLHttpRequest",
        }
        
        if referer:
            headers["Referer"] = referer
            headers["Origin"] = "/".join(referer.split("/")[:3])
        
        return headers
    
    async def initialize_session(self, http_client: aiohttp.ClientSession) -> SessionData:
        """Initialize a fresh session with Terabox."""
        async with self._lock:
            if self._session_data and not self._session_data.is_expired():
                return self._session_data
            
            logger.info("Initializing new Terabox session...")
            
            session_data = SessionData(
                user_agent=self.get_user_agent(),
                timestamp=int(time.time()),
                expires=int(time.time()) + self.refresh_interval,
                logid=self._generate_logid(),
            )
            
            # Initial cookies to set
            session_data.cookies = {
                "lang": "en",
                "ndus": self._generate_device_id(),
                "browserid": self._generate_browser_id(),
                "__bid_n": self._generate_browser_id()[:16],
            }
            
            try:
                # Fetch the main page to get additional cookies and tokens
                headers = self.get_default_headers()
                headers["User-Agent"] = session_data.user_agent
                
                async with http_client.get(
                    "https://www.terabox.com",
                    headers=headers,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    # Extract cookies from response
                    for cookie in response.cookies.values():
                        session_data.cookies[cookie.key] = cookie.value
                    
                    html = await response.text()
                    
                    # Extract tokens from HTML
                    session_data.js_token = self._extract_js_token(html)
                    session_data.bdstoken = self._extract_bdstoken(html)
                    session_data.csrf_token = session_data.cookies.get("csrfToken")
                    
                    logger.info(f"Session initialized. Cookies: {list(session_data.cookies.keys())}")
                    
            except Exception as e:
                logger.error(f"Failed to initialize session: {e}")
            
            self._session_data = session_data
            return session_data
    
    def _extract_js_token(self, html: str) -> Optional[str]:
        """Extract jsToken from HTML content."""
        patterns = [
            r'"jsToken"\s*:\s*"([^"]+)"',
            r"jsToken\s*=\s*'([^']+)'",
            r"jsToken\s*=\s*\"([^\"]+)\"",
            r"window\.jsToken\s*=\s*['\"]([^'\"]+)['\"]",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return None
    
    def _extract_bdstoken(self, html: str) -> Optional[str]:
        """Extract bdstoken from HTML content."""
        patterns = [
            r'"bdstoken"\s*:\s*"([^"]+)"',
            r"bdstoken\s*=\s*['\"]([^'\"]+)['\"]",
            r"'bdstoken'\s*:\s*'([^']+)'",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return None
    
    def get_cookies(self) -> Dict[str, str]:
        """Get current session cookies."""
        if self._session_data:
            return self._session_data.cookies.copy()
        return {}
    
    def get_cookie_string(self) -> str:
        """Get cookies as a string for Cookie header."""
        cookies = self.get_cookies()
        return "; ".join(f"{k}={v}" for k, v in cookies.items())
    
    async def refresh_if_needed(self, http_client: aiohttp.ClientSession) -> SessionData:
        """Refresh session if expired."""
        if not self._session_data or self._session_data.is_expired():
            return await self.initialize_session(http_client)
        return self._session_data
    
    def get_session_data(self) -> Optional[SessionData]:
        """Get current session data."""
        return self._session_data
    
    def generate_sign(self, timestamp: int, share_id: str) -> str:
        """Generate request signature."""
        # Terabox sign generation algorithm (reverse-engineered)
        sign_str = f"{share_id}_{timestamp}"
        return hashlib.md5(sign_str.encode()).hexdigest()
