"""One isolated webhook HTTP operation. Parent enforces a hard total timeout.

Credentials arrive only on stdin, never command arguments or diagnostic output.
"""

import json
import sys
from urllib import error, request


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None


def perform(packet):
    opener = request.build_opener(NoRedirect())
    req = request.Request(
        packet["url"],
        data=json.dumps(packet["body"]).encode(),
        method="POST",
        headers=packet["headers"],
    )
    try:
        with opener.open(req, timeout=packet["timeout"]) as response:
            size = len(response.read(packet["limit"] + 1))
            if size > packet["limit"]:
                return {"kind": "oversize"}
            return {"kind": "http", "status": response.status}
    except error.HTTPError as exc:
        exc.close()
        return {"kind": "http", "status": exc.code}
    except (TimeoutError, error.URLError):
        return {"kind": "unavailable"}
    except Exception:
        return {"kind": "unknown"}


if __name__ == "__main__":
    # A control packet is tiny; no document payload is forwarded here.
    value = sys.stdin.buffer.read(64 * 1024 + 1)
    if len(value) > 64 * 1024:
        raise SystemExit(2)
    result = perform(json.loads(value))
    sys.stdout.write(json.dumps(result))
