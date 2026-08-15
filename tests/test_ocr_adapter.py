from __future__ import annotations

from pathlib import Path

from lib.dal.remote.ocr_adapter import OcrAdapter


class FakePaddleOcr:
    def __init__(self, result) -> None:
        self._result = result

    def ocr(self, path, cls=True):
        return self._result


def test_extract_text_regions_computes_bounds_from_polygon() -> None:
    adapter = OcrAdapter()
    polygon = [[10, 20], [110, 20], [110, 40], [10, 40]]
    adapter._ocr = FakePaddleOcr([[[polygon, ("Hello", 0.99)]]])

    regions = adapter.extract_text_regions(Path("/tmp/fake.png"))

    assert regions == [{"text": "Hello", "bounds": "[10,20][110,40]"}]


def test_extract_text_regions_skips_blank_text() -> None:
    adapter = OcrAdapter()
    polygon = [[0, 0], [10, 0], [10, 10], [0, 10]]
    adapter._ocr = FakePaddleOcr([[[polygon, ("   ", 0.5)]]])

    regions = adapter.extract_text_regions(Path("/tmp/fake.png"))

    assert regions == []


def test_extract_text_regions_handles_multiple_regions_across_pages() -> None:
    adapter = OcrAdapter()
    first = [[0, 0], [10, 0], [10, 10], [0, 10]]
    second = [[20, 20], [40, 20], [40, 30], [20, 30]]
    adapter._ocr = FakePaddleOcr([[[first, ("A", 0.9)], [second, ("B", 0.9)]]])

    regions = adapter.extract_text_regions(Path("/tmp/fake.png"))

    assert regions == [
        {"text": "A", "bounds": "[0,0][10,10]"},
        {"text": "B", "bounds": "[20,20][40,30]"},
    ]
