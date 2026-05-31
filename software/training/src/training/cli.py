"""`train` CLI — single entry point for the training pipeline.

Subcommands (some are stubs pending module implementation):

    pull       Pull samples + annotations from Hive into datasets/<zone>/
    build      Convert a pulled Hive dump into a YOLO-format dataset
    vastai     Provision a Vast.ai session and run a training track
    export     Produce runtime artifacts from a run (ONNX → NCNN/Hailo)
    publish    Publish a finished run to Hive's model catalog
    benchmark  Run the cross-device benchmark bundle
"""

from __future__ import annotations

import sys

import click


@click.group(help=__doc__)
def main() -> None:
    pass


@main.command("pull")
@click.option("--hive-url", required=True)
@click.option("--zone", required=True, help="classification_chamber | c_channel_2 | c_channel_3 | carousel | …")
@click.option("--source-role", default=None, help="Hive source_role filter (defaults to --zone)")
@click.option("--status", default="accepted", help="Sample review_status filter; pass empty string for any")
@click.option("--token", default=None, help="Hive API key; falls back to stored token")
def pull(hive_url: str, zone: str, source_role: str | None, status: str, token: str | None) -> None:
    """Pull reviewed samples from Hive into datasets/<zone>/raw/."""
    from training.hive import pull as pull_mod

    pull_mod.run(
        hive_url=hive_url,
        zone=zone,
        source_role=source_role,
        review_status=status or None,
        token=token,
    )


