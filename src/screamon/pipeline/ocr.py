"""OCR (Optical Character Recognition) utilities."""

import logging
from typing import NamedTuple

from PIL import Image
import pytesseract

logger = logging.getLogger(__name__)


class OCRResult(NamedTuple):
    """Result from OCR processing."""

    text: str
    confidence: float | None  # Average confidence if available


def extract_text(image: Image.Image, lang: str = "eng") -> str:
    """
    Extract text from an image using Tesseract OCR.

    Args:
        image: PIL Image to process
        lang: Language code for Tesseract

    Returns:
        Extracted text string
    """
    try:
        text = pytesseract.image_to_string(image, lang=lang)
        logger.debug("OCR extracted: %r", text[:100] if len(text) > 100 else text)
        return text
    except Exception as e:
        logger.error("OCR failed: %s", e)
        return ""


def extract_text_with_confidence(image: Image.Image, lang: str = "eng") -> OCRResult:
    """
    Extract text with confidence scores.

    Uses Tesseract's data output to get per-word confidence scores
    and returns the average confidence.

    Args:
        image: PIL Image to process
        lang: Language code for Tesseract

    Returns:
        OCRResult with text and average confidence
    """
    try:
        # Get detailed data including confidence
        data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)

        # Combine text
        words = []
        confidences = []

        for i, text in enumerate(data["text"]):
            conf = data["conf"][i]
            if text.strip() and conf != -1:  # -1 means no confidence
                words.append(text)
                confidences.append(conf)

        full_text = " ".join(words)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        logger.debug("OCR extracted with %.1f%% confidence: %r", avg_confidence, full_text[:50])
        return OCRResult(text=full_text, confidence=avg_confidence)

    except Exception as e:
        logger.error("OCR with confidence failed: %s", e)
        return OCRResult(text="", confidence=None)


def extract_lines(image: Image.Image, lang: str = "eng") -> list[str]:
    """
    Extract text as a list of lines.

    Args:
        image: PIL Image to process
        lang: Language code

    Returns:
        List of non-empty text lines
    """
    text = extract_text(image, lang)
    return [line.strip() for line in text.splitlines() if line.strip()]


def count_lines(image: Image.Image, lang: str = "eng") -> int:
    """
    Count the number of text lines in an image.

    Args:
        image: PIL Image to process
        lang: Language code

    Returns:
        Number of non-empty lines
    """
    return len(extract_lines(image, lang))


# Common OCR corrections for EVE Online text
EVE_OCR_CORRECTIONS = {
    # Number corrections
    "l": "1",  # lowercase L often misread as 1
    "O": "0",  # uppercase O often misread as 0
    "o": "0",
    # Asteroid variations (common OCR misreads)
    "Astroid": "Asteroid",
    "Asteraid": "Asteroid",
    "Asterpid": "Asteroid",
    "Asterocid": "Asteroid",
    "Astersid": "Asteroid",
}


def apply_corrections(text: str, corrections: dict[str, str] | None = None) -> str:
    """
    Apply OCR corrections to text.

    Args:
        text: Raw OCR text
        corrections: Dict of {wrong: correct} pairs. Defaults to EVE_OCR_CORRECTIONS.

    Returns:
        Corrected text
    """
    if corrections is None:
        corrections = EVE_OCR_CORRECTIONS

    result = text
    for wrong, correct in corrections.items():
        result = result.replace(wrong, correct)

    return result
