from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

sys.dont_write_bytecode = True

from ltx23_batch_core import (
    BatchConfig,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PROMPTS,
    DEFAULT_WORKFLOW,
    RunnerError,
    discover_prompt_packs,
    get_template_default_image,
    load_prompt_pack,
    load_json,
    prompt_pack_key,
    prompt_pack_to_dict,
    prompt_sequence_to_dict,
    run_batch,
    run_result_to_dict,
)


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8765
DEFAULT_COMFY_URL = "http://127.0.0.1:8000/"
DEFAULT_COMFY_INPUT_DIR = Path(r"C:\ComfyUI\input")
STATIC_ROOT = Path(__file__).with_name("webui")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class JobRecord:
    job_id: str
    status: str
    created_at: float
    config: dict[str, Any]
    started_at: float | None = None
    finished_at: float | None = None
    total_runs: int = 0
    completed_runs: int = 0
    current_run_index: int | None = None
    current_prompt_number: int | None = None
    current_prompt_title: str | None = None
    current_variation: int | None = None
    current_seed_1: int | None = None
    current_seed_2: int | None = None
    current_prompt_id: str | None = None
    current_message: str = ""
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "status": self.status,
            "createdAt": iso_timestamp(self.created_at),
            "startedAt": iso_timestamp(self.started_at),
            "finishedAt": iso_timestamp(self.finished_at),
            "config": self.config,
            "totalRuns": self.total_runs,
            "completedRuns": self.completed_runs,
            "currentRunIndex": self.current_run_index,
            "currentPromptNumber": self.current_prompt_number,
            "currentPromptTitle": self.current_prompt_title,
            "currentVariation": self.current_variation,
            "currentSeed1": self.current_seed_1,
            "currentSeed2": self.current_seed_2,
            "currentPromptId": self.current_prompt_id,
            "currentMessage": self.current_message,
            "error": self.error,
            "events": self.events[-80:],
            "results": self.results,
        }


def iso_timestamp(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def request_text(url: str, timeout: int = 5) -> tuple[bool, int | None, str]:
    try:
        with urlopen(url, timeout=timeout) as response:
            content = response.read(256).decode("utf-8", errors="replace")
            return True, getattr(response, "status", 200), content
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)


