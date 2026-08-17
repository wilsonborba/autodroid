from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from lib.core.logs import get_logger
from lib.presentation.api.dependencies import get_android_sources_service
from lib.presentation.api.schemas.android_sources_schemas import (
    AndroidSourcesDeleteResponse,
    AndroidSourcesListResponse,
    AndroidSourcesStageResponse,
)

# deliberately not under /device or /mapper: this is about the app's own file storage on the
# emulator (issue #63), a different concern from driving its UI (device-actions) or mapping its
# screens (mapper).
router = APIRouter(prefix="/android-sources", tags=["android-sources"])
logger = get_logger(__name__)


@router.get(
    "/{package_name}/files",
    response_model=AndroidSourcesListResponse,
    summary="List files under an app's data or a shared staging folder",
)
def list_files(package_name: str, path: str | None = None):
    logger.info("GET /android-sources/%s/files path=%s", package_name, path)
    try:
        return AndroidSourcesListResponse(**get_android_sources_service().list_files(package_name, path=path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/{package_name}/files",
    response_model=AndroidSourcesDeleteResponse,
    summary="Delete one file under an app's data or a shared staging folder",
)
def delete_file(package_name: str, path: str):
    logger.info("DELETE /android-sources/%s/files path=%s", package_name, path)
    try:
        return AndroidSourcesDeleteResponse(**get_android_sources_service().delete_file(package_name, path))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{package_name}/files",
    response_model=AndroidSourcesStageResponse,
    summary="Stage a file (from the host) into a shared folder the app's own picker can read from",
)
async def stage_file(package_name: str, file: UploadFile = File(...), folder: str | None = Form(default=None)):
    logger.info("POST /android-sources/%s/files filename=%s folder=%s", package_name, file.filename, folder)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no filename")
    content = await file.read()
    try:
        return AndroidSourcesStageResponse(**get_android_sources_service().stage_file(package_name, file.filename, content, folder=folder))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
