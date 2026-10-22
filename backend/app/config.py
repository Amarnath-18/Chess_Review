from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+psycopg://chess:change-me@db:5432/chess"
    stockfish_path: str = "/usr/games/stockfish"

    default_depth: int = 16
    max_depth: int = 22
    max_nodes: int = 5_000_000
    max_plies: int = 300
    max_multipv: int = 5  # most engine lines a user can request per position
    analysis_job_timeout_seconds: int = 600  # minimum time limit for a job
    job_seconds_per_position: float = 15.0  # ...or this much per position, if that is more
    engine_threads: int = 1
    engine_hash_mb: int = 128
    max_seconds_per_position: float = 30.0
    # A position that exceeds its time cap by this much means the engine is hung: it is killed.
    engine_hang_grace_seconds: float = 30.0

    # Job queue
    max_active_jobs_per_user: int = 2
    max_queue_length: int = 50
    job_max_attempts: int = 2
    # Analyze-all: most games one batch may hold
    batch_max_games: int = 100
    # "Analyze new games automatically": most games queued by one import
    auto_analyze_max_per_import: int = 20
    job_stale_seconds: int = 120
    worker_poll_seconds: float = 1.0
    maintenance_interval_seconds: float = 15.0

    # External game sources (public APIs only; fixed hosts, never a user-supplied URL)
    chesscom_base_url: str = "https://api.chess.com"
    lichess_base_url: str = "https://lichess.org"
    # Chess.com asks API clients to identify themselves; set a contact in .env if you can.
    external_user_agent: str = "ChessReviewLab/0.1 (personal project)"
    external_timeout_seconds: float = 20.0
    external_max_bytes: int = 25_000_000  # abort absurdly large upstream responses
    external_max_games: int = 50  # most games one preview/import may touch
    chesscom_max_archives: int = 12  # months scanned for a username preview
    chesscom_url_scan_archives: int = 36  # months scanned to find a game from its link
    external_min_interval_seconds: float = 0.5  # pause between calls to one upstream
    external_user_cooldown_seconds: float = 2.0  # per-user minimum gap between lookups
    preview_cache_seconds: int = 600

    # "production" refuses to start with the placeholder database password
    environment: str = "development"
    max_request_bytes: int = 1_500_000  # largest request body accepted (a 1 MB PGN + overhead)
    max_games_per_user: int = 5000  # saved games per anonymous user
    sessions_per_ip_per_hour: int = 0  # new anonymous sessions per IP; 0 = unlimited (local use)

    cookie_secure: bool = False
    retention_days: int = 30  # anonymous data is deleted after this many days without a visit
    # Private server: every request needs a session that unlocked a (non-revoked) invite code.
    access_required: bool = False

    # AI explanations via OpenRouter (https://openrouter.ai). Off unless LLM_MODEL and LLM_API_KEY are set.
    llm_base_url: str = "https://openrouter.ai/api/v1"  # any OpenAI-compatible endpoint works
    llm_model: str = ""
    llm_api_key: str = ""
    llm_provider_label: str = ""  # named in the privacy notice; empty = derived from the URL (OpenRouter)
    llm_json_mode: bool = False  # many free models reject response_format; replies are parsed and checked anyway
    llm_max_tokens: int = 1200  # reasoning models spend part of this thinking before they answer
    llm_timeout_seconds: float = 60.0
    llm_requests_per_minute: int = 10  # server-wide, kept under the provider free quota; 0 = unlimited
    explain_daily_limit_per_user: int = 30  # per invite code when the gate is on, else per browser
    retention_purge_interval_seconds: int = 3600
    export_max_games: int = 5000
    default_multipv: int = 3  # engine lines when the user has not chosen
    default_import_count: int = 20  # games fetched per Chess.com / Lichess search

    @model_validator(mode="after")
    def _no_placeholder_secrets_in_production(self) -> "Settings":
        if self.environment.lower() == "production" and "change-me" in self.database_url:
            raise ValueError(
                "ENVIRONMENT=production but the database still uses the placeholder password "
                "'change-me'. Set a real POSTGRES_PASSWORD in .env."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
