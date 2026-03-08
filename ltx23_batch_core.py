from __future__ import annotations

import copy
import json
import random
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent
PROMPT_PACK_DIR = PROJECT_ROOT / "prompt-packs"
WORKFLOW_DIR = PROJECT_ROOT / "workflows"
DEFAULT_WORKFLOW = WORKFLOW_DIR / "ltx23_rover_api.json"
DEFAULT_PROMPTS = PROMPT_PACK_DIR / "rover-prompt-pack.yaml"
DEFAULT_SERVER_URL = "http://127.0.0.1:8188"
DEFAULT_OUTPUT_ROOT = Path(r"C:\ComfyUI\output")
DEFAULT_VARIATIONS = 3
PROMPT_PACK_EXTENSIONS = {".yaml", ".yml"}
LEGACY_PROMPT_EXTENSIONS = {".md", ".markdown"}
POSITIVE_PROMPT_NODE = "121"
NEGATIVE_PROMPT_NODE = "110"
IMAGE_NODE = "167"
OUTPUT_NODE = "140"
TEXT_TO_VIDEO_NODE = "290"
LENGTH_SECONDS_NODE = "291"
FIRST_NOISE_NODE = "115"
SECOND_NOISE_NODE = "114"
PREVIEW_OVERRIDE_NODE = "337"
NAG_MODEL_NODE = "342"
BASE_MODEL_NODE = "301"
MAX_SEED = 2**63 - 1
VIDEO_EXTENSIONS = {".avi", ".gif", ".mkv", ".mov", ".mp4", ".webm"}


class RunnerError(RuntimeError):
    pass


class StopRequestedError(RunnerError):
    pass


@dataclass(frozen=True)
class PromptSequence:
    number: int
    title: str
    concept: str
    duration: str
    beats: list[tuple[str, str]]
    extras: list[str]
    speech_sound: str

    def to_prompt_text(self) -> str:
        lines = [f"Prompt Sequence {self.number}: {self.title}"]
        if self.concept:
            lines.append(f"Concept: {self.concept}")
        if self.duration:
            lines.append(f"Video Description: {self.duration}")
        for timestamp, description in self.beats:
            lines.append(f"{timestamp}: {description}")
        lines.extend(self.extras)
        if self.speech_sound:
            lines.append(f"Speech & Sound: {self.speech_sound}")
        return "\n".join(lines)


@dataclass(frozen=True)
class PromptPack:
    name: str
    description: str
    source_path: Path
    prompts: list[PromptSequence]
    format: str


@dataclass(frozen=True)
class RunPlan:
    prompt: PromptSequence
    variation: int
    seed_1: int
    seed_2: int
    video_length_seconds: int | None
    image_name: str
    filename_prefix: str
    positive_prompt: str
    negative_prompt: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunResult:
    prompt_number: int
    prompt_title: str
    variation: int
    seed_1: int
    seed_2: int
    video_length_seconds: int | None
    prompt_id: str
    filename_prefix: str
    image_name: str
    output_paths: list[str]


@dataclass(frozen=True)
class BatchConfig:
    workflow: Path = DEFAULT_WORKFLOW
    prompts: Path = DEFAULT_PROMPTS
    image: str | None = None
    variations: int = DEFAULT_VARIATIONS
    prompt_numbers: str | list[int] | None = None
    seed_base: int | None = None
    video_length_seconds: int | None = None
    server_url: str = DEFAULT_SERVER_URL
    output_root: Path = DEFAULT_OUTPUT_ROOT
    timeout_seconds: int = 7200
    poll_seconds: float = 5.0
    dry_run: bool = False
    dry_run_dir: Path | None = None


@dataclass(frozen=True)
class BatchProgressEvent:
    event_type: str
    message: str
    timestamp: float
    total_runs: int | None = None
    completed_runs: int | None = None
    run_index: int | None = None
    prompt_number: int | None = None
    prompt_title: str | None = None
    variation: int | None = None
    seed_1: int | None = None
    seed_2: int | None = None
    prompt_id: str | None = None
    filename_prefix: str | None = None
    output_paths: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ProgressCallback = Callable[[BatchProgressEvent], None]
StopRequestedCallback = Callable[[], bool]


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnerError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RunnerError(f"Invalid JSON in {path}: {exc}") from exc


def prompt_pack_key(path: Path | str) -> str:
    path = Path(path)
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT.resolve())
        return relative.as_posix()
    except ValueError:
        return path.name


