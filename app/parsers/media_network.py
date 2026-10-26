"""Keep extractor pages, redirects and native media fragments on public egress."""
import io

import yt_dlp
from yt_dlp.networking import Request, Response
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp.downloader import get_suitable_downloader
from yt_dlp.downloader.http import HttpFD
from yt_dlp.downloader.hls import HlsFD
from yt_dlp.downloader.dash import DashSegmentsFD

from app.network import UnsafeURL, public_sync_client, validate_url


class PublicYoutubeDL(yt_dlp.YoutubeDL):
    def __init__(self, params=None, **kwargs):
        params = dict(params or {})
        params["external_downloader"] = {"default": "native"}
        # HlsFD can internally fall back to FFmpeg for unsupported manifests.
        params["external_downloader_args"] = {"ffmpeg_i": ["-protocol_whitelist", "file,pipe"]}
        super().__init__(params, **kwargs)

    def dl(self, name, info, subtitle=False, test=False):
        validate_url(info.get("url", ""))
        downloader = get_suitable_downloader(info, self.params, to_stdout=(name == "-"))
        if downloader not in (HttpFD, HlsFD, DashSegmentsFD):
            raise UnsafeURL("Only native HTTP media downloaders are allowed")
        return super().dl(name, info, subtitle=subtitle, test=test)

    def urlopen(self, request):
        if isinstance(request, str):
            request = Request(request)
        elif not isinstance(request, Request):
            request = Request(request.full_url, data=request.data, headers=dict(request.headers),
                              method=request.get_method())
        validate_url(request.url)
        try:
            with public_sync_client(timeout=self.params.get("socket_timeout", 15),
                                    cookies=self.cookiejar, follow_redirects=True) as client:
                with client.stream(request.method, request.url, content=request.data,
                                   headers=dict(request.headers)) as response:
                    # Bounded short-video responses; no downloader bypasses this transport.
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > 64 * 1024 * 1024:
                            raise ValueError("Media response exceeds 64 MiB limit")
                    headers = {k: v for k, v in response.headers.items()
                               if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
                    headers["Content-Length"] = str(len(data))
                    result = Response(io.BytesIO(data), str(response.url), headers,
                                      response.status_code, response.reason_phrase)
            if result.status >= 400:
                raise HTTPError(result)
            return result
        except HTTPError:
            raise
        except Exception as exc:
            raise TransportError(cause=exc) from exc
