import base64
import json
from typing import Dict, Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


def _base64url_decode(input_str: str) -> bytes:
    """Decode a base64url-encoded string to bytes."""
    padded = input_str.replace("-", "+").replace("_", "/")
    padding = 4 - len(padded) % 4
    if padding != 4:
        padded += "=" * padding
    return base64.b64decode(padded)


def _combine_key_parts(key_parts: list) -> bytes:
    """Combine base64url-encoded key parts into a single key."""
    decoded = [_base64url_decode(part) for part in key_parts]
    return b"".join(decoded)


def _decrypt_playback(playback: dict) -> dict:
    """Decrypt AES-256-GCM encrypted playback payload."""
    key = _combine_key_parts(playback["key_parts"])
    iv = _base64url_decode(playback["iv"])
    payload = _base64url_decode(playback["payload"])

    # GCM auth tag is the last 16 bytes of the payload
    tag = payload[-16:]
    ciphertext = payload[:-16]

    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
    except Exception as e:
        raise ExtractorError(f"Decryption failed: {e}")

    return json.loads(plaintext.decode("utf-8"))


class FileMoonExtractor(BaseExtractor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mediaflow_endpoint = "hls_manifest_proxy"

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        # URL format: https://filemoon.sx/e/{code} or https://filemoon.sx/d/{code}
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        code = path.split("/")[-1] if path else None

        if not code or code in ("e", "d"):
            raise ExtractorError(f"Could not extract video code from URL: {url}")

        api_url = f"{parsed.scheme}://{parsed.netloc}/api/videos/{code}"

        headers = {"Referer": url}
        response = await self._make_request(api_url, headers=headers)

        try:
            data = response.json()
        except Exception as e:
            raise ExtractorError(f"Failed to parse API response: {e}")

        if "error" in data:
            raise ExtractorError(f"FileMoon API error: {data['error']}")

        playback = data.get("playback")
        if not playback or not playback.get("key_parts") or not playback.get("payload"):
            raise ExtractorError("No playback data available")

        decrypted = _decrypt_playback(playback)

        sources = decrypted.get("sources", [])
        hls_source = None
        for source in sources:
            if source.get("mime_type") == "application/vnd.apple.mpegurl":
                hls_source = source
                break

        if not hls_source:
            raise ExtractorError("No HLS source found in decrypted playback")

        destination_url = hls_source["url"]

        self.base_headers["referer"] = url

        return {
            "destination_url": destination_url,
            "request_headers": self.base_headers,
            "mediaflow_endpoint": self.mediaflow_endpoint,
        }