def load_prompt_pack(path: Path | str) -> PromptPack:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in PROMPT_PACK_EXTENSIONS:
        return parse_yaml_prompt_pack(path)
    if suffix in LEGACY_PROMPT_EXTENSIONS:
        return PromptPack(
            name=path.stem,
            description="Legacy Markdown prompt pack.",
            source_path=path,
            prompts=parse_markdown_prompt_sequences(path),
            format="markdown",
        )
    raise RunnerError(f"Unsupported prompt pack format for {path}. Use .yaml or .yml.")


def discover_prompt_packs() -> list[PromptPack]:
    candidate_paths: list[Path] = []
    if PROMPT_PACK_DIR.exists():
        for extension in sorted(PROMPT_PACK_EXTENSIONS):
            candidate_paths.extend(PROMPT_PACK_DIR.rglob(f"*{extension}"))

    prompt_packs: list[PromptPack] = []
    seen: set[Path] = set()
    for path in sorted(candidate_paths, key=lambda item: prompt_pack_key(item).lower()):
        if path.name.startswith(("_", ".")):
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            prompt_packs.append(load_prompt_pack(path))
        except RunnerError:
            continue
    return prompt_packs


def prompt_pack_to_dict(pack: PromptPack) -> dict[str, Any]:
    return {
        "key": prompt_pack_key(pack.source_path),
        "name": pack.name,
        "description": pack.description,
        "path": str(pack.source_path.resolve()),
        "format": pack.format,
        "promptCount": len(pack.prompts),
    }


def parse_prompt_sequences(path: Path | str) -> list[PromptSequence]:
    return load_prompt_pack(path).prompts


def parse_markdown_prompt_sequences(markdown_path: Path) -> list[PromptSequence]:
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RunnerError(f"File not found: {markdown_path}") from exc

    heading_re = re.compile(r"^##\s+Prompt Sequence\s+(\d+):\s*(.+?)\s*$", re.MULTILINE)
    matches = list(heading_re.finditer(markdown))
    if not matches:
        raise RunnerError(f"No prompt sections found in {markdown_path}.")

    sequences: list[PromptSequence] = []
    for index, match in enumerate(matches):
        number = int(match.group(1))
        title = match.group(2).strip()
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end].strip()
        sequences.append(parse_markdown_prompt_section(number, title, body))

    return sequences


def parse_markdown_prompt_section(number: int, title: str, body: str) -> PromptSequence:
    concept = ""
    duration = ""
    speech_sound = ""
    beats: list[tuple[str, str]] = []
    extras: list[str] = []

    concept_re = re.compile(r"^\*\*Concept:\*\*\s*(.+)$")
    duration_re = re.compile(r"^\*\*Video Description:\*\*\s*(.+)$")
    speech_re = re.compile(r"^\*\*Speech & Sound:\*\*\s*(.+)$")
    beat_re = re.compile(r"^- \*\*(.+?):\*\*\s*(.+)$")

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = concept_re.match(line)
        if match:
            concept = match.group(1).strip()
            continue
        match = duration_re.match(line)
        if match:
            duration = match.group(1).strip()
            continue
        match = speech_re.match(line)
        if match:
            speech_sound = match.group(1).strip()
            continue
        match = beat_re.match(line)
        if match:
            beats.append((match.group(1).strip(), match.group(2).strip()))
            continue
        extras.append(line.replace("**", "").strip())

    return PromptSequence(
        number=number,
        title=title,
        concept=concept,
        duration=duration,
        beats=beats,
        extras=extras,
        speech_sound=speech_sound,
    )


