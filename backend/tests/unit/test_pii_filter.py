import pytest

from app.services.query_pipeline.pii_filter import redact_personal_information


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Email jane.doe@example.com for details.",
            "Email [REDACTED_EMAIL] for details.",
        ),
        (
            "Call me at +63 917 123 4567.",
            "Call me at [REDACTED_PHONE].",
        ),
        (
            "My SSS number is 12-3456789-0.",
            "My [REDACTED_GOVERNMENT_ID].",
        ),
        (
            "My card is 4111 1111 1111 1111.",
            "My card is [REDACTED_PAYMENT_CARD].",
        ),
        (
            "My address is 123 Main Street, Quezon City.",
            "[REDACTED_ADDRESS].",
        ),
        (
            "My name is Juan Dela Cruz.",
            "My name is [REDACTED_NAME].",
        ),
    ],
)
def test_redacts_selected_personal_information(message, expected):
    assert redact_personal_information(message) == expected


def test_preserves_non_personal_numbers_and_non_name_phrases():
    message = "I am a student asking about AY 2026-2027 admission requirements."

    assert redact_personal_information(message) == message


def test_redacts_multiple_personal_information_types_in_one_message():
    message = (
        "My name is Juan Dela Cruz, email juan@example.com, "
        "and phone 09171234567."
    )

    assert redact_personal_information(message) == (
        "My name is [REDACTED_NAME], email [REDACTED_EMAIL], "
        "and phone [REDACTED_PHONE]."
    )
