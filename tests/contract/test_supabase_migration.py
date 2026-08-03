from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = (
    ROOT
    / "neveran-main-app"
    / "supabase"
    / "migrations"
    / "20260801090000_gazzetta_engine.sql"
)
ARTWORK_MIGRATION = (
    ROOT
    / "neveran-main-app"
    / "supabase"
    / "migrations"
    / "20260803120000_gazzetta_artwork_storage.sql"
)
QUEUE_MIGRATION = (
    ROOT
    / "neveran-main-app"
    / "supabase"
    / "migrations"
    / "20260803150000_gazzetta_generation_queue.sql"
)


def test_migration_copre_tabelle_rpc_e_rls() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for table in (
        "gazzetta_engine_state",
        "gazzetta_workers",
        "gazzetta_generation_jobs",
        "gazzetta_generation_runs",
        "gazzetta_storylines",
        "gazzetta_entities",
        "gazzetta_events",
        "gazzetta_editions",
        "gazzetta_audit_log",
    ):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql

    for rpc in (
        "gazzetta_worker_heartbeat",
        "lease_next_gazzetta_job",
        "renew_gazzetta_job_lease",
        "submit_gazzetta_run",
        "publish_gazzetta_edition",
        "fail_gazzetta_job",
        "gazzetta_get_editorial_context",
        "gazzetta_get_run",
        "gazzetta_maintain_retention",
        "admin_get_gazzetta_status",
        "admin_pause_gazzetta_engine",
        "admin_resume_gazzetta_engine",
        "admin_withdraw_current_gazzetta_edition",
        "admin_restore_gazzetta_edition",
    ):
        assert f"function public.{rpc}" in sql


def test_migration_non_espone_generate_now() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "function public.generate" not in sql
    assert "service_role" in sql  # documentato come identità vietata
    assert "is_gazzetta_worker()" in sql


def test_player_puo_leggere_soltanto_lo_snapshot_corrente() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "grant select (snapshot) on public.gazzetta_editions to authenticated" in sql
    assert "grant select on public.gazzetta_editions to authenticated" not in sql
    assert "using (status = 'published' and is_current)" in sql


def test_submit_e_publish_sono_idempotenti() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "attempt_content_conflict" in sql
    assert "where job_id = v_job.id and attempt_number = v_job.attempt_count" in sql
    assert "where e.generation_run_id = p_run_id and r.job_id = p_job_id" in sql
    assert "if found then return v_snapshot" in sql
    assert "policy_hash text not null" in sql
    assert "prompt_hashes jsonb not null" in sql
    assert "jsonb_object_length(p_prompt_hashes) <> 4" in sql
    assert "array['planner', 'writer', 'verifier', 'repair']" in sql


def test_dead_letter_avanza_il_calendario_senza_pubblicare() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "when v_terminal then public._gazzetta_next_slot" in sql
    assert "'job_dead_letter'" in sql
    assert "error_class = 'lease_exhausted'" in sql
    assert "attempt_count < max_attempts" in sql


def test_latest_due_revoca_anche_un_vecchio_lease_attivo() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "('queued', 'failed', 'leased', 'running')" in sql
    assert "job superato da una scadenza più recente" in sql
    assert "j.status = 'missed' and j.schedule_slot < v_latest" in sql


def test_publish_richiede_firme_visibili() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "raise exception 'invalid_byline'" in sql
    assert "raise exception 'invalid_byline_rotation'" in sql


def test_publish_riverifica_grounding_fonti_e_fake() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "raise exception 'invalid_event_classification'" in sql
    assert "raise exception 'invalid_diegetic_sources'" in sql
    assert "raise exception 'ungrounded_event'" in sql
    assert "raise exception 'invalid_fake_distribution'" in sql
    assert "raise exception 'invalid_fake_classification'" in sql
    assert "raise exception 'weak_diegetic_sources'" in sql


def test_hash_edizione_corrisponde_allo_snapshot_pubblicato() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "v_published_hash := encode(" in sql
    assert "extensions.digest(convert_to(v_snapshot::text, 'utf8'), 'sha256')" in sql
    assert "v_published_hash, v_run.id" in sql