def parse_yaml_prompt_pack(path: Path) -> PromptPack:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunnerError(f"File not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise RunnerError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RunnerError(f"Prompt pack {path} must contain a top-level mapping.")

    raw_name = payload.get("name")
    raw_description = payload.get("description", "")
    raw_prompts = payload.get("prompts")
    if not isinstance(raw_prompts, list) or not raw_prompts:
        raise RunnerError(f"Prompt pack {path} must define a non-empty prompts list.")

    prompts: list[PromptSequence] = []
    seen_numbers: set[int] = set()
    for index, raw_prompt in enumerate(raw_prompts, start=1):
        if not isinstance(raw_prompt, dict):
            raise RunnerError(f"Prompt #{index} in {path} must be a mapping.")
        prompts.append(parse_yaml_prompt_sequence(raw_prompt, path, index))
        if prompts[-1].number in seen_numbers:
            raise RunnerError(f"Prompt number {prompts[-1].number} is duplicated in {path}.")
        seen_numbers.add(prompts[-1].number)

    name = str(raw_name).strip() if raw_name else path.stem
    description = str(raw_description).strip()
    return PromptPack(
        name=name,
        description=description,
        source_path=path,
        prompts=sorted(prompts, key=lambda prompt: prompt.number),
        format="yaml",
    )


def parse_yaml_prompt_sequence(raw_prompt: dict[str, Any], path: Path, index: int) -> PromptSequence:
    number_raw = raw_prompt.get("number", raw_prompt.get("id"))
    if number_raw is None:
        raise RunnerError(f"Prompt #{index} in {path} is missing a number.")
    try:
        number = int(number_raw)
    except (TypeError, ValueError) as exc:
        raise RunnerError(f"Prompt #{index} in {path} has an invalid number: {number_raw}") from exc

    title = str(raw_prompt.get("title", "")).strip()
    if not title:
        raise RunnerError(f"Prompt {number} in {path} is missing a title.")

    concept = str(raw_prompt.get("concept", "")).strip()
    duration = str(raw_prompt.get("duration", "")).strip()
    speech_sound = str(raw_prompt.get("speech_sound", raw_prompt.get("speechSound", ""))).strip()
    extras = parse_string_list(raw_prompt.get("extras"), path, number, "extras")
    beats = parse_yaml_beats(raw_prompt.get("beats"), path, number)

    return PromptSequence(
        number=number,
        title=title,
        concept=concept,
        duration=duration,
        beats=beats,
        extras=extras,
        speech_sound=speech_sound,
    )


def parse_string_list(raw_value: Any, path: Path, prompt_number: int, field_name: str) -> list[str]:
    if raw_value in (None, ""):
        return []
    if not isinstance(raw_value, list):
        raise RunnerError(f"Prompt {prompt_number} in {path} must define {field_name} as a list.")
    items: list[str] = []
    for raw_item in raw_value:
        text = str(raw_item).strip()
        if text:
            items.append(text)
    return items


def parse_yaml_beats(raw_value: Any, path: Path, prompt_number: int) -> list[tuple[str, str]]:
    if raw_value in (None, ""):
        return []
    if not isinstance(raw_value, list):
        raise RunnerError(f"Prompt {prompt_number} in {path} must define beats as a list.")

    beats: list[tuple[str, str]] = []
    for beat_index, raw_beat in enumerate(raw_value, start=1):
        if not isinstance(raw_beat, dict):
            raise RunnerError(
                f"Beat #{beat_index} for prompt {prompt_number} in {path} must be a mapping."
            )
        timestamp = str(raw_beat.get("timestamp", raw_beat.get("time", ""))).strip()
        description = str(raw_beat.get("description", "")).strip()
        if not timestamp or not description:
            raise RunnerError(
                f"Beat #{beat_index} for prompt {prompt_number} in {path} needs timestamp and description."
            )
        beats.append((timestamp, description))
    return beats


def prompt_sequence_to_dict(sequence: PromptSequence) -> dict[str, Any]:
    preview_lines = []
    if sequence.concept:
        preview_lines.append(f"Concept: {sequence.concept}")
    if sequence.duration:
        preview_lines.append(f"Duration: {sequence.duration}")
    if sequence.beats:
        preview_lines.append(f"Opening beat: {sequence.beats[0][1]}")
    return {
        "number": sequence.number,
        "title": sequence.title,
        "concept": sequence.concept,
        "duration": sequence.duration,
        "beats": [{"timestamp": ts, "description": desc} for ts, desc in sequence.beats],
        "extras": sequence.extras,
        "speechSound": sequence.speech_sound,
        "positivePrompt": sequence.to_prompt_text(),
        "preview": " ".join(preview_lines).strip(),
    }


def parse_prompt_number_selection(selection: str | None, available_numbers: Iterable[int]) -> set[int]:
    available = set(available_numbers)
    if not selection:
        return available

    selected: set[int] = set()
    for chunk in selection.split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text)
            end = int(end_text)
            if end < start:
                raise RunnerError(f"Invalid prompt range: {part}")
            selected.update(range(start, end + 1))
            continue
        selected.add(int(part))

    missing = sorted(number for number in selected if number not in available)
    if missing:
        raise RunnerError(f"Prompt numbers not found in prompt pack: {missing}")
    return selected


