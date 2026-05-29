import re
from typing import Dict, Any
from urllib.parse import urljoin, urlparse
from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


class VidmolyExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str) -> Dict[str, Any]:
        parsed = urlparse(url)
        if not parsed.hostname or "vidmoly" not in parsed.hostname:
            raise ExtractorError("VIDMOLY: Invalid domain")

        embed_id_match = re.search(r"/embed-([a-zA-Z0-9]+)\.html", parsed.path)
        if not embed_id_match:
            raise ExtractorError("VIDMOLY: Could not extract embed ID from URL")
        embed_id = embed_id_match.group(1)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Cookie": f"cf_turnstile_demo_pass_{embed_id}=1",
            "Referer": url,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }

        # --- Fetch embed page ---
        response = await self._make_request(url, headers=headers)
        html = response.text

        # --- Extract master m3u8 ---
        match = re.search(r'sources\s*:\s*\[\s*\{\s*file\s*:\s*[\'"]([^\'"]+)', html)
        if not match:
            raise ExtractorError("VIDMOLY: Stream URL not found")

        master_url = match.group(1)
        if not master_url.startswith("http"):
            master_url = urljoin(url, master_url)

        # --- Validate stream ---
        try:
            test = await self._make_request(master_url, headers=headers)
        except Exception as e:
            if "timeout" in str(e).lower():
                raise ExtractorError("VIDMOLY: Request timed out")
            raise

        if test.status >= 400:
            raise ExtractorError(f"VIDMOLY: Stream unavailable ({test.status})")

        return {
            "destination_url": master_url,
            "request_headers": headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }
