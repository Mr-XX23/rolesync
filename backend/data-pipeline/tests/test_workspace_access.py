"""Workspace membership checks for workspace-scoped routes (offline: workspace-service is faked)."""

import uuid

import pytest
import requests
from fastapi import HTTPException

from module_1_document_processing import workspace_access
from module_1_document_processing.workspace_access import (
    MembershipDirectory,
    MembershipUnavailable,
    fetch_memberships,
    resolve_workspace_access,
)

USER = str(uuid.uuid4())
WORKSPACE = str(uuid.uuid4())


class _Response:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_memberships_come_from_workspace_service_with_roles(monkeypatch):
    seen = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers)
        return _Response(200, [
            {"workspaceId": WORKSPACE.upper(), "role": "MEMBER", "isActive": True},
            {"workspaceId": str(uuid.uuid4()), "role": "OWNER", "isActive": False},
            {"workspaceId": "not-a-uuid"},
        ])

    monkeypatch.setattr(requests, "get", fake_get)
    assert fetch_memberships("http://workspace.test/", USER, 5) == {WORKSPACE: "MEMBER"}
    assert seen == {"url": "http://workspace.test/api/v1/workspaces", "headers": {"X-User-Id": USER}}


def test_no_profile_means_no_memberships_and_errors_fail_closed(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, headers, timeout: _Response(404))
    assert fetch_memberships("http://workspace.test", USER, 5) == {}

    monkeypatch.setattr(requests, "get", lambda url, headers, timeout: _Response(500))
    with pytest.raises(MembershipUnavailable):
        fetch_memberships("http://workspace.test", USER, 5)


def test_answers_are_cached_but_a_miss_is_rechecked_live():
    answers = [{}, {WORKSPACE: "OWNER"}]
    calls = []

    def fetch(base_url, user_id, timeout):
        calls.append(user_id)
        return answers[min(len(calls) - 1, len(answers) - 1)]

    directory = MembershipDirectory("http://workspace.test", cache_seconds=60, fetch=fetch)
    access = directory.access(USER, WORKSPACE)  # cached "none", then a live re-check finds the new workspace
    assert access.role == "OWNER" and access.is_admin and access.can_write
    assert directory.access(USER, WORKSPACE).role == "OWNER"
    assert len(calls) == 2  # the second lookup was served from the cache


def test_requests_without_a_valid_member_workspace_are_refused(monkeypatch):
    fake = MembershipDirectory("http://workspace.test", fetch=lambda base, user, timeout: {WORKSPACE: "VIEWER"})
    monkeypatch.setattr(workspace_access, "directory", fake)

    for header, status in [(None, 400), ("   ", 400), ("tenant_default", 400), (str(uuid.uuid4()), 403)]:
        with pytest.raises(HTTPException) as refused:
            resolve_workspace_access(USER, header)
        assert refused.value.status_code == status

    viewer = resolve_workspace_access(USER, WORKSPACE.upper())
    assert viewer.workspace_id == WORKSPACE and not viewer.can_write

    def unavailable(base, user, timeout):
        raise MembershipUnavailable("workspace-service unreachable")

    monkeypatch.setattr(workspace_access, "directory", MembershipDirectory("http://x", fetch=unavailable))
    with pytest.raises(HTTPException) as refused:
        resolve_workspace_access(USER, WORKSPACE)
    assert refused.value.status_code == 503