@main.command("build")
@click.option("--zone", required=True)
@click.option("--name", default=None, help="Dataset subdirectory under datasets/<zone>/ (default: v1)")
@click.option("--split", default=0.85, type=float, help="Train/val split ratio")
@click.option("--keep-empty", is_flag=True, help="Include samples with zero bounding boxes")
@click.option("--seed", default=42, type=int, help="Shuffle seed")
@click.option("--copy/--symlink", default=False, help="Copy images instead of symlinking")
@click.option(
    "--target-size",
    default=None,
    type=int,
    help="Cap dataset size via YOLO-embedding farthest-point sampling (drops near-duplicates)",
)
@click.option(
    "--embed-model",
    default="yolo11n.pt",
    help="Ultralytics model weights used as feature extractor for --target-size",
)
@click.option(
    "--balance-source-role",
    is_flag=True,
    help="When using --target-size, keep source_role groups (e.g. c_channel_2/3) balanced before diversity sampling.",
)
@click.option(
    "--strict-source-role-balance",
    "--strict-balance",
    "strict_source_role_balance",
    is_flag=True,
    help="Fail the build if any balance group lacks enough samples for an equal share of --target-size.",
)
@click.option(
    "--balance-piece-count",
    is_flag=True,
    help="When using --target-size, also balance by number of pieces in the frame.",
)
@click.option(
    "--balance-machine",
    is_flag=True,
    help="When using --target-size, also balance by source machine so one rig can't dominate the picks.",
)
@click.option(
    "--piece-count-bins",
    default=None,
    help="Comma-separated piece-count buckets for --balance-piece-count, e.g. 0,1,2,3,4,5,6,7,8,9-12,13+.",
)
@click.option(
    "--min-detection-score",
    default=None,
    type=float,
    help="Only include positive samples with detection_score >= this value; empty samples are kept.",
)
@click.option(
    "--max-empty-fraction",
    default=None,
    type=float,
    help="When --keep-empty is set, cap empties so they are at most this fraction of the final dataset (e.g. 0.1 = 10%%). Empties are randomly subsampled; positives are kept (after diversity sampling).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Skip the expensive embedding + dataset write. Print the projected "
         "per-machine + per-balance-group selection counts for the given "
         "--target-size + balance flags, then exit. Lets you pick a sensible "
         "target before committing to a multi-minute build.",
)
@click.option(
    "--raw-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Override raw dataset directory containing manifest.json.",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False, dir_okay=True),
    help="Override output dataset directory.",
)
@click.option(
    "--exclude-algorithm-prefix",
    "exclude_algorithm_prefixes",
    multiple=True,
    help="Drop samples whose detection_algorithm starts with this prefix (repeatable, e.g. 'bundled:' 'hive:').",
)
@click.option(
    "--prioritize-machine",
    "prioritize_machine_ids",
    multiple=True,
    help="Force-include ALL samples from this machine_id UUID; only the rest are subject to --target-size diversity sampling (repeatable).",
)
@click.option(
    "--include-source-role",
    "include_source_roles",
    multiple=True,
    help="Only include samples with this source_role (repeatable). Lets one shared --raw-dir feed multiple zone builds.",
)
def build(
    zone: str,
    name: str | None,
    split: float,
    keep_empty: bool,
    seed: int,
    copy: bool,
    target_size: int | None,
    embed_model: str,
    balance_source_role: bool,
    strict_source_role_balance: bool,
    balance_piece_count: bool,
    balance_machine: bool,
    piece_count_bins: str | None,
    min_detection_score: float | None,
    max_empty_fraction: float | None,
    dry_run: bool,
    raw_dir: str | None,
    output_dir: str | None,
    exclude_algorithm_prefixes: tuple[str, ...],
    prioritize_machine_ids: tuple[str, ...],
    include_source_roles: tuple[str, ...],
) -> None:
    """Build YOLO-format dataset from a pulled Hive dump."""
    if strict_source_role_balance and not (
        balance_source_role or balance_piece_count or balance_machine
    ):
        raise click.ClickException(
            "--strict-balance requires --balance-source-role, --balance-piece-count, or --balance-machine"
        )
    if max_empty_fraction is not None:
        if not keep_empty:
            raise click.ClickException("--max-empty-fraction requires --keep-empty")
        if not 0.0 <= max_empty_fraction < 1.0:
            raise click.ClickException("--max-empty-fraction must be in [0.0, 1.0)")

    from training.datasets import build as build_mod
    from pathlib import Path

    if dry_run:
        build_mod.preview(
            zone=zone,
            keep_empty=keep_empty,
            target_size=target_size,
            balance_source_role=balance_source_role,
            balance_piece_count=balance_piece_count,
            balance_machine=balance_machine,
            piece_count_bins=piece_count_bins or build_mod.DEFAULT_PIECE_COUNT_BINS,
            min_detection_score=min_detection_score,
            max_empty_fraction=max_empty_fraction,
            raw_dir=Path(raw_dir) if raw_dir else None,
        )
        return

    build_mod.run(
        zone=zone,
        name=name,
        train_ratio=split,
        keep_empty=keep_empty,
        seed=seed,
        symlink_images=not copy,
        target_size=target_size,
        embed_model=embed_model,
        balance_source_role=balance_source_role,
        balance_piece_count=balance_piece_count,
        balance_machine=balance_machine,
        piece_count_bins=piece_count_bins or build_mod.DEFAULT_PIECE_COUNT_BINS,
        strict_source_role_balance=strict_source_role_balance,
        min_detection_score=min_detection_score,
        max_empty_fraction=max_empty_fraction,
        raw_dir=Path(raw_dir) if raw_dir else None,
        output_dir=Path(output_dir) if output_dir else None,
        exclude_algorithm_prefixes=exclude_algorithm_prefixes,
        prioritize_machine_ids=prioritize_machine_ids,
        include_source_roles=include_source_roles,
    )


@main.group("lambda")
def lambda_group() -> None:
    """Lambda Labs GPU pipeline (manual provision, end-to-end run)."""


