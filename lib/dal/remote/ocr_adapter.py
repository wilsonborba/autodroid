from __future__ import annotations

from pathlib import Path

from lib.core.logs import get_logger

try:
    from paddleocr import PaddleOCR
except Exception:  # pragma: no cover - optional until runtime
    PaddleOCR = None


class OcrAdapter:
    def __init__(self, language: str = "en") -> None:
        self.language = language
        self._ocr = None
        self.logger = get_logger(__name__)

    @property
    def ocr(self):
        if PaddleOCR is None:
            raise RuntimeError("PaddleOCR is not available in this environment")
        if self._ocr is None:
            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.language, show_log=False)
        return self._ocr

    def extract_lines(self, image_path: Path) -> list[str]:
        self.logger.debug("Running OCR fallback on %s", image_path)
        result = self.ocr.ocr(str(image_path), cls=True)
        lines: list[str] = []
        for page in result:
            for item in page or []:
                if len(item) < 2:
                    continue
                text = item[1][0].strip()
                if text:
                    lines.append(text)
        self.logger.debug("OCR extracted %s lines from %s", len(lines), image_path)
        return lines
