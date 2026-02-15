"""Input validation utilities for MyBola agent tools."""
import re
from datetime import datetime
from typing import Any, Dict


class ValidationError(Exception):
    """Custom exception for validation errors."""
    pass


def validate_club_ref(club_ref: str) -> Dict[str, Any]:
    """Validate club reference format.

    Args:
        club_ref: Club reference string (e.g., 'club/my_club_123')

    Returns:
        Validation result dict

    Raises:
        ValidationError: If validation fails
    """
    if not club_ref or not isinstance(club_ref, str):
        raise ValidationError("Club reference must be a non-empty string")

    if not club_ref.strip():
        raise ValidationError("Club reference cannot be empty or whitespace")

    return {"valid": True, "club_ref": club_ref.strip()}


def validate_amount(amount: float, min_value: float = 0.0) -> Dict[str, Any]:
    """Validate monetary amount.

    Args:
        amount: Amount to validate
        min_value: Minimum allowed value (default: 0.0)

    Returns:
        Validation result dict

    Raises:
        ValidationError: If validation fails
    """
    try:
        amount_float = float(amount)
    except (TypeError, ValueError):
        raise ValidationError(f"Amount must be a valid number, got: {amount}")

    if amount_float < min_value:
        raise ValidationError(f"Amount must be at least RM{min_value}, got: RM{amount_float}")

    if amount_float > 999999.99:
        raise ValidationError(f"Amount too large: RM{amount_float} (max: RM999,999.99)")

    # Round to 2 decimal places for currency
    return {"valid": True, "amount": round(amount_float, 2)}


def validate_date(date_str: str) -> Dict[str, Any]:
    """Validate date string in YYYY-MM-DD format.

    Args:
        date_str: Date string to validate

    Returns:
        Validation result dict with parsed date

    Raises:
        ValidationError: If validation fails
    """
    if not date_str or not isinstance(date_str, str):
        raise ValidationError("Date must be a non-empty string")

    try:
        parsed_date = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return {"valid": True, "date": date_str.strip(), "parsed": parsed_date}
    except ValueError:
        raise ValidationError(f"Invalid date format: {date_str}. Expected: YYYY-MM-DD")


def validate_email(email: str) -> Dict[str, Any]:
    """Validate email address format.

    Args:
        email: Email address to validate

    Returns:
        Validation result dict

    Raises:
        ValidationError: If validation fails
    """
    if not email or not isinstance(email, str):
        raise ValidationError("Email must be a non-empty string")

    email = email.strip().lower()

    # Basic email regex pattern
    pattern = r'^[a-z0-9][a-z0-9._-]*@[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$'

    if not re.match(pattern, email):
        raise ValidationError(f"Invalid email format: {email}")

    if len(email) > 254:  # RFC 5321
        raise ValidationError("Email address too long")

    return {"valid": True, "email": email}


def validate_phone(phone: str) -> Dict[str, Any]:
    """Validate phone number (Malaysian format).

    Args:
        phone: Phone number to validate

    Returns:
        Validation result dict

    Raises:
        ValidationError: If validation fails
    """
    if not phone or not isinstance(phone, str):
        raise ValidationError("Phone number must be a non-empty string")

    # Remove common separators
    phone_clean = re.sub(r'[\s\-()]', '', phone)

    # Check if it's all digits (optionally with leading +)
    if not re.match(r'^\+?\d+$', phone_clean):
        raise ValidationError(f"Phone number contains invalid characters: {phone}")

    # Remove leading + for length check
    digits = phone_clean.lstrip('+')

    if len(digits) < 10 or len(digits) > 15:
        raise ValidationError(f"Phone number invalid length: {phone} ({len(digits)} digits)")

    return {"valid": True, "phone": phone_clean}


def validate_text_field(text: str, field_name: str,
                       min_length: int = 1,
                       max_length: int = 500,
                       allow_empty: bool = False) -> Dict[str, Any]:
    """Validate text field with length constraints.

    Args:
        text: Text to validate
        field_name: Name of the field (for error messages)
        min_length: Minimum length (default: 1)
        max_length: Maximum length (default: 500)
        allow_empty: Whether to allow empty strings (default: False)

    Returns:
        Validation result dict

    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(text, str):
        raise ValidationError(f"{field_name} must be a string")

    text_stripped = text.strip()

    if not text_stripped and not allow_empty:
        raise ValidationError(f"{field_name} cannot be empty")

    if len(text_stripped) < min_length:
        raise ValidationError(
            f"{field_name} too short (min: {min_length} chars, got: {len(text_stripped)})"
        )

    if len(text_stripped) > max_length:
        raise ValidationError(
            f"{field_name} too long (max: {max_length} chars, got: {len(text_stripped)})"
        )

    return {"valid": True, "text": text_stripped}


def validate_member_id(member_id: str) -> Dict[str, Any]:
    """Validate member ID format.

    Args:
        member_id: Member ID to validate

    Returns:
        Validation result dict

    Raises:
        ValidationError: If validation fails
    """
    if not member_id or not isinstance(member_id, str):
        raise ValidationError("Member ID must be a non-empty string")

    member_id = member_id.strip()

    if not member_id:
        raise ValidationError("Member ID cannot be empty")

    if len(member_id) > 100:
        raise ValidationError(f"Member ID too long: {member_id}")

    return {"valid": True, "member_id": member_id}


def validate_status(status: str, allowed_statuses: list) -> Dict[str, Any]:
    """Validate status against allowed values.

    Args:
        status: Status value to validate
        allowed_statuses: List of allowed status values

    Returns:
        Validation result dict

    Raises:
        ValidationError: If validation fails
    """
    if not status or not isinstance(status, str):
        raise ValidationError("Status must be a non-empty string")

    status = status.strip()

    if status not in allowed_statuses:
        raise ValidationError(
            f"Invalid status: {status}. Allowed: {', '.join(allowed_statuses)}"
        )

    return {"valid": True, "status": status}
