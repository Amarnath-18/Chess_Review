from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class SettingsOut(BaseModel):
    # the user's effective preferences
    default_depth: int
    default_multipv: int
    import_count: int
    auto_analyze: bool  # analyze newly imported games automatically
    my_names: list[str] = []  # how the person is named in their games
    # AI explanations: what this server offers and what the person chose
    ai_available: bool = False
    ai_explanations: bool = False
    explain_level: str = "intermediate"
    ai_provider: str = "OpenRouter"  # who receives the positions when it is on
    explain_daily_limit: int = 0
    # facts about this server, so the UI can offer only valid choices
    max_depth: int
    max_multipv: int
    retention_days: int


class SettingsUpdate(BaseModel):
    """Only the fields sent are changed. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    default_depth: int | None = Field(None, ge=1)
    default_multipv: int | None = Field(None, ge=1)
    import_count: Literal[10, 20, 50] | None = None
    auto_analyze: StrictBool | None = None
    my_names: list[str] | None = Field(None, max_length=5)
    ai_explanations: StrictBool | None = None
    explain_level: Literal["beginner", "intermediate", "advanced"] | None = None


class DeletedOut(BaseModel):
    deleted: int
