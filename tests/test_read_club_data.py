"""Tests for the generic club-scoped Firestore read tool."""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mybola_agent.tools.firestore_read import (
    _club_ref_matches,
    _resolve_collection,
    _sanitize_doc,
    _validate_filters,
    read_club_data,
)
from mybola_agent.tools.validation import ValidationError

# ---------------------------------------------------------------------------
# Helper resolution tests
# ---------------------------------------------------------------------------


class TestResolveCollection:
    def test_canonical_names(self):
        assert _resolve_collection("club") == "club"
        assert _resolve_collection("member") == "member"
        assert _resolve_collection("sesi") == "sesi"
        assert _resolve_collection("billing") == "billing"
        assert _resolve_collection("shirt") == "shirt"

    def test_aliases(self):
        assert _resolve_collection("sessions") == "sesi"
        assert _resolve_collection("bills") == "billing"
        assert _resolve_collection("shirt_orders") == "shirt"
        assert _resolve_collection("shirts") == "shirt"
        assert _resolve_collection("members") == "member"
        assert _resolve_collection("clubs") == "club"
        assert _resolve_collection("orders") == "shirt"

    def test_case_insensitive(self):
        assert _resolve_collection("MEMBER") == "member"
        assert _resolve_collection("Bills") == "billing"

    def test_unknown_raises(self):
        with pytest.raises(ValidationError, match="Unknown collection"):
            _resolve_collection("nonexistent")

    def test_users_not_allowed(self):
        with pytest.raises(ValidationError, match="Unknown collection"):
            _resolve_collection("users")


# ---------------------------------------------------------------------------
# Sanitization tests
# ---------------------------------------------------------------------------


class TestSanitizeDoc:
    def test_datetime_to_iso(self):
        dt = datetime(2025, 1, 15, 10, 30, 0)
        result = _sanitize_doc({"created_at": dt, "name": "Ali"})
        assert result["created_at"] == "2025-01-15T10:30:00"
        assert result["name"] == "Ali"

    def test_document_reference_to_path(self):
        mock_ref = MagicMock()
        mock_ref.path = "club/abc123"
        result = _sanitize_doc({"club_ref": mock_ref})
        assert result["club_ref"] == "club/abc123"

    def test_bytes_to_placeholder(self):
        result = _sanitize_doc({"photo": b"\x89PNG"})
        assert result["photo"] == "<binary>"

    def test_plain_values_unchanged(self):
        result = _sanitize_doc({"status": "active", "count": 5, "rate": 3.14})
        assert result == {"status": "active", "count": 5, "rate": 3.14}


# ---------------------------------------------------------------------------
# Club ref matching tests
# ---------------------------------------------------------------------------


class TestClubRefMatches:
    def test_string_match(self):
        assert _club_ref_matches("club/abc", "club/abc") is True

    def test_string_mismatch(self):
        assert _club_ref_matches("club/abc", "club/xyz") is False

    def test_document_reference_match(self):
        mock_ref = MagicMock()
        mock_ref.path = "club/abc"
        assert _club_ref_matches(mock_ref, "club/abc") is True

    def test_document_reference_mismatch(self):
        mock_ref = MagicMock()
        mock_ref.path = "club/abc"
        assert _club_ref_matches(mock_ref, "club/xyz") is False

    def test_strips_whitespace(self):
        assert _club_ref_matches("  club/abc  ", "club/abc") is True


# ---------------------------------------------------------------------------
# Filter validation tests
# ---------------------------------------------------------------------------


class TestValidateFilters:
    def test_none_is_ok(self):
        _validate_filters(None)

    def test_empty_is_ok(self):
        _validate_filters([])

    def test_valid_filter(self):
        _validate_filters([{"field": "status", "op": "==", "value": "active"}])

    def test_missing_keys_raises(self):
        with pytest.raises(ValidationError, match="missing keys"):
            _validate_filters([{"field": "status"}])

    def test_invalid_op_raises(self):
        with pytest.raises(ValidationError, match="invalid op"):
            _validate_filters([{"field": "x", "op": "LIKE", "value": "y"}])

    def test_club_ref_filter_rejected(self):
        with pytest.raises(ValidationError, match="club reference"):
            _validate_filters([{"field": "club_ref", "op": "==", "value": "club/x"}])

    def test_club_ref_camel_filter_rejected(self):
        with pytest.raises(ValidationError, match="club reference"):
            _validate_filters([{"field": "clubRef", "op": "==", "value": "club/x"}])


