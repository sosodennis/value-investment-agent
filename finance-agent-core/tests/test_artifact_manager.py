"""
Unit tests for ArtifactManager service.
Tests artifact storage, retrieval, and edge cases.
"""

import json
import uuid

import pytest

from src.services.artifact_manager import artifact_manager


@pytest.mark.anyio
async def test_save_and_retrieve_artifact():
    """Test basic save and retrieve flow."""
    # Arrange
    test_data = {
        "ticker": "AAPL",
        "news_items": [
            {"title": "Apple announces new product", "sentiment": 0.8},
            {"title": "Market analysis", "sentiment": 0.5},
        ],
    }

    # Act
    artifact_id = await artifact_manager.save_artifact(
        data=test_data,
        artifact_type="news_items",
        key_prefix="AAPL",
        thread_id="test_thread_123",
    )

    # Assert
    assert artifact_id is not None
    assert isinstance(artifact_id, str)
    assert len(artifact_id) == 36  # UUID format

    # Retrieve
    artifact = await artifact_manager.get_artifact(artifact_id)
    assert artifact is not None
    assert artifact.type == "news_items"
    assert artifact.data == test_data
    assert artifact.thread_id == "test_thread_123"
    assert "AAPL" in artifact.key


@pytest.mark.anyio
async def test_save_artifact_without_optional_fields():
    """Test saving artifact without key_prefix and thread_id."""
    # Arrange
    test_data = {"calculation": "DCF", "result": 150.25}

    # Act
    artifact_id = await artifact_manager.save_artifact(
        data=test_data, artifact_type="calculation_result"
    )

    # Assert
    artifact = await artifact_manager.get_artifact(artifact_id)
    assert artifact is not None
    assert artifact.type == "calculation_result"
    assert artifact.data == test_data
    assert artifact.key is None
    assert artifact.thread_id is None


@pytest.mark.anyio
async def test_large_artifact_5mb():
    """Test storing a large ~5MB JSON payload."""
    # Arrange: Create a large dataset
    large_data = {
        "price_history": [
            {"date": f"2024-{i:04d}", "open": 100 + i * 0.1, "close": 101 + i * 0.1}
            for i in range(100000)  # ~10MB of data
        ]
    }

    # Verify size is approximately 5MB
    json_str = json.dumps(large_data)
    size_mb = len(json_str.encode("utf-8")) / (1024 * 1024)
    assert size_mb > 4.5  # Should be around 5MB

    # Act
    artifact_id = await artifact_manager.save_artifact(
        data=large_data, artifact_type="price_data", key_prefix="LARGE_TEST"
    )

    # Assert
    artifact = await artifact_manager.get_artifact(artifact_id)
    assert artifact is not None
    assert artifact.type == "price_data"
    assert len(artifact.data["price_history"]) == 100000


@pytest.mark.anyio
async def test_artifact_not_found():
    """Test retrieval of non-existent artifact."""
    # Act
    fake_id = str(uuid.uuid4())
    artifact = await artifact_manager.get_artifact(fake_id)

    # Assert
    assert artifact is None


@pytest.mark.anyio
async def test_save_list_artifact():
    """Test saving a list instead of a dict."""
    # Arrange
    test_data = [
        {"symbol": "AAPL", "weight": 0.3},
        {"symbol": "GOOGL", "weight": 0.4},
        {"symbol": "MSFT", "weight": 0.3},
    ]

    # Act
    artifact_id = await artifact_manager.save_artifact(
        data=test_data, artifact_type="portfolio_allocation"
    )

    # Assert
    artifact = await artifact_manager.get_artifact(artifact_id)
    assert artifact is not None
    assert artifact.data == test_data
    assert isinstance(artifact.data, list)


@pytest.mark.anyio
async def test_multiple_artifacts_same_type():
    """Test creating multiple artifacts of the same type."""
    # Act
    id1 = await artifact_manager.save_artifact(
        data={"ticker": "AAPL"}, artifact_type="news_items", key_prefix="AAPL"
    )
    id2 = await artifact_manager.save_artifact(
        data={"ticker": "GOOGL"}, artifact_type="news_items", key_prefix="GOOGL"
    )

    # Assert
    assert id1 != id2

    artifact1 = await artifact_manager.get_artifact(id1)
    artifact2 = await artifact_manager.get_artifact(id2)

    assert artifact1.data["ticker"] == "AAPL"
    assert artifact2.data["ticker"] == "GOOGL"
    assert "AAPL" in artifact1.key
    assert "GOOGL" in artifact2.key
