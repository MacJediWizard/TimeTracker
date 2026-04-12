"""Tests for integration sync helpers."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


def test_sync_result_item_count_prefers_synced_count():
    from app.utils.integration_sync_context import sync_result_item_count

    assert sync_result_item_count({"synced_count": 5, "synced_items": 9}) == 5


def test_sync_result_item_count_falls_back_to_synced_items():
    from app.utils.integration_sync_context import sync_result_item_count

    assert sync_result_item_count({"synced_items": 7}) == 7


def test_sync_result_item_count_empty():
    from app.utils.integration_sync_context import sync_result_item_count

    assert sync_result_item_count({}) == 0
    assert sync_result_item_count(None) == 0


@patch("app.models.Task")
def test_find_task_by_integration_ref_filters_by_source(MockTask):
    from app.utils.integration_sync_context import find_task_by_integration_ref

    t_git = MagicMock()
    t_git.custom_fields = {"integration": {"source": "github", "ref": "same-ref"}}
    t_jira = MagicMock()
    t_jira.custom_fields = {"integration": {"source": "jira", "ref": "same-ref"}}
    MockTask.query.filter_by.return_value.all.return_value = [t_git, t_jira]

    assert find_task_by_integration_ref(42, "same-ref", source="jira") is t_jira
    assert find_task_by_integration_ref(42, "same-ref", source="github") is t_git


@patch("app.models.Task")
def test_find_task_by_integration_ref_without_source_matches_any(MockTask):
    from app.utils.integration_sync_context import find_task_by_integration_ref

    first = MagicMock()
    first.custom_fields = {"integration": {"source": "github", "ref": "r1"}}
    MockTask.query.filter_by.return_value.all.return_value = [first]

    assert find_task_by_integration_ref(1, "r1") is first
