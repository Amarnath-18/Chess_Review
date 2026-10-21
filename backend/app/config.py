from functools import lru_cache

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
    analysis_job_timeout_seconds: int = 600
    engine_threads: int = 1
    engine_hash_mb: int = 128
    max_seconds_per_position: float = 30.0
    # A position that exceeds its time cap by this much means the engine is hung: it is killed.
    engine_hang_grace_seconds: float = 30.0

    # Job queue
    max_active_jobs_per_user: int = 2
    max_queue_length: int = 50
    job_max_attempts: int = 2
    job_stale_seconds: int = 120
    worker_poll_seconds: float = 1.0
    maintenance_interval_seconds: float = 15.0

    cookie_secure: bool = False
    retention_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
