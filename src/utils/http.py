"""
HTTP utility functions and custom session management.
Provides robust HTTP handling with retry logic, SSL configuration, and proxy support.
"""
import asyncio
import ssl
import certifi
from typing import Optional, Dict, Any, Union, Callable
from functools import wraps
import logging
import aiohttp
from aiohttp import ClientSession, ClientTimeout, TCPConnector, ClientResponse
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


# Default timeout configuration
DEFAULT_TIMEOUT = ClientTimeout(
    total=60,
    connect=10,
    sock_read=30,
    sock_connect=10,
)

# Default headers that mimic a real browser
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def create_ssl_context(verify: bool = True) -> ssl.SSLContext:
    """
    Create an SSL context with proper configuration.
    
    Args:
        verify: Whether to verify SSL certificates
        
    Returns:
        Configured SSL context
    """
    if verify:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
    else:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    
    return ssl_context


def create_connector(
    limit: int = 100,
    limit_per_host: int = 30,
    ttl_dns_cache: int = 300,
    ssl_verify: bool = False,
    force_close: bool = False,
) -> TCPConnector:
    """
    Create a TCP connector with optimal settings.
    
    Args:
        limit: Total connection pool limit
        limit_per_host: Connection limit per host
        ttl_dns_cache: DNS cache TTL in seconds
        ssl_verify: Whether to verify SSL certificates
        force_close: Force close connections after each request
        
    Returns:
        Configured TCP connector
    """
    ssl_context = create_ssl_context(verify=ssl_verify)
    
    return TCPConnector(
        limit=limit,
        limit_per_host=limit_per_host,
        ttl_dns_cache=ttl_dns_cache,
        ssl=ssl_context,
        force_close=force_close,
        enable_cleanup_closed=True,
    )


async def create_session(
    timeout: Optional[ClientTimeout] = None,
    headers: Optional[Dict[str, str]] = None,
    connector: Optional[TCPConnector] = None,
    cookie_jar: Optional[aiohttp.CookieJar] = None,
    **kwargs
) -> ClientSession:
    """
    Create an aiohttp ClientSession with sensible defaults.
    
    Args:
        timeout: Request timeout configuration
        headers: Default headers for all requests
        connector: TCP connector to use
        cookie_jar: Cookie jar for session persistence
        **kwargs: Additional arguments for ClientSession
        
    Returns:
        Configured ClientSession
    """
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    
    if headers is None:
        headers = DEFAULT_HEADERS.copy()
    
    if connector is None:
        connector = create_connector()
    
    if cookie_jar is None:
        cookie_jar = aiohttp.CookieJar(unsafe=True)  # Allow cookies for IP addresses
    
    return ClientSession(
        timeout=timeout,
        headers=headers,
        connector=connector,
        cookie_jar=cookie_jar,
        **kwargs
    )


