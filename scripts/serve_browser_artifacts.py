"""Serve the packaged browser-engine artifacts on loopback for local development (Stage 5a).

The extension downloads only files listed in its pinned manifest and verifies each SHA-256,
so this server needs no trust. Default: http://127.0.0.1:47620/ over .cache/browser-artifacts.
"""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ArtifactHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # The engine page is cross-origin isolated; allow it to read these responses.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def list_directory(self, path):  # no directory listings
        self.send_error(404)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--directory", type=Path, default=ROOT / ".cache" / "browser-artifacts")
    parser.add_argument("--port", type=int, default=47620)
    arguments = parser.parse_args(argv)
    if not (arguments.directory / "manifest.json").is_file():
        parser.error(f"{arguments.directory} has no manifest.json; run scripts/build_browser_artifacts.py first")
    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), partial(ArtifactHandler, directory=str(arguments.directory)))
    print(f"Serving {arguments.directory} at http://127.0.0.1:{arguments.port}/ (Ctrl+C stops)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