def select_prompts(
    sequences: list[PromptSequence], selection: str | Iterable[int] | None
) -> list[PromptSequence]:
    available_numbers = [sequence.number for sequence in sequences]
    if selection is None:
        selected_numbers = set(available_numbers)
    elif isinstance(selection, str):
        selected_numbers = parse_prompt_number_selection(selection, available_numbers)
    else:
        selected_numbers = {int(number) for number in selection}
        missing = sorted(number for number in selected_numbers if number not in set(available_numbers))
        if missing:
            raise RunnerError(f"Prompt numbers not found in prompt pack: {missing}")
    return [sequence for sequence in sequences if sequence.number in selected_numbers]


def make_rng(seed_base: int | None) -> random.Random:
    return random.Random(seed_base) if seed_base is not None else random.SystemRandom()


def next_seed_pair(rng: random.Random) -> tuple[int, int]:
    return rng.randrange(1, MAX_SEED), rng.randrange(1, MAX_SEED)


def build_filename_prefix(prompt_number: int, variation: int, seed_1: int, seed_2: int) -> str:
    return (
        f"LTX2.3/PromptIteration/{prompt_number}/"
        f"p{prompt_number:02d}_v{variation:02d}_s1_{seed_1}_s2_{seed_2}"
    )


def validate_template(template: dict[str, Any]) -> None:
    required = {
        POSITIVE_PROMPT_NODE,
        NEGATIVE_PROMPT_NODE,
        IMAGE_NODE,
        OUTPUT_NODE,
        TEXT_TO_VIDEO_NODE,
        FIRST_NOISE_NODE,
        SECOND_NOISE_NODE,
    }
    missing = sorted(node_id for node_id in required if node_id not in template)
    if missing:
        raise RunnerError(f"Workflow template is missing required nodes: {missing}")


def get_template_default_image(template: dict[str, Any]) -> str | None:
    return template.get(IMAGE_NODE, {}).get("inputs", {}).get("image")


