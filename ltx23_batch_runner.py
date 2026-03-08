from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from pathlib import Path

from ltx23_batch_core import (
    BatchConfig,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PROMPTS,
    DEFAULT_SERVER_URL,
    DEFAULT_VARIATIONS,
    DEFAULT_WORKFLOW,
    RunnerError,
    get_template_default_image,
    load_json,
    run_batch,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-generate LTX 2.3 prompt variations through the ComfyUI API."
    )
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS)
    parser.add_argument("--image", help="Input image filename already present in the ComfyUI input folder.")
    parser.add_argument("--variations", type=int, default=DEFAULT_VARIATIONS)
    parser.add_argument(
        "--prompt-numbers",
        help="Optional prompt numbers/ranges to run, for example: 1,3,5-7",
    )
    parser.add_argument(
        "--seed-base",
        type=int,
        help="Optional deterministic seed source. Reusing it reproduces the same seed pairs.",
    )
    parser.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--dry-run-dir",
        type=Path,
        help="If set with --dry-run, write generated payloads and sidecars to this local folder.",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> BatchConfig:
    return BatchConfig(
        workflow=args.workflow,
        prompts=args.prompts,
        image=args.image,
        variations=args.variations,
        prompt_numbers=args.prompt_numbers,
        seed_base=args.seed_base,
        server_url=args.server_url,
        output_root=args.output_root,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
        dry_run=args.dry_run,
        dry_run_dir=args.dry_run_dir,
    )


def run_cli(config: BatchConfig) -> int:
    template = load_json(config.workflow)
    default_image = config.image or get_template_default_image(template)
    if not default_image:
        raise RunnerError("No input image was provided and the workflow template does not define one.")

    def on_progress(event) -> None:
        if event.event_type == "batch_planned":
            print(f"Prepared {event.total_runs or 0} run(s).")
            return
        if event.event_type in {"run_started", "run_completed", "dry_run_written", "batch_failed"}:
            print(event.message)
            return
        if event.event_type == "run_queued" and event.prompt_id:
            print(
                f"Queued prompt {event.prompt_number} variation {event.variation} "
                f"as {event.prompt_id}"
            )

    results = run_batch(config, progress_callback=on_progress)
    if not config.dry_run:
        print(f"Finished {len(results)} run(s) using image {default_image}.")
    return 0


def main() -> int:
    args = parse_args()
    try:
        return run_cli(build_config(args))
    except RunnerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
