"""Orrfin.ai Tally relay. Runs on the machine where Tally Prime is open, never on the internet.

It fetches pending vouchers from Orrfin.ai over HTTPS, posts each to Tally's local XML server,
and reports Tally's response back. Tally's port stays on localhost; nothing connects inbound.

Usage:
  python tally_relay.py --server https://your-orrfin-host --token <relay token> [--tally http://localhost:9000] [--once]

Needs Python 3.10+ and no extra packages.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def _call(url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
    request.add_header("X-Orrfin-Relay-Token", token)
    if data:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def post_to_tally(tally_url: str, xml: str) -> str:
    request = urllib.request.Request(tally_url, data=xml.encode("utf-8"), method="POST")
    request.add_header("Content-Type", "text/xml; charset=utf-8")
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def run_once(server: str, token: str, tally_url: str) -> int:
    pending = _call(f"{server}/api/erp/relay/pending", token)
    delivered = 0
    for item in pending["items"]:
        try:
            reply = post_to_tally(tally_url, item["xml"])
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"Tally didn't respond for {item['external_key']}: {error}. Is Tally open with the company loaded?", file=sys.stderr)
            return delivered
        result = _call(f"{server}/api/erp/relay/{item['outbox_id']}/result", token, {"response_xml": reply})
        print(f"{item['external_key']}: {result['status']} {result.get('last_error') or ''}".strip())
        delivered += result["status"] == "delivered"
    return delivered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--tally", default="http://localhost:9000")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    server = args.server.rstrip("/")
    if not args.tally.startswith(("http://localhost", "http://127.0.0.1")) and "--allow-remote-tally" not in sys.argv:
        print("Refusing: Tally's XML server has no authentication, so keep it on localhost.", file=sys.stderr)
        return 2
    while True:
        try:
            run_once(server, args.token, args.tally)
        except urllib.error.HTTPError as error:
            print(f"Orrfin.ai returned {error.code}. Check the relay token.", file=sys.stderr)
            if error.code == 401:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