def test_prima_edizione_puo_essere_ritirata_senza_cancellazione() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "previous_edition_not_found" not in sql
    assert "if v_previous.id is not null then" in sql


def test_prima_scadenza_sql_nasce_alle_sei_di_roma() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "function public._gazzetta_first_slot" in sql
    assert "public._gazzetta_first_slot(now(), 6, 0, 'europe/rome')" in sql
    assert "publication_minute integer not null default 0" in sql
    assert "v_state.max_job_attempts" in sql


def test_retention_compatta_filoni_e_svecchia_entita() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "p_storyline_compaction_days" in sql
    assert "where status = 'epilogue'" in sql
    assert "delete from public.gazzetta_entities" in sql


def test_artwork_storage_usa_bucket_pubblico_ma_scrittura_worker_only() -> None:
    sql = ARTWORK_MIGRATION.read_text(encoding="utf-8").lower()

    assert "'gazzetta-artwork'" in sql
    assert "6291456" in sql
    assert "public.is_gazzetta_worker()" in sql
    assert "for insert to authenticated" in sql
    assert "for delete to authenticated" in sql
    assert "x-upsert=false" in sql
    assert "service_role" not in sql


def test_coda_introduce_due_cursori_indipendenti() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "add column next_generation_slot timestamptz" in sql
    assert "add column queue_depth_target integer not null default 1" in sql
    assert "check (queue_depth_target between 1 and 10)" in sql


def test_archivio_pubblicato_visibile_a_tutti_non_solo_edizione_corrente() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "drop policy if exists gazzetta_editions_player_current" in sql
    assert "create policy gazzetta_editions_player_archive" in sql
    assert "using (status = 'published')" in sql
    assert "using (status = 'published' and is_current)" not in sql


def test_lease_next_e_guidato_dalla_profondita_coda_non_da_un_cursore_unico() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "function public.lease_next_gazzetta_job(p_worker_id text)" in sql
    assert "where status = 'validated'" in sql
    assert "if v_depth < v_state.queue_depth_target then" in sql
    assert "order by j.schedule_slot asc" in sql


def test_materialize_sostituisce_publish_e_non_stampa_la_data_di_pubblicazione() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "function public.materialize_gazzetta_edition(" in sql
    assert "drop function if exists public.publish_gazzetta_edition(uuid, text, uuid)" in sql
    assert "'validated', false" in sql
    assert "publicationdate" not in sql.split(
        "drop function if exists public.publish_gazzetta_edition"
    )[0].split("function public.materialize_gazzetta_edition(")[1]


def test_publish_next_stampa_la_data_e_solleva_queue_empty_se_la_coda_e_vuota() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "function public.publish_next_gazzetta_edition(p_worker_id text)" in sql
    assert "raise exception 'queue_empty'" in sql
    assert "{publicationdate}" in sql
    assert "order by issue_number asc" in sql


def test_publish_next_salta_gli_slot_scaduti_senza_recuperarli_in_burst() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "exit when v_next > now();" in sql


def test_fail_job_non_tocca_piu_il_cursore_di_pubblicazione() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()
    fail_job_section = sql.split("function public.fail_gazzetta_job(")[1].split(
        "function public.admin_get_gazzetta_status"
    )[0]

    assert "next_due_at" not in fail_job_section


def test_admin_status_espone_la_profondita_coda() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "'queuedepth'" in sql
    assert "'queuededitions'" in sql
    assert "where status = 'validated'" in sql


def test_worker_puo_leggere_la_profondita_coda_senza_ruolo_admin() -> None:
    sql = QUEUE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "function public.gazzetta_get_queue_status()" in sql
    assert "if not public.is_gazzetta_worker() then raise exception 'forbidden'; end if;" in (
        sql.split("function public.gazzetta_get_queue_status()")[1]
    )
    assert "'queuedepth', v_depth" in sql
    assert "'queuedepthtarget', v_state.queue_depth_target" in sql
