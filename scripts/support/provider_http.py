"""Credential-bearing OpenRouter transport; no redirects or alternative origins."""

import urllib.error
import urllib.parse
import urllib.request


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib otherwise copies Authorization onto some redirected requests.
        raise urllib.error.URLError("Authenticated provider redirects are disabled")


def open_provider_request(request: urllib.request.Request, *, timeout: float):
    """Send only to the reviewed HTTPS provider; preserve TLS verification."""
    target = urllib.parse.urlsplit(request.full_url)
    if (target.scheme != "https" or target.hostname != "openrouter.ai"
            or target.port not in (None, 443) or target.username is not None
            or target.password is not None or target.fragment):
        raise urllib.error.URLError("Unsupported authenticated provider origin")
    return urllib.request.build_opener(_RejectRedirects()).open(request, timeout=timeout)
