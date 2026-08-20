from __future__ import annotations

from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateJobRequest(BaseModel):
    job_type: str
    adapter_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    run_after: datetime | None = None
    cron_expression: str | None = None
    execution_window_start: time | None = None
    execution_window_end: time | None = None
    max_attempts: int = 3


class ReprioritizeJobRequest(BaseModel):
    priority: int


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    adapter_name: str
    status: str
    priority: int
    payload_json: dict[str, Any] | None
    run_after: datetime | None
    cron_expression: str | None
    cancel_requested: bool
    pid: int | None
    result_json: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    worker_name: str
    status: str
    current_job_id: int | None
    execution_enabled: bool
    last_heartbeat_at: datetime
