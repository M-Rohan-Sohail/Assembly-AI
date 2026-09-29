import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

from _data import DATA


@pytest.fixture(scope="session")
def data():
    return DATA


@pytest.fixture
def make_event(data):
    def _make(**overrides):
        return {**data["event_template"], **overrides}
    return _make


@pytest.fixture
def http_server():
    """Tiny local server. Configure with server.responder(handler_fn); inspect server.requests."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8") if length else ""
            self.server.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
            status, payload = self.server.responder(self.path, body)
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.requests = []
    server.responder = lambda path, body: (200, b"")
    server.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
