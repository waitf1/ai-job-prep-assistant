import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest import TestCase
from unittest.mock import patch

from app.config import LLMSettings
from app.llm.client import LLMClient


class LocalAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        payload = json.dumps({
            "id": "test", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class LLMTransportTests(TestCase):
    def test_local_generation_bypasses_inherited_proxy(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), LocalAPIHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict("os.environ", {
                "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
                "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": "", "OPENAI_PROXY": "",
            }):
                client = LLMClient(LLMSettings(f"http://localhost:{server.server_port}/v1", "test", "test"))
                try:
                    self.assertEqual(client.chat("test", "test"), "OK")
                    self.assertEqual(client.chat_with_tools("test", "test", []).content, "OK")
                finally:
                    client.model.http_client.close()
                    asyncio.run(client.model.http_async_client.aclose())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_remote_configuration_keeps_default_transport(self):
        with patch("app.llm.client.ChatOpenAI") as model:
            LLMClient(LLMSettings("https://example.com/v1", "test", "test"))
        self.assertNotIn("http_client", model.call_args.kwargs)
        self.assertNotIn("openai_proxy", model.call_args.kwargs)
