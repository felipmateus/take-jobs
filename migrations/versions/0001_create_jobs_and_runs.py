"""create jobs and collection runs

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # `unaccent` is only STABLE; generated columns and indexes need an IMMUTABLE wrapper (ADR-005).
    """
    CREATE FUNCTION immutable_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$ SELECT public.unaccent('public.unaccent', $1) $$
    """,
    """
    CREATE TABLE jobs (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        source varchar(32) NOT NULL,
        external_id varchar(64) NOT NULL,
        title text NOT NULL,
        company text,
        location text,
        description text,
        published_label text,
        url text NOT NULL,
        seniority varchar(8),
        first_seen_at timestamptz NOT NULL,
        last_seen_at timestamptz NOT NULL,
        search_text text GENERATED ALWAYS AS (
            immutable_unaccent(lower(
                title || ' ' || coalesce(company, '') || ' ' || coalesce(description, '')
            ))
        ) STORED,
        CONSTRAINT ck_jobs_seniority
            CHECK (seniority IN ('intern', 'junior', 'mid', 'senior')),
        CONSTRAINT uq_jobs_source_external_id UNIQUE (source, external_id)
    )
    """,
    """
    CREATE INDEX ix_jobs_recency
        ON jobs (last_seen_at DESC, first_seen_at DESC, id DESC)
    """,
    "CREATE INDEX ix_jobs_search_text_trgm ON jobs USING gin (search_text gin_trgm_ops)",
    """
    CREATE INDEX ix_jobs_location_trgm
        ON jobs USING gin ((immutable_unaccent(lower(location))) gin_trgm_ops)
    """,
    "CREATE INDEX ix_jobs_source ON jobs (source)",
    "CREATE INDEX ix_jobs_seniority ON jobs (seniority)",
    """
    CREATE TABLE collection_runs (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        trigger varchar(16) NOT NULL,
        status varchar(16) NOT NULL,
        started_at timestamptz NOT NULL,
        finished_at timestamptz,
        error text,
        expected_combinations integer NOT NULL,
        CONSTRAINT ck_collection_runs_trigger
            CHECK (trigger IN ('scheduled', 'startup', 'manual')),
        CONSTRAINT ck_collection_runs_status
            CHECK (status IN ('running', 'success', 'partial', 'failed')),
        CONSTRAINT ck_collection_runs_expected_combinations CHECK (expected_combinations > 0)
    )
    """,
    # Safety Invariant 1: the database allows a single running run.
    """
    CREATE UNIQUE INDEX uq_collection_runs_single_running
        ON collection_runs (status) WHERE status = 'running'
    """,
    "CREATE INDEX ix_collection_runs_started_at ON collection_runs (started_at DESC)",
    """
    CREATE TABLE collection_run_results (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        run_id bigint NOT NULL REFERENCES collection_runs (id) ON DELETE CASCADE,
        source varchar(32) NOT NULL,
        term text NOT NULL,
        status varchar(8) NOT NULL,
        pages integer NOT NULL,
        new_count integer NOT NULL,
        seen_again_count integer NOT NULL,
        discarded_count integer NOT NULL,
        error text,
        CONSTRAINT ck_run_results_status CHECK (status IN ('success', 'failed')),
        CONSTRAINT ck_run_results_pages CHECK (pages >= 0),
        CONSTRAINT ck_run_results_new_count CHECK (new_count >= 0),
        CONSTRAINT ck_run_results_seen_again_count CHECK (seen_again_count >= 0),
        CONSTRAINT ck_run_results_discarded_count CHECK (discarded_count >= 0),
        CONSTRAINT uq_run_results_combination UNIQUE (run_id, source, term)
    )
    """,
)

_DOWNGRADE_STATEMENTS = (
    "DROP TABLE collection_run_results",
    "DROP TABLE collection_runs",
    "DROP TABLE jobs",
    "DROP FUNCTION immutable_unaccent(text)",
    "DROP EXTENSION pg_trgm",
    "DROP EXTENSION unaccent",
)


def upgrade() -> None:
    for statement in _STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
