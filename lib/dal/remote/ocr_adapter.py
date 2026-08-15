from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from lib.core.logs import get_logger

try:
    from paddleocr import PaddleOCR
except Exception:  # pragma: no cover - optional until runtime
    PaddleOCR = None


class OcrTextRegion(TypedDict):
    text: str
    bounds: str


class OcrAdapter:
    def __init__(self, language: str = "en") -> None:
        self.language = language
        self._ocr = None
        self.logger = get_logger(__name__)

    @property
    def ocr(self):
        if self._ocr is None:
            if PaddleOCR is None:
                raise RuntimeError("PaddleOCR is not available in this environment")
            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.language, show_log=False)
        return self._ocr

    def extract_text_regions(self, image_path: Path) -> list[OcrTextRegion]:
        """OCR is only a textual reference for a screenshot, it can't tell on its own whether a
        result is meaningful or actionable, that call belongs to whoever asked for it. What it
        must always do is keep the position of what it found (issue #32): PaddleOCR already
        returns a 4-point polygon per detected region, previously discarded here, that's what
        makes an OCR result something `click_bounds` can actually act on instead of just text
        nobody can click."""
        self.logger.debug("Running OCR fallback on %s", image_path)
        result = self.ocr.ocr(str(image_path), cls=True)
        regions: list[OcrTextRegion] = []
        for page in result:
            for item in page or []:
                if len(item) < 2:
                    continue
                box = item[0]
                text = item[1][0].strip()
                if not text or not box:
                    continue
                xs = [point[0] for point in box]
                ys = [point[1] for point in box]
                bounds = f"[{int(min(xs))},{int(min(ys))}][{int(max(xs))},{int(max(ys))}]"
                regions.append({"text": text, "bounds": bounds})
        self.logger.debug("OCR extracted %s region(s) from %s", len(regions), image_path)
        return regions