# ---------------------------------------------------------------------------
# read_club_data integration tests (mocked Firestore)
# ---------------------------------------------------------------------------


def _make_mock_snapshot(data, doc_id="doc1", exists=True):
    """Create a mock Firestore document snapshot."""
    snap = MagicMock()
    snap.exists = exists
    snap.id = doc_id
    snap.to_dict.return_value = data
    return snap


def _make_mock_count_result(count_val):
    """Create a mock count query result."""
    count_obj = MagicMock()
    count_obj.value = count_val
    return [[count_obj]]


@pytest.mark.asyncio
async def test_empty_club_ref_returns_error():
    result = await read_club_data(club_ref="", collection="member")
    assert result["status"] == "error"
    assert "Validation error" in result["error"]


@pytest.mark.asyncio
async def test_unknown_collection_returns_error():
    result = await read_club_data(club_ref="club/abc", collection="nonexistent")
    assert result["status"] == "error"
    assert "Unknown collection" in result["error"]


@pytest.mark.asyncio
async def test_invalid_order_direction_returns_error():
    result = await read_club_data(
        club_ref="club/abc", collection="member", order_direction="RANDOM"
    )
    assert result["status"] == "error"
    assert "order_direction" in result["error"]


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_club_collection_returns_club_doc(mock_fs):
    club_data = {"name": "Test FC", "location": "KL"}
    mock_snap = _make_mock_snapshot(club_data, doc_id="test_fc")

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db
    mock_db.document.return_value.get = AsyncMock(return_value=mock_snap)

    result = await read_club_data(club_ref="club/test_fc", collection="club")
    assert result["status"] == "success"
    assert result["count"] == 1
    assert result["data"][0]["name"] == "Test FC"
    assert result["data"][0]["id"] == "test_fc"


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_club_collection_not_found(mock_fs):
    mock_snap = _make_mock_snapshot({}, exists=False)

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db
    mock_db.document.return_value.get = AsyncMock(return_value=mock_snap)

    result = await read_club_data(club_ref="club/nonexistent", collection="club")
    assert result["status"] == "error"
    assert "Club not found" in result["error"]


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_single_doc_get_matching_club_ref(mock_fs):
    doc_data = {"club_ref": "club/abc", "name": "Ali", "status": "active"}
    mock_snap = _make_mock_snapshot(doc_data, doc_id="m1")

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db
    mock_db.collection.return_value.document.return_value.get = AsyncMock(
        return_value=mock_snap
    )

    result = await read_club_data(
        club_ref="club/abc", collection="member", doc_id="m1"
    )
    assert result["status"] == "success"
    assert result["data"][0]["name"] == "Ali"
    assert result["data"][0]["id"] == "m1"


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_single_doc_get_mismatched_club_ref(mock_fs):
    doc_data = {"club_ref": "club/other", "name": "Ali"}
    mock_snap = _make_mock_snapshot(doc_data, doc_id="m1")

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db
    mock_db.collection.return_value.document.return_value.get = AsyncMock(
        return_value=mock_snap
    )

    result = await read_club_data(
        club_ref="club/abc", collection="member", doc_id="m1"
    )
    assert result["status"] == "error"
    assert "not found" in result["error"]


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_single_doc_get_not_found(mock_fs):
    mock_snap = _make_mock_snapshot({}, exists=False)

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db
    mock_db.collection.return_value.document.return_value.get = AsyncMock(
        return_value=mock_snap
    )

    result = await read_club_data(
        club_ref="club/abc", collection="member", doc_id="m1"
    )
    assert result["status"] == "error"
    assert "not found" in result["error"]


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_collection_query_basic(mock_fs):
    docs = [
        _make_mock_snapshot(
            {"club_ref": "club/abc", "name": "Ali", "status": "active"}, doc_id="m1"
        ),
        _make_mock_snapshot(
            {"club_ref": "club/abc", "name": "Siti", "status": "active"}, doc_id="m2"
        ),
    ]

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db

    # Chain: collection -> where -> limit -> get
    mock_query = MagicMock()
    mock_db.collection.return_value.where.return_value = mock_query
    mock_query.limit.return_value.get = AsyncMock(return_value=docs)

    result = await read_club_data(club_ref="club/abc", collection="member")
    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["data"][0]["name"] == "Ali"
    assert result["data"][1]["name"] == "Siti"


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_collection_query_with_filters(mock_fs):
    docs = [
        _make_mock_snapshot(
            {"club_ref": "club/abc", "name": "Ali", "status": "active"}, doc_id="m1"
        ),
    ]

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db

    mock_query = MagicMock()
    mock_db.collection.return_value.where.return_value = mock_query
    # After chaining .where for additional filter
    mock_query.where.return_value = mock_query
    mock_query.limit.return_value.get = AsyncMock(return_value=docs)

    result = await read_club_data(
        club_ref="club/abc",
        collection="member",
        filters=[{"field": "status", "op": "==", "value": "active"}],
    )
    assert result["status"] == "success"
    assert result["count"] == 1


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_collection_query_with_order_by(mock_fs):
    docs = [
        _make_mock_snapshot(
            {"club_ref": "club/abc", "name": "Ali"}, doc_id="m1"
        ),
    ]

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db
    mock_fs.Query.ASCENDING = "ASCENDING"
    mock_fs.Query.DESCENDING = "DESCENDING"

    mock_query = MagicMock()
    mock_db.collection.return_value.where.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value.get = AsyncMock(return_value=docs)

    result = await read_club_data(
        club_ref="club/abc",
        collection="member",
        order_by="name",
        order_direction="ASCENDING",
    )
    assert result["status"] == "success"


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_count_only(mock_fs):
    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db

    mock_query = MagicMock()
    mock_db.collection.return_value.where.return_value = mock_query
    mock_query.count.return_value.get = AsyncMock(
        return_value=_make_mock_count_result(42)
    )

    result = await read_club_data(
        club_ref="club/abc", collection="member", count_only=True
    )
    assert result["status"] == "success"
    assert result["count"] == 42
    assert "data" not in result


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_fields_projection(mock_fs):
    docs = [
        _make_mock_snapshot(
            {"club_ref": "club/abc", "name": "Ali", "ic_number": "123", "phone": "012"},
            doc_id="m1",
        ),
    ]

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db

    mock_query = MagicMock()
    mock_db.collection.return_value.where.return_value = mock_query
    mock_query.limit.return_value.get = AsyncMock(return_value=docs)

    result = await read_club_data(
        club_ref="club/abc", collection="member", fields=["name", "phone"]
    )
    assert result["status"] == "success"
    data = result["data"][0]
    assert "name" in data
    assert "phone" in data
    assert "id" in data  # always included
    assert "ic_number" not in data
    assert "club_ref" not in data


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_empty_results(mock_fs):
    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db

    mock_query = MagicMock()
    mock_db.collection.return_value.where.return_value = mock_query
    mock_query.limit.return_value.get = AsyncMock(return_value=[])

    result = await read_club_data(club_ref="club/abc", collection="member")
    assert result["status"] == "success"
    assert result["count"] == 0
    assert result["data"] == []


@pytest.mark.asyncio
@patch("mybola_agent.tools.firestore_read.firestore")
async def test_datetime_sanitized_in_results(mock_fs):
    dt = datetime(2025, 3, 15, 14, 0, 0)
    docs = [
        _make_mock_snapshot(
            {"club_ref": "club/abc", "name": "Ali", "joined_at": dt}, doc_id="m1"
        ),
    ]

    mock_db = MagicMock()
    mock_fs.AsyncClient.return_value = mock_db

    mock_query = MagicMock()
    mock_db.collection.return_value.where.return_value = mock_query
    mock_query.limit.return_value.get = AsyncMock(return_value=docs)

    result = await read_club_data(club_ref="club/abc", collection="member")
    assert result["data"][0]["joined_at"] == "2025-03-15T14:00:00"
