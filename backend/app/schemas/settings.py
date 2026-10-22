from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SettingsOut(BaseModel):
    # the user's effective preferences
    default_depth: int
    default_multipv: int
    import_count: int
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


class DeletedOut(BaseModel):
    deleted: int
