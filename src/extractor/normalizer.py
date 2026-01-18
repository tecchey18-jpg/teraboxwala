"""
Link normalizer for Terabox URLs.
"""
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import logging

logger = logging.getLogger(__name__)


class LinkNormalizer:
    """Normalizes and cleans Terabox links."""
    
    @staticmethod
    def clean_url(url: str) -> str:
        """Remove tracking parameters and normalize URL."""
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            
            # Keep only essential parameters
            essential = {"surl", "shareid", "uk", "fid"}
            cleaned_params = {k: v[0] for k, v in params.items() if k in essential}
            
            new_query = urlencode(cleaned_params) if cleaned_params else ""
            cleaned = urlunparse((
                parsed.scheme or "https",
                parsed.netloc,
                parsed.path,
                "",
                new_query,
                ""
            ))
            
            return cleaned
            
        except Exception as e:
            logger.error(f"Error cleaning URL: {e}")
            return url
    
    @staticmethod
    def extract_file_id(url: str) -> Optional[str]:
        """Extract file ID from URL if present."""
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            
            # Check various file ID parameters
            for key in ["fid", "fs_id", "file_id", "id"]:
                if key in params:
                    return params[key][0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting file ID: {e}")
            return None
    
    @staticmethod
    def build_share_url(surl: str, domain: str = "www.terabox.com") -> str:
        """Build a standard share URL from surl."""
        return f"https://{domain}/s/{surl}"
    
    @staticmethod
    def build_api_url(endpoint: str, params: Dict[str, Any], domain: str = "www.terabox.com") -> str:
        """Build an API URL with parameters."""
        base = f"https://{domain}{endpoint}"
        query = urlencode(params)
        return f"{base}?{query}" if query else base
