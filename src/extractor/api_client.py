"""
Terabox API client for making authenticated requests.
"""
import asyncio
import json
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode, quote
import logging
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .token_manager import TokenManager

logger = logging.getLogger(__name__)


class TeraboxAPIError(Exception):
    """Custom exception for Terabox API errors."""
    def __init__(self, message: str, errno: int = -1, response: Optional[Dict] = None):
        super().__init__(message)
        self.errno = errno
        self.response = response


class TeraboxAPIClient:
    """
    Low-level API client for Terabox.
    Handles all HTTP communication with proper authentication.
    """
    
    BASE_DOMAINS = [
        "www.terabox.com",
        "terabox.com",
        "www.teraboxapp.com",
        "www.1024tera.com",
    ]
    
    def __init__(self, token_manager: TokenManager, timeout: int = 30):
        self.token_manager = token_manager
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._current_domain_idx = 0
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._http_session is None or self._http_session.closed:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                ssl=False,  # Handle SSL verification manually
            )
            self._http_session = aiohttp.ClientSession(
                connector=connector,
                timeout=self.timeout,
            )
        return self._http_session
    
    async def close(self):
        """Close the HTTP session."""
        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
    
    @property
    def current_domain(self) -> str:
        """Get current active domain."""
        return self.BASE_DOMAINS[self._current_domain_idx]
    
    def _rotate_domain(self):
        """Rotate to next domain on failure."""
        self._current_domain_idx = (self._current_domain_idx + 1) % len(self.BASE_DOMAINS)
        logger.info(f"Rotated to domain: {self.current_domain}")
    
    async def _ensure_session(self):
        """Ensure we have valid session data."""
        session = await self._get_session()
        await self.token_manager.refresh_if_needed(session)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        referer: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated API request."""
        await self._ensure_session()
        session = await self._get_session()
        
        url = f"https://{self.current_domain}{endpoint}"
        
        # Build headers
        request_headers = self.token_manager.get_api_headers(referer)
        if headers:
            request_headers.update(headers)
        
        # Add cookies
        request_headers["Cookie"] = self.token_manager.get_cookie_string()
        
        # Add common params
        if params is None:
            params = {}
        
        session_data = self.token_manager.get_session_data()
        if session_data:
            params.setdefault("channel", "chunlei")
            params.setdefault("web", "1")
            params.setdefault("app_id", "250528")
            params.setdefault("clienttype", "0")
            if session_data.logid:
                params.setdefault("dp-logid", session_data.logid)
        
        logger.debug(f"Request: {method} {url}")
        logger.debug(f"Params: {params}")
        
        try:
            async with session.request(
                method,
                url,
                params=params,
                data=data,
                headers=request_headers,
                allow_redirects=True,
            ) as response:
                # Update cookies from response
                for cookie in response.cookies.values():
                    if session_data:
                        session_data.cookies[cookie.key] = cookie.value
                
                content_type = response.headers.get("Content-Type", "")
                
                if "application/json" in content_type or "text/json" in content_type:
                    result = await response.json()
                else:
                    text = await response.text()
                    # Try to parse as JSON anyway
                    try:
                        result = json.loads(text)
                    except json.JSONDecodeError:
                        # Check for redirect or error pages
                        if response.status >= 400:
                            raise TeraboxAPIError(f"HTTP {response.status}: {text[:200]}")
                        result = {"raw_html": text}
                
                # Check for API errors
                if isinstance(result, dict):
                    errno = result.get("errno", 0)
                    if errno != 0:
                        error_msg = result.get("errmsg", result.get("show_msg", f"Unknown error: {errno}"))
                        
                        # Handle specific errors
                        if errno in [-6, -9, 2]:  # Cookie/session errors
                            logger.warning(f"Session error (errno={errno}), refreshing...")
                            session = await self._get_session()
                            await self.token_manager.initialize_session(session)
                            raise TeraboxAPIError(error_msg, errno, result)
                        
                        if errno == 112:  # Need captcha/verification
                            self._rotate_domain()
                            raise TeraboxAPIError("Captcha required, rotating domain", errno, result)
                        
                        logger.error(f"API error: {error_msg} (errno={errno})")
                        raise TeraboxAPIError(error_msg, errno, result)
                
                return result
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error: {e}")
            self._rotate_domain()
            raise
    
    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make GET request."""
        return await self._request("GET", endpoint, params=params, **kwargs)
    
    async def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Make POST request."""
        return await self._request("POST", endpoint, params=params, data=data, **kwargs)
    
    async def fetch_page(self, url: str) -> str:
        """Fetch a page and return HTML content."""
        await self._ensure_session()
        session = await self._get_session()
        
        headers = self.token_manager.get_default_headers()
        headers["Cookie"] = self.token_manager.get_cookie_string()
        
        async with session.get(url, headers=headers, allow_redirects=True) as response:
            # Update cookies
            session_data = self.token_manager.get_session_data()
            for cookie in response.cookies.values():
                if session_data:
                    session_data.cookies[cookie.key] = cookie.value
            
            return await response.text()
