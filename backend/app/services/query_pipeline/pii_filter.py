"""Best-effort local redaction of personal information in chat text."""
import re

EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w-])",
    re.IGNORECASE,
)
CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
GOVERNMENT_ID_PATTERN = re.compile(
    r"\b(?:"
    r"national\s+id|"
    r"driver['’]?s?\s+licen[cs]e|"
    r"passport|"
    r"philhealth|"
    r"prc(?:\s+id)?|"
    r"sss|"
    r"gsis|"
    r"tin|"
    r"umid"
    r")(?:\s+(?:number|no\.?))?\s*(?:#|:|is)\s*"
    r"[A-Z0-9][A-Z0-9-]{2,}",
    re.IGNORECASE,
)
LABELED_ADDRESS_PATTERN = re.compile(
    r"\b(?:my\s+)?address(?:\s+is)?\s*(?::|is)?\s*[^.!?;\n]{3,120}",
    re.IGNORECASE,
)
STREET_ADDRESS_PATTERN = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z0-9][\w.'-]*\s+){0,6}"
    r"(?:street|st\.|avenue|ave\.|road|rd\.|boulevard|blvd\.|"
    r"drive|dr\.|lane|ln\.|court|ct\.|highway|hwy\.|"
    r"place|pl\.|crescent|walk)\b"
    r"(?:,\s*(?:unit|apt\.?|apartment|suite|floor|brgy\.?|barangay)?"
    r"\s*[\w.#-]+){0,3}",
    re.IGNORECASE,
)
LABELED_NAME_PATTERN = re.compile(
    r"\b(?:my\s+name\s+is|name\s+is|name\s*:|i\s+am|i['’]m|this\s+is)\s+"
    r"(?P<name>[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?"
    r"(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?){0,3})"
)
PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d ().-]{5,}\d(?!\w)")
NAME_FALSE_POSITIVES = {
    "a",
    "an",
    "applying",
    "asking",
    "currently",
    "enrolled",
    "interested",
    "looking",
    "not",
    "student",
    "wondering",
}
REDACTION = {
    "email": "[REDACTED_EMAIL]",
    "phone": "[REDACTED_PHONE]",
    "government_id": "[REDACTED_GOVERNMENT_ID]",
    "payment": "[REDACTED_PAYMENT_CARD]",
    "address": "[REDACTED_ADDRESS]",
    "name": "[REDACTED_NAME]",
}


def _passes_luhn(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False

    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _redact_payment_cards(text: str) -> str:
    return CARD_PATTERN.sub(
        lambda match: REDACTION["payment"]
        if _passes_luhn(match.group())
        else match.group(),
        text,
    )


def _redact_names(text: str) -> str:
    def replace_name(match: re.Match[str]) -> str:
        name = match.group("name")
        words = name.split()
        if len(words) == 1 and words[0].lower() in NAME_FALSE_POSITIVES:
            return match.group()
        if match.group(0).lower().startswith("i am ") and len(words) == 1:
            return match.group()
        return match.group(0).replace(name, REDACTION["name"])

    return LABELED_NAME_PATTERN.sub(replace_name, text)


def _redact_phones(text: str) -> str:
    def replace_phone(match: re.Match[str]) -> str:
        value = match.group()
        digit_count = sum(char.isdigit() for char in value)
        separator_count = sum(value.count(char) for char in " -().")
        has_international_prefix = value.lstrip().startswith("+")
        if 7 <= digit_count <= 15 and (
            digit_count >= 10
            or has_international_prefix
            or separator_count >= 2
        ):
            return REDACTION["phone"]
        return value

    return PHONE_PATTERN.sub(replace_phone, text)


def redact_personal_information(text: str) -> str:
    """Mask recognizable email, phone, ID, payment, address and labeled-name patterns.

    Pattern-based name and address detection is intentionally best-effort. It
    may miss unstructured personal information or redact ordinary text.
    """
    text = EMAIL_PATTERN.sub(REDACTION["email"], text)
    text = _redact_payment_cards(text)
    text = GOVERNMENT_ID_PATTERN.sub(REDACTION["government_id"], text)
    text = LABELED_ADDRESS_PATTERN.sub(REDACTION["address"], text)
    text = STREET_ADDRESS_PATTERN.sub(REDACTION["address"], text)
    text = _redact_names(text)
    return _redact_phones(text)
