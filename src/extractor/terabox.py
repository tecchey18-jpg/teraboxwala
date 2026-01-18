"""
Main Terabox extractor - the core extraction logic.
Reverse-engineers Terabox's web API flow.
"""
import asyncio
import json
import re
import time
import hashlib
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlencode, quote, unquote
import logging

from ..domains.resolver import DomainResolver
from .token_manager import TokenManager
from .api_client import TeraboxAPIClient, TeraboxAPIError
from .normalizer import LinkNormalizer

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """Holds extracted video information."""
    title: str = ""
    filename: str = ""
    size: int = 0
    size_formatted: str = ""
    thumbnail: str = ""
    duration: int = 0
    resolution: str = ""
    
    # File identifiers
    fs_id: str = ""
    share_id: str = ""
    uk: str = ""
    surl: str = ""
    
    # URLs
    download_url: str = ""
    stream_url: str = ""
    dlink: str = ""
    
    # Quality variants
    quality_options: List[Dict[str, str]] = field(default_factory=list)
    
    # Original data
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def format_size(self, size_bytes: int) -> str:
        """Format file size to human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    def __post_init__(self):
        if self.size and not self.size_formatted:
            self.size_formatted = self.format_size(self.size)


class TeraboxExtractor:
    """
    Production-grade Terabox video extractor.
    Implements the full Terabox API flow.
    """
    
    # Quality priority (highest first)
    QUALITY_PRIORITY = ["1080p", "720p", "480p", "360p", "240p", "original"]
    
    def __init__(self, token_manager: Optional[TokenManager] = None, timeout: int = 30):
        self.token_manager = token_manager or TokenManager()
        self.api_client = TeraboxAPIClient(self.token_manager, timeout)
        self.domain_resolver = DomainResolver()
        self.normalizer = LinkNormalizer()
        
    async def close(self):
        """Clean up resources."""
        await self.api_client.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def extract(self, url: str) -> VideoInfo:
        """
        Extract video information and streaming URL from a Terabox link.
        
        Args:
            url: Any Terabox share URL
            
        Returns:
            VideoInfo with all extracted data including direct streaming URL
        """
        logger.info(f"Extracting from: {url}")
        
        # Step 1: Parse and normalize URL
        surl, normalized_url, _ = self.domain_resolver.parse_url(url)
        if not surl:
            raise TeraboxAPIError(f"Invalid Terabox URL: {url}")
        
        logger.info(f"Extracted surl: {surl}")
        
        # Step 2: Fetch share page to get initial data
        share_data = await self._fetch_share_info(surl)
        
        # Step 3: Get file list
        file_list = await self._get_file_list(share_data, surl)
        
        if not file_list:
            raise TeraboxAPIError("No files found in share")
        
        # Get first video file (or first file)
        target_file = self._find_video_file(file_list)
        if not target_file:
            raise TeraboxAPIError("No video file found in share")
        
        # Step 4: Get streaming URL
        video_info = await self._get_stream_url(share_data, target_file)
        
        # Store surl for reference
        video_info.surl = surl
        
        return video_info
    
    async def _fetch_share_info(self, surl: str) -> Dict[str, Any]:
        """Fetch share page and extract embedded data."""
        # First, try the short URL info API
        try:
            response = await self.api_client.get(
                "/api/shorturlinfo",
                params={
                    "shorturl": surl,
                    "root": "1",
                }
            )
            
            if response.get("errno") == 0:
                return response
                
        except TeraboxAPIError as e:
            logger.warning(f"shorturlinfo API failed: {e}")
        
        # Fallback: fetch the actual page and parse it
        url = f"https://{self.api_client.current_domain}/s/{surl}"
        html = await self.api_client.fetch_page(url)
        
        return self._parse_share_page(html, surl)
    
    def _parse_share_page(self, html: str, surl: str) -> Dict[str, Any]:
        """Parse share page HTML to extract all needed data."""
        data: Dict[str, Any] = {"surl": surl}
        
        # Try to find the embedded data script
        patterns = [
            # Pattern 1: window.locals = {...}
            r'<script>\s*window\.locals\s*=\s*(\{.+?\});\s*</script>',
            # Pattern 2: __locals = {...}
            r'__locals\s*=\s*(\{.+?\})',
            # Pattern 3: data-* attribute
            r'data-share-info="([^"]+)"',
            # Pattern 4: React/JS state
            r'window\.__INITIAL_STATE__\s*=\s*(\{.+?\});',
            # Pattern 5: Inline JSON
            r'var\s+share(?:Info|Data)\s*=\s*(\{.+?\});',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    json_str = match.group(1)
                    # Handle HTML-encoded JSON
                    json_str = json_str.replace('&quot;', '"').replace('&amp;', '&')
                    json_str = unquote(json_str)
                    
                    embedded_data = json.loads(json_str)
                    data.update(self._flatten_share_data(embedded_data))
                    break
                except json.JSONDecodeError as e:
                    logger.debug(f"Failed to parse embedded JSON: {e}")
                    continue
        
        # Extract individual fields if embedded data failed
        extractors = {
            "shareid": [
                r'"shareid"\s*[=:]\s*["\']?(\d+)["\']?',
                r'share_id["\s]*[=:]\s*["\']?(\d+)["\']?',
                r'shareid=(\d+)',
            ],
            "uk": [
                r'"uk"\s*[=:]\s*["\']?(\d+)["\']?',
                r'user_key["\s]*[=:]\s*["\']?(\d+)["\']?',
                r'uk=(\d+)',
            ],
            "sign": [
                r'"sign"\s*[=:]\s*["\']([^"\']+)["\']',
                r'sign=([a-zA-Z0-9]+)',
            ],
            "timestamp": [
                r'"timestamp"\s*[=:]\s*(\d+)',
                r'timestamp=(\d+)',
            ],
        }
        
        for key, patterns in extractors.items():
            if key not in data or not data[key]:
                for pattern in patterns:
                    match = re.search(pattern, html)
                    if match:
                        data[key] = match.group(1)
                        break
        
        # Extract file list from page if available
        file_list_patterns = [
            r'"file_list"\s*:\s*(\[.+?\])',
            r'"list"\s*:\s*(\[.+?\])',
        ]
        
        for pattern in file_list_patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data["file_list"] = json.loads(match.group(1))
                    break
                except json.JSONDecodeError:
                    continue
        
        logger.debug(f"Parsed share data: shareid={data.get('shareid')}, uk={data.get('uk')}")
        
        return data
    
    def _flatten_share_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested share data structure."""
        result = {}
        
        # Direct fields
        direct_fields = ["shareid", "uk", "sign", "timestamp", "title", "file_list"]
        for field in direct_fields:
            if field in data:
                result[field] = data[field]
        
        # Nested structures
        if "share" in data:
            result.update(self._flatten_share_data(data["share"]))
        if "file" in data:
            if isinstance(data["file"], list):
                result["file_list"] = data["file"]
            elif isinstance(data["file"], dict):
                result["file_list"] = [data["file"]]
        if "list" in data:
            result["file_list"] = data["list"]
        
        return result
    
    async def _get_file_list(self, share_data: Dict[str, Any], surl: str) -> List[Dict[str, Any]]:
        """Get the list of files in the share."""
        # Check if we already have file list
        if "file_list" in share_data:
            return share_data["file_list"]
        if "list" in share_data:
            return share_data["list"]
        
        # Fetch file list from API
        shareid = share_data.get("shareid", "")
        uk = share_data.get("uk", "")
        
        if not shareid or not uk:
            # Try alternative API
            try:
                response = await self.api_client.get(
                    "/share/list",
                    params={
                        "shorturl": surl,
                        "root": "1",
                        "dir": "/",
                        "page": "1",
                        "num": "100",
                        "order": "asc",
                        "by": "name",
                    }
                )
                
                if "list" in response:
                    return response["list"]
                    
            except TeraboxAPIError as e:
                logger.warning(f"share/list API failed: {e}")
        
        # Standard file list API
        try:
            params = {
                "shorturl": surl,
                "dir": "/",
                "page": "1",
                "num": "100",
                "order": "asc",
                "by": "name",
                "root": "1",
            }
            
            if shareid:
                params["shareid"] = shareid
            if uk:
                params["uk"] = uk
            
            response = await self.api_client.get("/share/list", params=params)
            
            return response.get("list", [])
            
        except TeraboxAPIError as e:
            logger.error(f"Failed to get file list: {e}")
            return []
    
    def _find_video_file(self, file_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Find the first video file in the file list."""
        video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}
        
        # First pass: find by extension
        for file in file_list:
            filename = file.get("server_filename", file.get("filename", "")).lower()
            if any(filename.endswith(ext) for ext in video_extensions):
                return file
        
        # Second pass: find by category/type
        for file in file_list:
            category = file.get("category", 0)
            if category == 1:  # Video category
                return file
        
        # Third pass: find by MIME type
        for file in file_list:
            mime = file.get("mime_type", file.get("type", "")).lower()
            if "video" in mime:
                return file
        
        # Return first file if no video found
        return file_list[0] if file_list else None
    
    async def _get_stream_url(self, share_data: Dict[str, Any], file: Dict[str, Any]) -> VideoInfo:
        """Get the streaming URL for a file."""
        video_info = VideoInfo(
            filename=file.get("server_filename", file.get("filename", "Unknown")),
            title=file.get("server_filename", file.get("filename", "Unknown")),
            size=int(file.get("size", 0)),
            fs_id=str(file.get("fs_id", "")),
            share_id=str(share_data.get("shareid", "")),
            uk=str(share_data.get("uk", "")),
            thumbnail=file.get("thumbs", {}).get("url3", file.get("thumb", "")),
            raw_data=file,
        )
        
        # Try multiple methods to get stream URL
        
        # Method 1: dlink from file data
        if file.get("dlink"):
            video_info.dlink = file["dlink"]
            video_info.stream_url = await self._process_dlink(file["dlink"])
            if video_info.stream_url:
                return video_info
        
        # Method 2: Streaming API
        stream_url = await self._fetch_streaming_url(share_data, file)
        if stream_url:
            video_info.stream_url = stream_url
            return video_info
        
        # Method 3: Download API with special handling
        download_url = await self._fetch_download_url(share_data, file)
        if download_url:
            video_info.download_url = download_url
            video_info.stream_url = download_url
            return video_info
        
        # Method 4: Alternative streaming endpoint
        alt_url = await self._fetch_alt_stream_url(share_data, file)
        if alt_url:
            video_info.stream_url = alt_url
            return video_info
        
        raise TeraboxAPIError("Could not obtain streaming URL")
    
    async def _process_dlink(self, dlink: str) -> Optional[str]:
        """Process and validate a dlink URL."""
        if not dlink:
            return None
        
        # Add necessary parameters
        if "?" in dlink:
            dlink = f"{dlink}&"
        else:
            dlink = f"{dlink}?"
        
        # Follow redirects to get final URL
        try:
            session = await self.api_client._get_session()
            headers = self.token_manager.get_api_headers()
            headers["Cookie"] = self.token_manager.get_cookie_string()
            
            async with session.head(
                dlink,
                headers=headers,
                allow_redirects=True,
                timeout=10
            ) as response:
                if response.status == 200:
                    return str(response.url)
        except Exception as e:
            logger.debug(f"dlink processing failed: {e}")
        
        return dlink
    
    async def _fetch_streaming_url(self, share_data: Dict[str, Any], file: Dict[str, Any]) -> Optional[str]:
        """Fetch streaming URL from streaming API."""
        fs_id = file.get("fs_id", "")
        uk = share_data.get("uk", "")
        shareid = share_data.get("shareid", "")
        surl = share_data.get("surl", "")
        
        # Try different streaming types
        stream_types = ["M3U8_AUTO_720", "M3U8_AUTO_480", "M3U8_FLV_264_480", "mp4"]
        
        for stream_type in stream_types:
            try:
                params = {
                    "type": stream_type,
                    "uk": uk,
                    "shareid": shareid,
                    "fid": fs_id,
                }
                
                if share_data.get("sign"):
                    params["sign"] = share_data["sign"]
                if share_data.get("timestamp"):
                    params["timestamp"] = share_data["timestamp"]
                
                response = await self.api_client.get(
                    "/share/streaming",
                    params=params,
                    referer=f"https://{self.api_client.current_domain}/s/{surl}"
                )
                
                # Check for stream URL in response
                if isinstance(response, dict):
                    for key in ["lurl", "dlink", "url", "path", "mlink"]:
                        if response.get(key):
                            return response[key]
                    
                    if response.get("urls"):
                        urls = response["urls"]
                        if isinstance(urls, list) and urls:
                            return urls[0].get("url", urls[0].get("dlink"))
                        elif isinstance(urls, dict):
                            return urls.get("url", urls.get("dlink"))
                            
            except TeraboxAPIError as e:
                if e.errno != 2:  # 2 = invalid params, expected for some types
                    logger.debug(f"Streaming API failed for type {stream_type}: {e}")
                continue
        
        return None
    
    async def _fetch_download_url(self, share_data: Dict[str, Any], file: Dict[str, Any]) -> Optional[str]:
        """Fetch download URL that can also be used for streaming."""
        fs_id = file.get("fs_id", "")
        uk = share_data.get("uk", "")
        shareid = share_data.get("shareid", "")
        surl = share_data.get("surl", "")
        sign = share_data.get("sign", "")
        timestamp = share_data.get("timestamp", int(time.time()))
        
        # Generate sign if not available
        if not sign:
            sign = self.token_manager.generate_sign(int(timestamp), str(shareid))
        
        try:
            params = {
                "shareid": shareid,
                "uk": uk,
                "fid_list": f'["{fs_id}"]',
                "sign": sign,
                "timestamp": timestamp,
            }
            
            session_data = self.token_manager.get_session_data()
            if session_data and session_data.js_token:
                params["jsToken"] = session_data.js_token
            
            response = await self.api_client.get(
                "/share/download",
                params=params,
                referer=f"https://{self.api_client.current_domain}/s/{surl}"
            )
            
            if isinstance(response, dict):
                # Check various response formats
                if response.get("list"):
                    item = response["list"][0] if isinstance(response["list"], list) else response["list"]
                    return item.get("dlink", item.get("url"))
                
                if response.get("dlink"):
                    return response["dlink"]
                
        except TeraboxAPIError as e:
            logger.debug(f"Download API failed: {e}")
        
        return None
    
    async def _fetch_alt_stream_url(self, share_data: Dict[str, Any], file: Dict[str, Any]) -> Optional[str]:
        """Try alternative methods to get stream URL."""
        fs_id = file.get("fs_id", "")
        surl = share_data.get("surl", "")
        
        # Method: Try direct filemetas endpoint
        try:
            response = await self.api_client.get(
                "/api/filemetas",
                params={
                    "dlink": "1",
                    "target": f'["{fs_id}"]',
                }
            )
            
            if response.get("info"):
                info = response["info"]
                if isinstance(info, list) and info:
                    return info[0].get("dlink")
                    
        except TeraboxAPIError as e:
            logger.debug(f"filemetas API failed: {e}")
        
        # Method: Try video endpoint
        try:
            response = await self.api_client.get(
                "/share/videoPlay",
                params={
                    "surl": surl,
                    "fid": fs_id,
                }
            )
            
            if isinstance(response, dict):
                # Check for video URL in various formats
                for key in ["video", "url", "stream", "hd_url", "sd_url"]:
                    if response.get(key):
                        return response[key]
                        
        except TeraboxAPIError as e:
            logger.debug(f"videoPlay API failed: {e}")
        
        return None