class JobManager:
    def __init__(
        self,
        workflow_path: Path,
        prompts_path: Path,
        output_root: Path,
        comfy_input_dir: Path,
        default_comfy_url: str,
    ) -> None:
        self.workflow_path = workflow_path
        self.prompts_path = prompts_path
        self.output_root = output_root
        self.comfy_input_dir = comfy_input_dir
        self.default_comfy_url = default_comfy_url
        self.lock = threading.Lock()
        self.jobs: dict[str, JobRecord] = {}
        self.job_order: list[str] = []
        self.active_job_id: str | None = None

    def resolve_comfy_input_dir(self, path_value: str | None = None) -> Path:
        return self._resolve_path(path_value, self.comfy_input_dir)

    def resolve_output_root(self, path_value: str | None = None) -> Path:
        return self._resolve_path(path_value, self.output_root)

    def get_defaults(self) -> dict[str, Any]:
        template = load_json(self.workflow_path)
        return {
            "workflowPath": str(self.workflow_path.resolve()),
            "promptsPath": str(self.prompts_path.resolve()),
            "defaultPromptFile": prompt_pack_key(self.prompts_path),
            "outputRoot": str(self.output_root),
            "comfyInputDir": str(self.comfy_input_dir),
            "defaultImage": get_template_default_image(template),
            "defaultServerUrl": self.default_comfy_url,
        }

    def list_prompt_files(self) -> list[dict[str, Any]]:
        return [prompt_pack_to_dict(pack) for pack in self._available_prompt_packs()]

    def list_prompts(self, prompt_file: str | None = None) -> dict[str, Any]:
        pack = load_prompt_pack(self.resolve_prompt_file(prompt_file))
        return {
            "pack": prompt_pack_to_dict(pack),
            "items": [prompt_sequence_to_dict(sequence) for sequence in pack.prompts],
        }

    def list_images(self, comfy_input_dir: Path | None = None) -> list[dict[str, Any]]:
        input_dir = comfy_input_dir or self.comfy_input_dir
        if not input_dir.exists():
            return []
        items = []
        for path in sorted(input_dir.iterdir(), key=lambda p: p.name.lower()):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                stat = path.stat()
                items.append(
                    {
                        "name": path.name,
                        "size": stat.st_size,
                        "modifiedAt": iso_timestamp(stat.st_mtime),
                    }
                )
        return items

    def list_recent_outputs(self, output_root: Path | None = None, limit: int = 12) -> list[dict[str, Any]]:
        base_dir = (output_root or self.output_root) / "LTX2.3" / "PromptIteration"
        if not base_dir.exists():
            return []
        candidates = sorted(
            base_dir.rglob("*-audio.mp4"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        items = []
        for path in candidates[:limit]:
            stat = path.stat()
            sidecar = path.with_suffix(".txt")
            items.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "folder": str(path.parent),
                    "size": stat.st_size,
                    "modifiedAt": iso_timestamp(stat.st_mtime),
                    "sidecarPath": str(sidecar) if sidecar.exists() else None,
                }
            )
        return items

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            active_job = self.jobs.get(self.active_job_id) if self.active_job_id else None
            recent_jobs = [self.jobs[job_id].to_dict() for job_id in reversed(self.job_order[-8:])]
            return {
                "activeJobId": self.active_job_id,
                "activeJob": active_job.to_dict() if active_job else None,
                "recentJobs": recent_jobs,
            }

    def open_output_path(self, path_value: str, output_root_value: str | None = None) -> dict[str, Any]:
        if not path_value:
            raise RunnerError("No output path was provided.")

        output_root = self.resolve_output_root(output_root_value)
        path = Path(path_value).expanduser().resolve()
        if not path.exists():
            raise RunnerError(f"Output path does not exist: {path}")
        try:
            path.relative_to(output_root)
        except ValueError as exc:
            raise RunnerError("Only files inside the ComfyUI output root can be opened.") from exc
        if path.is_dir():
            raise RunnerError("Expected a video file path, not a directory.")
        if not hasattr(os, "startfile"):
            raise RunnerError("Opening files is only supported on Windows in this tool.")

        os.startfile(str(path))
        return {"opened": str(path)}

    def resolve_prompt_file(self, prompt_file: str | None) -> Path:
        if not prompt_file:
            return self.prompts_path
        requested_key = prompt_file.replace("\\", "/").strip()
        for pack in self._available_prompt_packs():
            if prompt_pack_key(pack.source_path) == requested_key:
                return pack.source_path
        raise RunnerError(f"Prompt pack not found: {prompt_file}")

    def start_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._build_config(payload)
        with self.lock:
            if self.active_job_id is not None:
                raise RunnerError("A batch job is already running. Wait for it to finish before starting another.")

            job_id = uuid.uuid4().hex[:10]
            job = JobRecord(
                job_id=job_id,
                status="queued",
                created_at=time.time(),
                config={
                    "serverUrl": config.server_url,
                    "promptFile": prompt_pack_key(config.prompts),
                    "image": config.image,
                    "variations": config.variations,
                    "promptNumbers": config.prompt_numbers,
                    "seedBase": config.seed_base,
                    "comfyInputDir": str(self.resolve_comfy_input_dir(payload.get("comfyInputDir"))),
                    "outputRoot": str(config.output_root),
                },
            )
            self.jobs[job_id] = job
            self.job_order.append(job_id)
            self.active_job_id = job_id

        thread = threading.Thread(target=self._run_job, args=(job_id, config), daemon=True)
        thread.start()
        return job.to_dict()

    def _build_config(self, payload: dict[str, Any]) -> BatchConfig:
        image = str(payload.get("image", "")).strip()
        if not image:
            raise RunnerError("An image filename is required.")

        variations_raw = payload.get("variations", 1)
        try:
            variations = int(variations_raw)
        except (TypeError, ValueError) as exc:
            raise RunnerError("Variations must be a whole number.") from exc
        if variations < 1 or variations > 20:
            raise RunnerError("Variations must be between 1 and 20.")

        prompt_numbers_raw = payload.get("promptNumbers")
        if not isinstance(prompt_numbers_raw, list) or not prompt_numbers_raw:
            raise RunnerError("Select at least one prompt.")
        prompt_numbers = sorted({int(number) for number in prompt_numbers_raw})

        seed_base_raw = payload.get("seedBase")
        seed_base = None
        if seed_base_raw not in (None, ""):
            try:
                seed_base = int(seed_base_raw)
            except (TypeError, ValueError) as exc:
                raise RunnerError("Seed base must be blank or an integer.") from exc

        server_url = str(payload.get("serverUrl") or self.default_comfy_url).strip()
        if not server_url:
            raise RunnerError("A ComfyUI server URL is required.")

        prompt_file = str(payload.get("promptFile", "")).strip() or None
        prompts_path = self.resolve_prompt_file(prompt_file)
        output_root = self.resolve_output_root(payload.get("outputRoot"))

        return BatchConfig(
            workflow=self.workflow_path,
            prompts=prompts_path,
            image=image,
            variations=variations,
            prompt_numbers=prompt_numbers,
            seed_base=seed_base,
            server_url=server_url,
            output_root=output_root,
            timeout_seconds=7200,
            poll_seconds=5.0,
        )

    def _run_job(self, job_id: str, config: BatchConfig) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = time.time()
            job.current_message = "Preparing batch plan"

        def on_progress(event) -> None:
            event_dict = event.to_dict()
            with self.lock:
                current = self.jobs[job_id]
                current.events.append(event_dict)
                current.current_message = event.message
                if event.total_runs is not None:
                    current.total_runs = event.total_runs
                if event.completed_runs is not None:
                    current.completed_runs = event.completed_runs
                if event.run_index is not None:
                    current.current_run_index = event.run_index
                if event.prompt_number is not None:
                    current.current_prompt_number = event.prompt_number
                if event.prompt_title is not None:
                    current.current_prompt_title = event.prompt_title
                if event.variation is not None:
                    current.current_variation = event.variation
                if event.seed_1 is not None:
                    current.current_seed_1 = event.seed_1
                if event.seed_2 is not None:
                    current.current_seed_2 = event.seed_2
                if event.prompt_id is not None:
                    current.current_prompt_id = event.prompt_id

        try:
            results = run_batch(config, progress_callback=on_progress)
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                current = self.jobs[job_id]
                current.status = "failed"
                current.finished_at = time.time()
                current.error = str(exc)
                current.current_message = str(exc)
                self.active_job_id = None
            return

        with self.lock:
            current = self.jobs[job_id]
            current.status = "completed"
            current.finished_at = time.time()
            current.results = [run_result_to_dict(result) for result in results]
            current.completed_runs = len(results)
            current.current_message = f"Completed {len(results)} run(s)."
            self.active_job_id = None

    def _available_prompt_packs(self) -> list[Any]:
        packs = discover_prompt_packs()
        default_path = self.prompts_path.resolve()
        if all(pack.source_path.resolve() != default_path for pack in packs) and self.prompts_path.exists():
            packs.append(load_prompt_pack(self.prompts_path))
        return sorted(packs, key=lambda pack: prompt_pack_key(pack.source_path).lower())

    @staticmethod
    def _resolve_path(path_value: str | os.PathLike[str] | None, default_path: Path) -> Path:
        raw = str(path_value or "").strip()
        path = Path(raw) if raw else default_path
        return path.expanduser().resolve()


