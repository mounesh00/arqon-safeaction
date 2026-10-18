"""Focused offline SafeAction workflow and authorization tests."""
from dataclasses import replace
from datetime import timedelta
import os
import socket
import sqlite3
import subprocess

import pytest

from arqon_os.safe_action import SafeActionWorkflow, SafeActionError, SafeActionPermissionError
from arqon_os.tools import approvals
from arqon_os.tools.approvals import (
    ActorKind, ApprovalManager, ApprovalStatus, ApprovalBindingError,
    ApprovalExpiredError, ApprovalConsumedError, HumanDecisionRequiredError,
)


@pytest.fixture(autouse=True)
def no_external_actions(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('External action attempted')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(os, 'system', forbidden)


@pytest.fixture
def workflow(tmp_path):
    flow = SafeActionWorkflow(tmp_path/'runs.db', ApprovalManager(frozenset({'operator'})))
    flow.initialize()
    return flow


def approve(flow, proposal, **changes):
    return flow.approve(proposal, **({'decided_by': 'operator', 'actor_kind': ActorKind.HUMAN,
                                   'human_confirmed': True} | changes))


def test_proposal_and_explicit_approval(workflow):
    proposal = workflow.prepare()
    assert proposal.title == 'Travel checklist' and len(proposal.items) == 5
    assert proposal.approval_status is ApprovalStatus.PENDING
    assert workflow.get(proposal.proposal_id) is None
    approved = approve(workflow, proposal)
    assert approved.approval_status is ApprovalStatus.APPROVED
    assert workflow.get(proposal.proposal_id) is None
    workflow.save(approved, grants=frozenset({'checklist.save'}))
    assert workflow.get(proposal.proposal_id) == approved


def test_no_approval_or_forged_flag(workflow):
    proposal = workflow.prepare()
    with pytest.raises(SafeActionPermissionError):
        workflow.save(proposal, grants=frozenset({'checklist.save'}))
    with pytest.raises(ApprovalBindingError):
        workflow.save(replace(proposal, approval_status=ApprovalStatus.APPROVED), grants=frozenset({'checklist.save'}))
    assert workflow.get(proposal.proposal_id) is None


@pytest.mark.parametrize('changes', [{'title': 'Changed'}, {'items': ('Changed',)}, {'proposal_id': 'another'}])
def test_altered_proposals(workflow, changes):
    proposal = workflow.prepare()
    with pytest.raises(ApprovalBindingError):
        approve(workflow, replace(proposal, **changes))
    approved = approve(workflow, proposal)
    with pytest.raises(ApprovalBindingError):
        workflow.save(replace(approved, **changes), grants=frozenset({'checklist.save'}))
    assert workflow.get(proposal.proposal_id) is None
    workflow.save(approved, grants=frozenset({'checklist.save'}))


@pytest.mark.parametrize('changes', [{'decided_by': 'stranger'}, {'actor_kind': ActorKind.MODEL}, {'human_confirmed': False}])
def test_unauthorized_approvals(workflow, changes):
    proposal = workflow.prepare()
    with pytest.raises(HumanDecisionRequiredError):
        approve(workflow, proposal, **changes)
    assert workflow.get(proposal.proposal_id) is None


@pytest.mark.parametrize('grants', [frozenset(), frozenset({'*'}), frozenset({'other'})])
def test_permission_denial_does_not_consume(workflow, grants):
    approved = approve(workflow, workflow.prepare())
    with pytest.raises(SafeActionPermissionError):
        workflow.save(approved, grants=grants)
    workflow.save(approved, grants=frozenset({'checklist.save'}))


def test_expiry(workflow, monkeypatch):
    approved = approve(workflow, workflow.prepare())
    later = approvals._now() + timedelta(minutes=11)
    monkeypatch.setattr(approvals, '_now', lambda: later)
    with pytest.raises(ApprovalExpiredError):
        workflow.save(approved, grants=frozenset({'checklist.save'}))
    assert workflow.get(approved.proposal_id) is None


def test_replay(workflow):
    approved = approve(workflow, workflow.prepare())
    workflow.save(approved, grants=frozenset({'checklist.save'}))
    with pytest.raises(ApprovalConsumedError):
        workflow.save(approved, grants=frozenset({'checklist.save'}))
    assert workflow.get(approved.proposal_id) == approved


def test_restart_retrieval(workflow, tmp_path):
    approved = approve(workflow, workflow.prepare())
    workflow.save(approved, grants=frozenset({'checklist.save'}))
    restarted = SafeActionWorkflow(tmp_path/'runs.db', ApprovalManager())
    restarted.initialize()
    assert restarted.get(approved.proposal_id) == approved
    with pytest.raises(ApprovalBindingError):
        restarted.save(approved, grants=frozenset({'checklist.save'}))


def test_failed_insert_burns_approval(workflow, tmp_path):
    approved = approve(workflow, workflow.prepare())
    with sqlite3.connect(tmp_path/'runs.db') as conn:
        conn.execute("CREATE TRIGGER deny_insert BEFORE INSERT ON safeaction_checklists BEGIN SELECT RAISE(ABORT, 'private db detail'); END")
    with pytest.raises(SafeActionError) as exc:
        workflow.save(approved, grants=frozenset({'checklist.save'}))
    assert 'private' not in str(exc.value)
    assert workflow.get(approved.proposal_id) is None
    with pytest.raises(ApprovalConsumedError):
        workflow.save(approved, grants=frozenset({'checklist.save'}))
