"""
Terabox domain resolver and normalizer.
Handles all known Terabox domains and mirrors.
"""
import re
from typing import Optional, Tuple, Set
from urllib.parse import urlparse, parse_qs
import logging

logger = logging.getLogger(__name__)


class DomainResolver:
    """
    Resolves and normalizes Terabox URLs across all known domains.
    """
    
    # All known Terabox domains and mirrors
    KNOWN_DOMAINS: Set[str] = {
        # Primary domains
        "terabox.com",
        "www.terabox.com",
        "teraboxapp.com",
        "www.teraboxapp.com",
        
        # Alternative domains
        "1024tera.com",
        "www.1024tera.com",
        "4funbox.co",
        "www.4funbox.co",
        "4funbox.com",
        "www.4funbox.com",
        
        # Mirror domains
        "mirrobox.com",
        "www.mirrobox.com",
        "nephobox.com",
        "www.nephobox.com",
        "momerybox.com",
        "www.momerybox.com",
        "tibibox.com",
        "www.tibibox.com",
        "freeterabox.com",
        "www.freeterabox.com",
        
        # Legacy domains
        "dubox.com",
        "www.dubox.com",
        "teraboxlink.com",
        "www.teraboxlink.com",
        "terafileshare.com",
        "www.terafileshare.com",
        
        # Regional domains
        "terabox.co",
        "www.terabox.co",
        "terabox.fun",
        "www.terabox.fun",
        "terabox.app",
        "www.terabox.app",
        
        # Additional mirrors
        "1024terabox.com",
        "www.1024terabox.com",
        "gibibox.com",
        "www.gibibox.com",
        "box.terabox.app",
    }
    
    # Canonical domain for API calls
    CANONICAL_DOMAIN = "www.terabox.com"
    
    # URL patterns for extracting share IDs
    SHARE_PATTERNS = [
        # Standard share links: /s/xxxxx or /sharing/link?surl=xxxxx
        r"/s/([a-zA-Z0-9_-]+)",
        r"/sharing/link\?surl=([a-zA-Z0-9_-]+)",
        r"[?&]surl=([a-zA-Z0-9_-]+)",
        # Shortened formats
        r"/wap/s/([a-zA-Z0-9_-]+)",
        r"/web/share/link\?surl=([a-zA-Z0-9_-]+)",
        r"/share/link\?surl=([a-zA-Z0-9_-]+)",
    ]
    
    @classmethod
    def is_terabox_url(cls, url: str) -> bool:
        """Check if URL belongs to Terabox ecosystem."""
        try:
            parsed = urlparse(url.lower())
            domain = parsed.netloc.replace("www.", "")
            
            # Check against known domains
            for known in cls.KNOWN_DOMAINS:
                if known.replace("www.", "") == domain or domain.endswith(known.replace("www.", "")):
                    return True
            
            # Check for terabox-like patterns in domain
            terabox_patterns = ["terabox", "tera", "box", "dubox", "funbox", "nepho", "mirro", "momer"]
            return any(pattern in domain for pattern in terabox_patterns)
            
        except Exception as e:
            logger.error(f"Error parsing URL: {e}")
            return False
    
    @classmethod
    def extract_surl(cls, url: str) -> Optional[str]:
        """Extract the share URL ID (surl) from any Terabox URL format."""
        try:
            # Try each pattern
            for pattern in cls.SHARE_PATTERNS:
                match = re.search(pattern, url)
                if match:
                    return match.group(1)
            
            # Try query parameter extraction
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            
            if "surl" in params:
                return params["surl"][0]
            
            # Try path-based extraction for /s/ format
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] == "s":
                return path_parts[1]
            
            logger.warning(f"Could not extract surl from: {url}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting surl: {e}")
            return None
    
    @classmethod
    def normalize_url(cls, url: str) -> Optional[str]:
        """Normalize any Terabox URL to canonical format."""
        surl = cls.extract_surl(url)
        if surl:
            return f"https://{cls.CANONICAL_DOMAIN}/s/{surl}"
        return None
    
    @classmethod
    def get_api_base(cls) -> str:
        """Get the canonical API base URL."""
        return f"https://{cls.CANONICAL_DOMAIN}"
    
    @classmethod
    def parse_url(cls, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Parse Terabox URL and return (surl, normalized_url, api_base).
        """
        if not cls.is_terabox_url(url):
            return None, None, None
        
        surl = cls.extract_surl(url)
        if not surl:
            return None, None, None
        
        normalized = cls.normalize_url(url)
        api_base = cls.get_api_base()
        
        return surl, normalized, api_base