class LTXRequestHandler(BaseHTTPRequestHandler):
    server_version = "LTX23WebUI/1.0"

    @property
    def app(self) -> "LTXWebServer":
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self.serve_static("index.html")
            return
        if path == "/styles.css":
            self.serve_static("styles.css")
            return
        if path == "/app.js":
            self.serve_static("app.js")
            return
        if path == "/api/config":
            self.send_json(HTTPStatus.OK, self.app.manager.get_defaults())
            return
        if path == "/api/prompt-files":
            self.send_json(HTTPStatus.OK, {"items": self.app.manager.list_prompt_files()})
            return
        if path == "/api/prompts":
            prompt_file = parse_qs(parsed.query).get("file", [None])[0]
            self.send_json(HTTPStatus.OK, self.app.manager.list_prompts(prompt_file))
            return
        if path == "/api/images":
            input_dir = self.app.manager.resolve_comfy_input_dir(parse_qs(parsed.query).get("inputDir", [None])[0])
            self.send_json(
                HTTPStatus.OK,
                {
                    "directory": str(input_dir),
                    "exists": input_dir.exists(),
                    "items": self.app.manager.list_images(input_dir),
                },
            )
            return
        if path == "/api/status":
            self.send_json(HTTPStatus.OK, self.app.manager.get_status())
            return
        if path == "/api/recent-outputs":
            output_root = self.app.manager.resolve_output_root(parse_qs(parsed.query).get("outputRoot", [None])[0])
            self.send_json(
                HTTPStatus.OK,
                {
                    "outputRoot": str(output_root),
                    "exists": output_root.exists(),
                    "items": self.app.manager.list_recent_outputs(output_root),
                },
            )
            return
        if path == "/api/health":
            server_url = parse_qs(parsed.query).get("serverUrl", [self.app.manager.default_comfy_url])[0]
            ok, status_code, detail = request_text(server_url)
            self.send_json(
                HTTPStatus.OK,
                {
                    "serverUrl": server_url,
                    "ok": ok,
                    "statusCode": status_code,
                    "detail": detail,
                },
            )
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/jobs":
            try:
                payload = self.read_json_body()
                job = self.app.manager.start_job(payload)
            except RunnerError as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except ValueError as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self.send_json(HTTPStatus.CREATED, job)
            return
        if self.path == "/api/open-output":
            try:
                payload = self.read_json_body()
                result = self.app.manager.open_output_path(
                    str(payload.get("path", "")).strip(),
                    str(payload.get("outputRoot", "")).strip() or None,
                )
            except RunnerError as exc:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self.send_json(HTTPStatus.OK, result)
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length).decode("utf-8")
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON body: {exc}") from exc
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object.")
        return body

    def serve_static(self, filename: str) -> None:
        path = STATIC_ROOT / filename
        if not path.exists():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Static asset not found"})
            return
        content = path.read_bytes()
        content_type, _ = mimetypes.guess_type(path.name)
        if content_type is None:
            content_type = "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


class LTXWebServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], manager: JobManager) -> None:
        super().__init__(server_address, LTXRequestHandler)
        self.manager = manager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local LTX 2.3 web UI.")
    parser.add_argument("--host", default=DEFAULT_WEB_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_WEB_PORT)
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--comfy-input-dir", type=Path, default=DEFAULT_COMFY_INPUT_DIR)
    parser.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manager = JobManager(
        workflow_path=args.workflow,
        prompts_path=args.prompts,
        output_root=args.output_root,
        comfy_input_dir=args.comfy_input_dir,
        default_comfy_url=args.comfy_url,
    )
    server = LTXWebServer((args.host, args.port), manager)
    print(f"R.O.V.E.R. web UI running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