def get_template_default_video_length(template: dict[str, Any]) -> int | None:
    raw = template.get(LENGTH_SECONDS_NODE, {}).get("inputs", {}).get("value")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def build_payload(
    template: dict[str, Any],
    positive_prompt: str,
    image_name: str,
    seed_1: int,
    seed_2: int,
    filename_prefix: str,
    video_length_seconds: int | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(template)
    payload[POSITIVE_PROMPT_NODE]["inputs"]["text"] = positive_prompt
    payload[FIRST_NOISE_NODE]["inputs"]["noise_seed"] = seed_1
    payload[SECOND_NOISE_NODE]["inputs"]["noise_seed"] = seed_2
    payload[IMAGE_NODE]["inputs"]["image"] = image_name
    payload[OUTPUT_NODE]["inputs"]["filename_prefix"] = filename_prefix.replace("\\", "/")
    payload[TEXT_TO_VIDEO_NODE]["inputs"]["value"] = False
    if video_length_seconds is not None and LENGTH_SECONDS_NODE in payload:
        payload[LENGTH_SECONDS_NODE]["inputs"]["value"] = int(video_length_seconds)
    # The desktop preview override can crash headless/API runs in some KJNodes setups.
    if NAG_MODEL_NODE in payload and BASE_MODEL_NODE in payload:
        model_input = payload[NAG_MODEL_NODE]["inputs"].get("model")
        if model_input == [PREVIEW_OVERRIDE_NODE, 0]:
            payload[NAG_MODEL_NODE]["inputs"]["model"] = [BASE_MODEL_NODE, 0]
    return payload


def build_run_plans(
    template: dict[str, Any],
    sequences: list[PromptSequence],
    variations: int,
    image_name: str,
    rng: random.Random,
    video_length_seconds: int | None = None,
) -> list[RunPlan]:
    negative_prompt = template[NEGATIVE_PROMPT_NODE]["inputs"]["text"]
    plans: list[RunPlan] = []

    for sequence in sequences:
        positive_prompt = sequence.to_prompt_text()
        for variation in range(1, variations + 1):
            seed_1, seed_2 = next_seed_pair(rng)
            filename_prefix = build_filename_prefix(sequence.number, variation, seed_1, seed_2)
            payload = build_payload(
                template=template,
                positive_prompt=positive_prompt,
                image_name=image_name,
                seed_1=seed_1,
                seed_2=seed_2,
                filename_prefix=filename_prefix,
                video_length_seconds=video_length_seconds,
            )
            plans.append(
                RunPlan(
                    prompt=sequence,
                    variation=variation,
                    seed_1=seed_1,
                    seed_2=seed_2,
                    video_length_seconds=video_length_seconds,
                    image_name=image_name,
                    filename_prefix=filename_prefix,
                    positive_prompt=positive_prompt,
                    negative_prompt=negative_prompt,
                    payload=payload,
                )
            )
    return plans


def sidecar_text(plan: RunPlan) -> str:
    lines = [
        f"Prompt Number: {plan.prompt.number}",
        f"Prompt Title: {plan.prompt.title}",
        f"Variation: {plan.variation}",
        f"Image: {plan.image_name}",
        f"Seed 1: {plan.seed_1}",
        f"Seed 2: {plan.seed_2}",
        f"Video Length (Seconds): {plan.video_length_seconds if plan.video_length_seconds is not None else 'Template default'}",
        f"Filename Prefix: {plan.filename_prefix}",
        "",
        "Positive Prompt:",
        plan.positive_prompt,
        "",
        "Negative Prompt:",
        plan.negative_prompt,
    ]
    return "\n".join(lines) + "\n"


def request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RunnerError(f"ComfyUI API error {exc.code} at {url}: {message}") from exc
    except URLError as exc:
        raise RunnerError(f"Could not reach ComfyUI API at {url}: {exc}") from exc

    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise RunnerError(f"Invalid JSON response from {url}: {body}") from exc


def interrupt_comfy(server_url: str) -> None:
    request_json("POST", f"{server_url.rstrip('/')}/interrupt")


def queue_prompt(server_url: str, payload: dict[str, Any]) -> str:
    response = request_json("POST", f"{server_url.rstrip('/')}/prompt", {"prompt": payload})
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise RunnerError(f"ComfyUI did not return a prompt_id: {response}")
    node_errors = response.get("node_errors") or {}
    if node_errors:
        raise RunnerError(f"ComfyUI rejected the prompt with node errors: {node_errors}")
    return prompt_id


def iter_queue_prompt_ids(queue_items: Any) -> Iterable[str]:
    if not isinstance(queue_items, list):
        return
    for item in queue_items:
        if isinstance(item, (list, tuple)) and len(item) > 1 and isinstance(item[1], str):
            yield item[1]


def wait_for_prompt_exit_queue(
    server_url: str,
    prompt_id: str,
    timeout_seconds: int = 45,
    poll_seconds: float = 1.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    queue_url = f"{server_url.rstrip('/')}/queue"

    while time.monotonic() < deadline:
        queue_state = request_json("GET", queue_url)
        queue_prompt_ids = set(iter_queue_prompt_ids(queue_state.get("queue_running"))) | set(
            iter_queue_prompt_ids(queue_state.get("queue_pending"))
        )
        if prompt_id not in queue_prompt_ids:
            return True
        time.sleep(poll_seconds)
    return False


def wait_for_completion(
    server_url: str,
    prompt_id: str,
    timeout_seconds: int,
    poll_seconds: float,
    should_stop: StopRequestedCallback | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    history_url = f"{server_url.rstrip('/')}/history/{prompt_id}"

    while time.monotonic() < deadline:
        if should_stop is not None and should_stop():
            stop_message = "Stop requested by operator."
            try:
                interrupt_comfy(server_url)
                queue_cleared = wait_for_prompt_exit_queue(server_url, prompt_id)
                if not queue_cleared:
                    stop_message = (
                        "Stop requested by operator. ComfyUI interrupt was sent, but queue shutdown "
                        "was not confirmed before timeout."
                    )
            except RunnerError:
                stop_message = "Stop requested by operator. ComfyUI interrupt was sent."
            raise StopRequestedError(stop_message)

        history = request_json("GET", history_url)
        if history:
            if prompt_id in history:
                record = history[prompt_id]
            elif len(history) == 1:
                record = next(iter(history.values()))
            else:
                record = None
            if record and record.get("outputs"):
                return record
        time.sleep(poll_seconds)

    raise RunnerError(f"Timed out waiting for ComfyUI prompt {prompt_id} to finish.")


def iter_file_entries(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        if "filename" in obj:
            yield obj
        for value in obj.values():
            yield from iter_file_entries(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_file_entries(item)


def extract_video_paths(history_record: dict[str, Any], output_root: Path) -> list[Path]:
    outputs = history_record.get("outputs", {})
    preferred = outputs.get(OUTPUT_NODE, {})
    entries = list(iter_file_entries(preferred))
    if not entries:
        entries = list(iter_file_entries(outputs))

    video_paths: list[Path] = []
    for entry in entries:
        filename = entry.get("filename")
        if not filename:
            continue
        fullpath = entry.get("fullpath")
        path = Path(fullpath) if fullpath else output_root / entry.get("subfolder", "") / filename
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            video_paths.append(path)

    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for path in video_paths:
        if path not in seen:
            unique_paths.append(path)
            seen.add(path)
    return unique_paths


def wait_for_files(paths: list[Path], timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    remaining = set(paths)
    while remaining and time.monotonic() < deadline:
        finished = {path for path in remaining if path.exists()}
        remaining -= finished
        if remaining:
            time.sleep(1)
    if remaining:
        missing = ", ".join(str(path) for path in sorted(remaining))
        raise RunnerError(f"ComfyUI reported outputs, but the files never appeared: {missing}")


def write_sidecars(paths: list[Path], plan: RunPlan) -> None:
    content = sidecar_text(plan)
    for video_path in paths:
        video_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path = video_path.with_suffix(".txt")
        sidecar_path.write_text(content, encoding="utf-8")


def write_dry_run_outputs(base_dir: Path, plans: list[RunPlan]) -> None:
    for plan in plans:
        relative_prefix = Path(plan.filename_prefix)
        output_dir = base_dir / relative_prefix.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        payload_path = output_dir / f"{relative_prefix.name}.json"
        payload_path.write_text(json.dumps(plan.payload, indent=2), encoding="utf-8")

        sidecar_path = output_dir / f"{relative_prefix.name}.txt"
        sidecar_path.write_text(sidecar_text(plan), encoding="utf-8")


def format_plan_summary(plans: list[RunPlan]) -> list[str]:
    lines = [f"Prepared {len(plans)} run(s)."]
    for plan in plans:
        lines.append(
            f"Prompt {plan.prompt.number} variation {plan.variation}: "
            f"seed_1={plan.seed_1} seed_2={plan.seed_2} prefix={plan.filename_prefix}"
        )
    return lines


def emit_progress(
    callback: ProgressCallback | None,
    event_type: str,
    message: str,
    *,
    total_runs: int | None = None,
    completed_runs: int | None = None,
    run_index: int | None = None,
    prompt_number: int | None = None,
    prompt_title: str | None = None,
    variation: int | None = None,
    seed_1: int | None = None,
    seed_2: int | None = None,
    prompt_id: str | None = None,
    filename_prefix: str | None = None,
    output_paths: list[str] | None = None,
) -> None:
    if callback is None:
        return
    callback(
        BatchProgressEvent(
            event_type=event_type,
            message=message,
            timestamp=time.time(),
            total_runs=total_runs,
            completed_runs=completed_runs,
            run_index=run_index,
            prompt_number=prompt_number,
            prompt_title=prompt_title,
            variation=variation,
            seed_1=seed_1,
            seed_2=seed_2,
            prompt_id=prompt_id,
            filename_prefix=filename_prefix,
            output_paths=output_paths,
        )
    )


def run_batch(
    config: BatchConfig,
    progress_callback: ProgressCallback | None = None,
    should_stop: StopRequestedCallback | None = None,
) -> list[RunResult]:
    if config.variations < 1:
        raise RunnerError("--variations must be at least 1.")
    if config.video_length_seconds is not None and not 1 <= int(config.video_length_seconds) <= 300:
        raise RunnerError("--video-length-seconds must be between 1 and 300.")

    template = load_json(config.workflow)
    validate_template(template)
    sequences = select_prompts(parse_prompt_sequences(config.prompts), config.prompt_numbers)
    image_name = config.image or get_template_default_image(template)
    if not image_name:
        raise RunnerError("No input image was provided and the workflow template does not define one.")

    plans = build_run_plans(
        template=template,
        sequences=sequences,
        variations=config.variations,
        image_name=image_name,
        rng=make_rng(config.seed_base),
        video_length_seconds=config.video_length_seconds,
    )

    emit_progress(
        progress_callback,
        "batch_planned",
        f"Prepared {len(plans)} run(s).",
        total_runs=len(plans),
        completed_runs=0,
    )

    if should_stop is not None and should_stop():
        emit_progress(
            progress_callback,
            "batch_stopped",
            "Stop requested before any runs were queued.",
            total_runs=len(plans),
            completed_runs=0,
        )
        raise StopRequestedError("Stop requested before any runs were queued.")

    if config.dry_run:
        if config.dry_run_dir:
            write_dry_run_outputs(config.dry_run_dir, plans)
            emit_progress(
                progress_callback,
                "dry_run_written",
                f"Dry-run files written to {config.dry_run_dir}",
                total_runs=len(plans),
                completed_runs=0,
            )
        return []

    results: list[RunResult] = []
    try:
        for index, plan in enumerate(plans, start=1):
            if should_stop is not None and should_stop():
                raise StopRequestedError("Stop requested by operator.")

            emit_progress(
                progress_callback,
                "run_started",
                (
                    f"Queueing prompt {plan.prompt.number} variation {plan.variation} "
                    f"with seeds {plan.seed_1}/{plan.seed_2}"
                ),
                total_runs=len(plans),
                completed_runs=len(results),
                run_index=index,
                prompt_number=plan.prompt.number,
                prompt_title=plan.prompt.title,
                variation=plan.variation,
                seed_1=plan.seed_1,
                seed_2=plan.seed_2,
                filename_prefix=plan.filename_prefix,
            )
            if should_stop is not None and should_stop():
                raise StopRequestedError("Stop requested by operator.")
            prompt_id = queue_prompt(config.server_url, plan.payload)
            emit_progress(
                progress_callback,
                "run_queued",
                f"ComfyUI accepted prompt {prompt_id}",
                total_runs=len(plans),
                completed_runs=len(results),
                run_index=index,
                prompt_number=plan.prompt.number,
                prompt_title=plan.prompt.title,
                variation=plan.variation,
                seed_1=plan.seed_1,
                seed_2=plan.seed_2,
                prompt_id=prompt_id,
                filename_prefix=plan.filename_prefix,
            )
            history_record = wait_for_completion(
                server_url=config.server_url,
                prompt_id=prompt_id,
                timeout_seconds=config.timeout_seconds,
                poll_seconds=config.poll_seconds,
                should_stop=should_stop,
            )
            video_paths = extract_video_paths(history_record, config.output_root)
            if not video_paths:
                raise RunnerError(
                    f"ComfyUI completed prompt {prompt_id}, but no video outputs were found in history."
                )
            wait_for_files(video_paths)
            write_sidecars(video_paths, plan)
            result = RunResult(
                prompt_number=plan.prompt.number,
                prompt_title=plan.prompt.title,
                variation=plan.variation,
                seed_1=plan.seed_1,
                seed_2=plan.seed_2,
                video_length_seconds=plan.video_length_seconds,
                prompt_id=prompt_id,
                filename_prefix=plan.filename_prefix,
                image_name=plan.image_name,
                output_paths=[str(path) for path in video_paths],
            )
            results.append(result)
            emit_progress(
                progress_callback,
                "run_completed",
                (
                    f"Completed prompt {plan.prompt.number} variation {plan.variation}: "
                    f"{', '.join(result.output_paths)}"
                ),
                total_runs=len(plans),
                completed_runs=len(results),
                run_index=index,
                prompt_number=plan.prompt.number,
                prompt_title=plan.prompt.title,
                variation=plan.variation,
                seed_1=plan.seed_1,
                seed_2=plan.seed_2,
                prompt_id=prompt_id,
                filename_prefix=plan.filename_prefix,
                output_paths=result.output_paths,
            )
    except StopRequestedError as exc:
        emit_progress(
            progress_callback,
            "batch_stopped",
            str(exc),
            total_runs=len(plans),
            completed_runs=len(results),
        )
        raise
    except Exception as exc:
        emit_progress(
            progress_callback,
            "batch_failed",
            str(exc),
            total_runs=len(plans),
            completed_runs=len(results),
        )
        raise

    emit_progress(
        progress_callback,
        "batch_completed",
        f"Completed {len(results)} run(s).",
        total_runs=len(plans),
        completed_runs=len(results),
    )
    return results


def run_result_to_dict(result: RunResult) -> dict[str, Any]:
    return asdict(result)
