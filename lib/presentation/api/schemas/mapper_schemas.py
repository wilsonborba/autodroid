from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MapperRunRequest(BaseModel):
    package_name: str
    mode: str = "light"
    skip_dangerous_actions: bool = True


class MapperRunResponse(BaseModel):
    session_id: int
    package_name: str
    mode: str
    screens_recorded: int
    actions_executed: int
    scrolls_used: int
    revisited_screens: int
    status: str


class MapperSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    package_name: str
    mode: str
    status: str
    skip_dangerous_actions: bool
    max_depth: int
    max_actions: int
    max_scrolls: int
    created_at: datetime


class MapperExportResponse(BaseModel):
    session_id: int
    export_path: str