class HTTPClient:
    """
    Managed HTTP client with automatic session handling.
    """
    
    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        ssl_verify: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.timeout = ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.ssl_verify = ssl_verify
        self.default_headers = headers or DEFAULT_HEADERS.copy()
        self._session: Optional[ClientSession] = None
        self._lock = asyncio.Lock()
    
    async def _get_session(self) -> ClientSession:
        """Get or create HTTP session."""
        async with self._lock:
            if self._session is None or self._session.closed:
                connector = create_connector(ssl_verify=self.ssl_verify)
                self._session = ClientSession(
                    timeout=self.timeout,
                    headers=self.default_headers,
                    connector=connector,
                    cookie_jar=aiohttp.CookieJar(unsafe=True),
                )
            return self._session
    
    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str, bytes]] = None,
        json: Optional[Dict[str, Any]] = None,
        cookies: Optional[Dict[str, str]] = None,
        allow_redirects: bool = True,
        **kwargs
    ) -> ClientResponse:
        """
        Make an HTTP request with automatic retry.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Target URL
            headers: Request headers
            params: URL query parameters
            data: Request body data
            json: JSON request body
            cookies: Request cookies
            allow_redirects: Whether to follow redirects
            **kwargs: Additional arguments for aiohttp
            
        Returns:
            aiohttp ClientResponse
        """
        session = await self._get_session()
        
        request_headers = self.default_headers.copy()
        if headers:
            request_headers.update(headers)
        
        return await session.request(
            method=method,
            url=url,
            headers=request_headers,
            params=params,
            data=data,
            json=json,
            cookies=cookies,
            allow_redirects=allow_redirects,
            **kwargs
        )
    
    async def get(self, url: str, **kwargs) -> ClientResponse:
        """Make GET request."""
        return await self.request("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> ClientResponse:
        """Make POST request."""
        return await self.request("POST", url, **kwargs)
    
    async def head(self, url: str, **kwargs) -> ClientResponse:
        """Make HEAD request."""
        return await self.request("HEAD", url, **kwargs)
    
    async def get_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """Make GET request and return JSON response."""
        async with await self.get(url, **kwargs) as response:
            return await response.json()
    
    async def get_text(self, url: str, **kwargs) -> str:
        """Make GET request and return text response."""
        async with await self.get(url, **kwargs) as response:
            return await response.text()
    
    async def get_bytes(self, url: str, **kwargs) -> bytes:
        """Make GET request and return bytes response."""
        async with await self.get(url, **kwargs) as response:
            return await response.read()
    
    async def download_file(
        self,
        url: str,
        destination: str,
        chunk_size: int = 8192,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        **kwargs
    ) -> int:
        """
        Download a file with optional progress callback.
        
        Args:
            url: URL to download
            destination: Local file path
            chunk_size: Download chunk size
            progress_callback: Callback(downloaded_bytes, total_bytes)
            **kwargs: Additional request arguments
            
        Returns:
            Total bytes downloaded
        """
        async with await self.get(url, **kwargs) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            
            with open(destination, "wb") as f:
                async for chunk in response.content.iter_chunked(chunk_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback:
                        progress_callback(downloaded, total_size)
            
            return downloaded
    
    async def get_final_url(self, url: str, **kwargs) -> str:
        """
        Follow redirects and get the final URL.
        
        Args:
            url: Initial URL
            **kwargs: Additional request arguments
            
        Returns:
            Final URL after all redirects
        """
        async with await self.head(url, allow_redirects=True, **kwargs) as response:
            return str(response.url)
    
    async def check_url(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        Check URL availability and get metadata.
        
        Args:
            url: URL to check
            **kwargs: Additional request arguments
            
        Returns:
            Dict with status, content_type, content_length, final_url
        """
        try:
            async with await self.head(url, allow_redirects=True, **kwargs) as response:
                return {
                    "status": response.status,
                    "ok": response.ok,
                    "content_type": response.headers.get("Content-Type", ""),
                    "content_length": int(response.headers.get("Content-Length", 0)),
                    "final_url": str(response.url),
                    "headers": dict(response.headers),
                }
        except Exception as e:
            return {
                "status": 0,
                "ok": False,
                "error": str(e),
            }


def build_url(base: str, path: str = "", params: Optional[Dict[str, Any]] = None) -> str:
    """
    Build a URL from components.
    
    Args:
        base: Base URL
        path: URL path
        params: Query parameters
        
    Returns:
        Complete URL string
    """
    from urllib.parse import urljoin, urlencode, urlparse, urlunparse, parse_qs
    
    # Join base and path
    if path:
        url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    else:
        url = base
    
    # Add query parameters
    if params:
        parsed = urlparse(url)
        existing_params = parse_qs(parsed.query)
        
        # Merge parameters
        for key, value in params.items():
            if value is not None:
                existing_params[key] = [str(value)]
        
        # Rebuild URL
        query = urlencode({k: v[0] for k, v in existing_params.items()})
        url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            query,
            parsed.fragment,
        ))
    
    return url


def parse_cookies(cookie_string: str) -> Dict[str, str]:
    """
    Parse a cookie string into a dictionary.
    
    Args:
        cookie_string: Cookie header value
        
    Returns:
        Dictionary of cookie name-value pairs
    """
    cookies = {}
    
    if not cookie_string:
        return cookies
    
    for item in cookie_string.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    
    return cookies


def build_cookie_string(cookies: Dict[str, str]) -> str:
    """
    Build a cookie string from a dictionary.
    
    Args:
        cookies: Dictionary of cookies
        
    Returns:
        Cookie header value
    """
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


async def fetch_with_retry(
    url: str,
    max_retries: int = 3,
    timeout: int = 30,
    headers: Optional[Dict[str, str]] = None,
    **kwargs
) -> str:
    """
    Fetch URL content with automatic retry.
    
    Args:
        url: URL to fetch
        max_retries: Maximum retry attempts
        timeout: Request timeout
        headers: Request headers
        **kwargs: Additional arguments
        
    Returns:
        Response text
    """
    async with HTTPClient(timeout=timeout, max_retries=max_retries) as client:
        if headers:
            client.default_headers.update(headers)
        return await client.get_text(url, **kwargs)


class RateLimiter:
    """
    Simple rate limiter for HTTP requests.
    """
    
    def __init__(self, requests_per_second: float = 10.0):
        self.min_interval = 1.0 / requests_per_second
        self.last_request = 0.0
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait for rate limit slot."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait_time = self.last_request + self.min_interval - now
            
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            self.last_request = asyncio.get_event_loop().time()
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


def retry_on_status(
    status_codes: tuple = (429, 500, 502, 503, 504),
    max_retries: int = 3,
    backoff_factor: float = 1.0,
):
    """
    Decorator to retry on specific HTTP status codes.
    
    Args:
        status_codes: Tuple of status codes to retry on
        max_retries: Maximum retry attempts
        backoff_factor: Exponential backoff factor
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    response = await func(*args, **kwargs)
                    
                    if hasattr(response, 'status') and response.status in status_codes:
                        if attempt < max_retries:
                            wait_time = backoff_factor * (2 ** attempt)
                            logger.warning(
                                f"Got status {response.status}, retrying in {wait_time}s "
                                f"(attempt {attempt + 1}/{max_retries})"
                            )
                            await asyncio.sleep(wait_time)
                            continue
                    
                    return response
                    
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_error = e
                    if attempt < max_retries:
                        wait_time = backoff_factor * (2 ** attempt)
                        logger.warning(
                            f"Request failed: {e}, retrying in {wait_time}s "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait_time)
                    else:
                        raise
            
            if last_error:
                raise last_error
                
        return wrapper
    return decorator
