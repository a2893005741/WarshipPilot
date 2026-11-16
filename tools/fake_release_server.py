"""Local stand-in for the GitHub Releases API, for testing the built-in updater.

    python tools/fake_release_server.py <zip> <tag> [port]
    set WARSHIPPILOT_UPDATE_API=http://127.0.0.1:<port>   (before starting the EXE)

Serves /repos/<any>/releases/latest and /repos/<any>/releases/assets/1 with
the given zip and its real SHA-256 digest. Development tool only.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys

archive = Path(sys.argv[1])
tag = sys.argv[2]
port = int(sys.argv[3]) if len(sys.argv) > 3 else 18765
data = archive.read_bytes()
digest = hashlib.sha256(data).hexdigest()
name = f'WarshipPilot-{tag.lstrip("v")}-win-x64.zip'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith('/releases/latest'):
            body = json.dumps({'tag_name': tag, 'name': tag, 'body': 'local test release',
                               'published_at': '2026-11-17T00:00:00Z',
                               'assets': [{'id': 1, 'name': name, 'size': len(data),
                                           'digest': f'sha256:{digest}'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
        elif self.path.endswith('/releases/assets/1'):
            body = data
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
        else:
            body = b'{}'
            self.send_response(404)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        print('[fake-release]', self.address_string(), self.requestline, flush=True)


print(f'serving {name} sha256={digest} on {port}', flush=True)
ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