@lambda_group.command("run")
@click.option("--host", required=True, help="ssh target, e.g. ubuntu@157.151.159.81")
@click.option("--zone", required=True, help="Hive zone (c_channel | classification_channel | ...)")
@click.option("--dataset-name", required=True, help="Dataset subdir under datasets/<zone>/")
@click.option("--bundle-name", required=True, help="Output bundle dir name (also remote runs subdir)")
@click.option("--model-id", default="A3", help="YOLO model id (A1..A8, see scripts/lambda/train_export.py)")
@click.option("--epochs", default=300, type=int)
@click.option("--target-size", default=None, type=int, help="Diversity-sample to this many positives in `train build`")
@click.option("--min-detection-score", default=0.98, type=float)
@click.option("--calibration-count", default=150, type=int)
@click.option("--target-platform", default="rk3588")
@click.option("--quantization", type=click.Choice(["i8", "fp"]), default="i8")
@click.option("--hive-url", default="https://hive.basically.website")
@click.option("--output-root", default="/Volumes/T7/sorter-v2-vision-models", type=click.Path())
@click.option("--no-head-strip", is_flag=True, help="Disable Detect.forward monkeypatch (stock ONNX).")
@click.option(
    "--activation",
    type=click.Choice(["silu", "relu6"]),
    default="silu",
    help="Activation function. relu6 trains from scratch with ReLU6 (quant-friendly, no pretrained weights).",
)
@click.option("--skip-pull", is_flag=True, help="Skip `train pull` (assume samples already on box).")
@click.option("--skip-build", is_flag=True, help="Skip `train build` (assume dataset already on box).")
@click.option(
    "--build-flag",
    "build_flags",
    multiple=True,
    help="Extra flag forwarded to `train build` (repeat). Default: --balance-source-role.",
)
@click.option("--no-status-server", is_flag=True, help="Disable the localhost live-progress web page.")
@click.option("--status-port", default=0, type=int, help="Pin the status server to a specific port (0 = auto).")
def lambda_run(
    host: str,
    zone: str,
    dataset_name: str,
    bundle_name: str,
    model_id: str,
    epochs: int,
    target_size: int | None,
    min_detection_score: float,
    calibration_count: int,
    target_platform: str,
    quantization: str,
    hive_url: str,
    output_root: str,
    no_head_strip: bool,
    activation: str,
    skip_pull: bool,
    skip_build: bool,
    build_flags: tuple[str, ...],
    no_status_server: bool,
    status_port: int,
) -> None:
    """End-to-end r3 pipeline on a Lambda Labs host: pull → build → train → export → RKNN → bundle on T7."""
    from pathlib import Path

    from training.lambda_.run import LambdaRunConfig, runLambdaPipeline
    from training.lambda_.status import PipelineStatus

    cfg = LambdaRunConfig(
        host=host,
        zone=zone,
        dataset_name=dataset_name,
        bundle_name=bundle_name,
        model_id=model_id,
        epochs=epochs,
        target_size=target_size,
        min_detection_score=min_detection_score,
        calibration_count=calibration_count,
        target_platform=target_platform,
        quantization=quantization,
        hive_url=hive_url,
        output_root=Path(output_root),
        head_stripped=not no_head_strip,
        activation=activation,
        skip_pull=skip_pull,
        skip_build=skip_build,
        extra_build_flags=list(build_flags) if build_flags else ["--balance-source-role"],
    )
    if no_status_server:
        runLambdaPipeline(cfg)
        return
    with PipelineStatus(port=status_port, open_browser=True) as status:
        runLambdaPipeline(cfg, status=status)


@main.group("vastai")
def vastai_group() -> None:
    """Vast.ai GPU session + training tracks."""


@vastai_group.command("package")
@click.option("--zone", required=True)
@click.option("--name", "dataset_name", default="v1", help="Dataset subdir under datasets/<zone>/")
@click.option("--track", type=click.Choice(["yolo", "nanodet", "rfdetr"]), default="yolo")
@click.option("--model-ids", multiple=True, help="Optional track-script model IDs (e.g. A3 A5)")
@click.option("--output", default=None, type=click.Path(), help="Target tarball path")
def vastai_package(
    zone: str,
    dataset_name: str,
    track: str,
    model_ids: tuple[str, ...],
    output: str | None,
) -> None:
    """Create a self-contained tarball (dataset + track script + README)."""
    from pathlib import Path

    from training.vastai import train as vt

    vt.package(
        zone=zone,
        dataset_name=dataset_name,
        track=track,
        model_ids=list(model_ids) or None,
        output=Path(output) if output else None,
    )


