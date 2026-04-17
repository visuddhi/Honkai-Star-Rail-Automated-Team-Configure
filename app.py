from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from src.data_loader import get_scenario, list_scenarios, load_sample_roster
from src.recommender import RecommendationError, build_recommendation

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"


class PrototypeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if path == "/api/scenarios":
            self._send_json({"scenarios": list_scenarios()})
            return
        if path == "/api/sample-roster":
            self._send_json(load_sample_roster())
            return
        if path == "/api/scenario":
            self._send_json({"error": "Use /api/scenarios and filter client-side."}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/recommend":
            self._send_json({"error": "Unknown endpoint."}, HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            payload = json.loads(raw_body or "{}")
        except json.JSONDecodeError:
            self._send_json({"error": "请求体不是合法 JSON。"}, HTTPStatus.BAD_REQUEST)
            return

        scenario_id = payload.get("scenarioId")
        roster_payload = payload.get("roster")
        if not scenario_id:
            self._send_json({"error": "缺少 scenarioId。"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            scenario = get_scenario(scenario_id)
            recommendation = build_recommendation(scenario, roster_payload)
            self._send_json(recommendation)
        except KeyError:
            self._send_json({"error": f"未找到场景：{scenario_id}"}, HTTPStatus.NOT_FOUND)
        except RecommendationError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - fallback for manual prototype use
            self._send_json({"error": f"服务端异常：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run() -> None:
    host = "127.0.0.1"
    port = 8000
    server = ThreadingHTTPServer((host, port), PrototypeHandler)
    print(f"Prototype server is running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
