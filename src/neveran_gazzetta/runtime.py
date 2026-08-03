from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr

from neveran_gazzetta.application.contracts import Pipeline
from neveran_gazzetta.artwork.cloudflare import CloudflareArtworkClient
from neveran_gazzetta.artwork.service import SupabaseBackedArtworkService
from neveran_gazzetta.artwork.supabase import SupabaseArtworkStore
from neveran_gazzetta.config import AppConfig, load_config
from neveran_gazzetta.domain.errors import ConfigurationError
from neveran_gazzetta.generation.groq import GroqJsonClient
from neveran_gazzetta.generation.pipeline import GazzettaGenerationPipeline
from neveran_gazzetta.retrieval.core_adapter import GazzettaRetrievalAdapter
from neveran_gazzetta.retrieval.service import EditorialRetrievalService
from neveran_gazzetta.storage.supabase import SupabaseRpcClient
from neveran_gazzetta.telemetry import MonitorTelemetry, NullTelemetry, TelemetrySink
from neveran_gazzetta.worker.runner import GazzettaWorker


def _required(value: str | None, name: str) -> str:
    if not value:
        raise ConfigurationError(f"{name} obbligatorio per avviare il runtime")
    return value


def _secret(value: SecretStr | None, name: str) -> str:
    if value is None:
        raise ConfigurationError(f"{name} obbligatorio per avviare il runtime")
    return value.get_secret_value()


@dataclass(frozen=True)
class LiveRuntime:
    config: AppConfig
    control: SupabaseRpcClient
    retrieval: GazzettaRetrievalAdapter
    pipeline: Pipeline
    groq: GroqJsonClient
    worker: GazzettaWorker
    telemetry: TelemetrySink
    artwork: SupabaseBackedArtworkService | None


def build_live_runtime(root: Path | None = None) -> LiveRuntime:
    project_root = root or Path(os.getenv("GAZZETTA_ROOT", Path.cwd())).resolve()
    config = load_config(project_root, require_live_secrets=True)
    secrets = config.secrets
    retrieval_config = config.runtime.retrieval
    generation = config.runtime.generation

    try:
        from neveran_knowledge.retrieval_core.adapters import (
            JinaQueryEmbedder,
            JsonReleaseProvider,
            QdrantReadOnlyStore,
        )
    except ImportError as exc:
        raise ConfigurationError("neveran-knowledge-engine non installato") from exc

    collection = secrets.qdrant_collection or retrieval_config.collection_default
    embedding_model = (
        secrets.jina_embedding_model or retrieval_config.embedding_model_default
    )
    dimension = secrets.embedding_dimension or retrieval_config.embedding_dimension_default
    query_task = secrets.jina_query_task or retrieval_config.query_task_default
    embedder = JinaQueryEmbedder(
        api_key=_secret(secrets.jina_api_key, "JINA_API_KEY"),
        model=embedding_model,
        task=query_task,
        dimension=dimension,
    )
    store = QdrantReadOnlyStore(
        url=_required(secrets.qdrant_url, "QDRANT_URL"),
        api_key=_secret(secrets.qdrant_api_key, "QDRANT_API_KEY"),
        collection=collection,
    )
    releases = JsonReleaseProvider(
        Path(_required(secrets.corpus_release_manifest_path, "CORPUS_RELEASE_MANIFEST_PATH")),
        expected_collection=collection,
        expected_model=embedding_model,
        expected_dimension=dimension,
    )
    retrieval = GazzettaRetrievalAdapter(
        embedder=embedder,
        store=store,
        releases=releases,
        limits=retrieval_config,
    )
    retrieval_service = EditorialRetrievalService(retrieval, retrieval_config)
    supabase_url = _required(secrets.supabase_url, "SUPABASE_URL")
    supabase_anon_key = _secret(secrets.supabase_anon_key, "SUPABASE_ANON_KEY")
    control = SupabaseRpcClient(
        url=supabase_url,
        anon_key=supabase_anon_key,
        email=_required(secrets.worker_email, "GAZZETTA_WORKER_EMAIL"),
        password=_secret(secrets.worker_password, "GAZZETTA_WORKER_PASSWORD"),
    )
    groq = GroqJsonClient(api_key=_secret(secrets.groq_api_key, "GROQ_API_KEY"))
    artwork: SupabaseBackedArtworkService | None = None
    if config.editorial.artwork.generation_enabled:
        artwork_config = config.runtime.artwork
        generator = CloudflareArtworkClient(
            base_url=_required(secrets.artwork_worker_url, "GAZZETTA_IMAGE_WORKER_URL"),
            token=_secret(secrets.artwork_worker_token, "GAZZETTA_IMAGE_WORKER_TOKEN"),
            expected_model=artwork_config.model,
            expected_width=artwork_config.width,
            expected_height=artwork_config.height,
            timeout_seconds=artwork_config.request_timeout_seconds,
            max_retries=artwork_config.max_retries,
        )
        artwork_store = SupabaseArtworkStore(
            url=supabase_url,
            anon_key=supabase_anon_key,
            token_provider=control.access_token,
            bucket=artwork_config.storage_bucket,
            max_stored_images=artwork_config.max_stored_images,
            expected_model=artwork_config.model,
            expected_width=artwork_config.width,
            expected_height=artwork_config.height,
        )
        artwork = SupabaseBackedArtworkService(generator=generator, store=artwork_store)
    pipeline = GazzettaGenerationPipeline(
        config=config,
        state_provider=control,
        retrieval_adapter=retrieval,
        retrieval_service=retrieval_service,
        groq=groq,
        prompts_root=project_root / "prompts",
        artwork_generator=artwork,
    )
    telemetry: TelemetrySink
    if config.runtime.telemetry.enabled:
        telemetry = MonitorTelemetry(
            url=_required(secrets.monitor_url, "NEVERAN_MONITOR_URL"),
            token=_secret(secrets.monitor_token, "NEVERAN_MONITOR_TOKEN"),
            environment=secrets.environment,
            buffer_path=Path(
                os.getenv(
                    "GAZZETTA_TELEMETRY_BUFFER_PATH",
                    str(project_root / "runtime" / "monitor-buffer.jsonl"),
                )
            ),
        )
    else:
        telemetry = NullTelemetry()
    models = {
        "planner": secrets.groq_planner_model or generation.planner_model_default,
        "writer": secrets.groq_writer_model or generation.writer_model_default,
        "verifier": secrets.groq_verifier_model or generation.verifier_model_default,
    }
    worker = GazzettaWorker(
        worker_id=os.getenv("GAZZETTA_WORKER_ID", "neveranforge-gazzetta-1"),
        control=control,
        pipeline=pipeline,
        lease_renew_seconds=config.runtime.worker.heartbeat_seconds,
        models=models,
        telemetry=telemetry,
        retention_days=config.runtime.retention.detailed_run_logs_days,
        storyline_compaction_days=config.runtime.retention.storyline_compaction_days,
        recurring_inactive_issues=config.runtime.retention.recurring_inactive_issues,
        nonrecurring_keep_issues=config.runtime.retention.nonrecurring_keep_issues,
    )
    return LiveRuntime(config, control, retrieval, pipeline, groq, worker, telemetry, artwork)
