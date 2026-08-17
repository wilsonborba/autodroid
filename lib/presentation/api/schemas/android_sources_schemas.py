from __future__ import annotations

from pydantic import BaseModel, Field


class AndroidSourcesListResponse(BaseModel):
    package_name: str
    path: str
    entries: list[str] = Field(description="One line per `ls -la` entry, unparsed (permissions, owner, size, name).")
    raw: str = Field(description="The full, unparsed `ls -la` output, in case a caller wants to parse it itself.")


class AndroidSourcesDeleteResponse(BaseModel):
    package_name: str
    path: str
    deleted: bool


class AndroidSourcesStageResponse(BaseModel):
    package_name: str
    path: str = Field(description="Where the file landed on the device, e.g. \"/sdcard/Download/photo.jpg\".")
    staged: bool
    size_bytes: int