@vastai_group.command("offers")
@click.option("--query", default=None, help="Override the default vastai search query")
@click.option("--order", default="dph_total")
@click.option("--limit", default=5, type=int)
def vastai_offers(query: str | None, order: str, limit: int) -> None:
    """List affordable Vast.ai offers for GPU training."""
    from training.vastai import train as vt

    vt.offers(query=query or vt.DEFAULT_OFFERS_QUERY, order=order, limit=limit)


@vastai_group.command("fetch")
@click.option("--instance", "instance_id", required=True, help="Vast.ai instance id")
@click.option("--zone", required=True)
@click.option("--track", type=click.Choice(["yolo", "nanodet", "rfdetr"]), default="yolo")
@click.option("--dataset-name", default=None)
@click.option("--remote-dir", default="/workspace/results")
def vastai_fetch(
    instance_id: str,
    zone: str,
    track: str,
    dataset_name: str | None,
    remote_dir: str,
) -> None:
    """Fetch /workspace/results from a running instance into runs/<timestamp>-<zone>-<track>/."""
    from training.vastai import train as vt

    vt.fetch(
        instance_id=instance_id,
        zone=zone,
        track=track,
        dataset_name=dataset_name,
        remote_results_dir=remote_dir,
    )


@main.group("export")
def export_group() -> None:
    """Produce runtime artifacts from a training run."""


@export_group.command("hailo")
@click.option("--run-dir", required=True, type=click.Path(exists=True))
@click.option("--zone", required=True)
def export_hailo(run_dir: str, zone: str) -> None:
    """Build a Hailo compile bundle from a training run."""
    from training.exports import hailo

    click.echo(f"[stub] delegating to {hailo.__name__}.main with --run-dir {run_dir} --zone {zone}", err=True)
    sys.exit(2)


@export_group.command("rknn")
@click.option("--preset", required=True, help="One of training.exports.rknn.PRESETS")
@click.option("--output-dir", default=None, type=click.Path(), help="Override bundle output dir.")
@click.option("--archive", is_flag=True, help="Also create a .tar.gz next to the bundle directory.")
def export_rknn(preset: str, output_dir: str | None, archive: bool) -> None:
    """Build a Rockchip RKNN compile bundle from a training run."""
    from training.exports import rknn as rknn_mod

    if preset not in rknn_mod.PRESETS:
        raise click.ClickException(
            f"Unknown RKNN preset {preset!r}. Available: {sorted(rknn_mod.PRESETS)}"
        )
    args = ["build", "--preset", preset]
    if output_dir:
        args += ["--output-dir", output_dir]
    if archive:
        args += ["--archive"]
    sys.argv = ["rknn", *args]
    sys.exit(rknn_mod.main())


@main.group("auth")
def auth_group() -> None:
    """Manage stored Hive API keys for the CLI."""


@auth_group.command("login")
@click.option("--hive-url", required=True)
@click.option("--token", default=None, help="Hive personal access token (hv_…). Prompts if omitted.")
def auth_login(hive_url: str, token: str | None) -> None:
    """Store a Hive API key for a given Hive URL."""
    import getpass

    from training import auth

    if token is None:
        token = getpass.getpass("Paste Hive token (hv_…): ").strip()
    if not token.startswith("hv_"):
        raise click.ClickException("Token must start with 'hv_'")
    auth.set_token(hive_url, token)
    click.echo(f"Stored token for {hive_url}")


@auth_group.command("status")
def auth_status() -> None:
    """List stored Hive URLs + token prefixes."""
    from training import auth

    entries = auth.list_targets()
    if not entries:
        click.echo("No stored tokens.")
        return
    for entry in entries:
        click.echo(f"  {entry['url']}  {entry['token_prefix']}  (added {entry['added_at']})")


@auth_group.command("logout")
@click.option("--hive-url", required=True)
def auth_logout(hive_url: str) -> None:
    """Forget the stored token for a Hive URL."""
    from training import auth

    if auth.delete_token(hive_url):
        click.echo(f"Removed token for {hive_url}")
    else:
        click.echo(f"No token stored for {hive_url}", err=True)
        sys.exit(1)


@main.command("compose-metadata")
@click.option("--run-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--dataset-dir", required=True, type=click.Path(exists=True, file_okay=False))
@click.option("--benchmark-json", default=None, type=click.Path(exists=True, dir_okay=False))
@click.option("--model-key", default=None, help="Track-results key (e.g. A7); defaults to the first entry.")
def compose_metadata(run_dir: str, dataset_dir: str, benchmark_json: str | None, model_key: str | None) -> None:
    """Write the standard training_metadata block into <run-dir>/run.json."""
    from pathlib import Path

    from training.datasets import compose_metadata as cm

    meta = cm.compose(
        run_dir=Path(run_dir),
        dataset_dir=Path(dataset_dir),
        benchmark_json=Path(benchmark_json) if benchmark_json else None,
        model_key=model_key,
    )
    click.echo(
        f"composed training_metadata: target_size={meta['dataset']['selection']['target_size']} "
        f"benchmarks={'yes' if meta.get('benchmarks') else 'no'}"
    )


@main.command("publish")
@click.option("--run-dir", required=True, type=click.Path(exists=True))
@click.option("--hailo-bundle", default=None, type=click.Path(exists=True))
@click.option("--slug", required=True)
@click.option("--scopes", default="")
@click.option("--hive-url", required=True)
@click.option("--token", default=None, help="Hive API key; falls back to stored token for this URL.")
@click.option("--email", default=None, help="(Legacy) email for cookie-based login")
@click.option("--password-env", default=None, help="(Legacy) env var with cookie-login password")
@click.option("--name", default=None)
@click.option("--description", default=None)
@click.option("--family", default=None)
@click.option("--public/--private", default=True)
@click.option(
    "--dataset-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="If set, compose the standard training_metadata from this dataset's build.json before publishing.",
)
@click.option(
    "--benchmark-json",
    default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Optional onnxruntime benchmark JSON to include in the composed metadata.",
)
@click.option("--model-key", default=None, help="Track-results key (e.g. A7) when --dataset-dir is set.")
def publish(**kwargs) -> None:
    """Upload a finished run (ONNX + NCNN + optional HEF) to Hive.

    Pass --dataset-dir to auto-compose the structured training_metadata that
    the Hive model detail page expects (model.best_metrics, dataset.selection,
    benchmarks). Without it the existing run.json training_metadata is sent
    verbatim.
    """
    from pathlib import Path

    dataset_dir = kwargs.pop("dataset_dir", None)
    benchmark_json = kwargs.pop("benchmark_json", None)
    model_key = kwargs.pop("model_key", None)

    if dataset_dir:
        from training.datasets import compose_metadata as cm

        cm.compose(
            run_dir=Path(kwargs["run_dir"]),
            dataset_dir=Path(dataset_dir),
            benchmark_json=Path(benchmark_json) if benchmark_json else None,
            model_key=model_key,
        )

    from training.hive import publish as publish_mod

    sys.exit(publish_mod.cli(kwargs))


@main.command("benchmark")
@click.argument("args", nargs=-1)
def benchmark(args: tuple[str, ...]) -> None:
    """Run the device detector benchmark (pass-through to the legacy script)."""
    from training.reports import benchmark as bench

    sys.argv = ["benchmark", *args]
    bench.main()


if __name__ == "__main__":
    main()
