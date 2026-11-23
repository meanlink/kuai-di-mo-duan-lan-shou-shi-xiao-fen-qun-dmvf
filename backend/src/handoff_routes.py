from fastapi import APIRouter, Depends

from . import handoff_audit, recovery_dispatch
from .auth import allow, current_user
from .db import session
from .expansion import load
from .expansion_schemas import ReviewNote, SupportPlan
from .handoff_models import HandoffAudit, RecoveryDispatch
from .handoff_schemas import HandoffRequest, RecoveryRequest, RecoveryVerification

router = APIRouter()
operators = allow('admin', 'analyst')
managers = allow('admin')


@router.get('/handoff-audits')
def audits(db=Depends(session), _user=Depends(current_user)):
    return handoff_audit.ledger(db)


@router.get('/handoff-audits/{key}')
def audit_detail(key: int, db=Depends(session), _user=Depends(current_user)):
    return handoff_audit.audit_detail(db, load(db, HandoffAudit, key, '交接证据'))


@router.post('/handoff-audits', status_code=201)
def inspect_handoff(payload: HandoffRequest, db=Depends(session), user=Depends(operators)):
    return handoff_audit.inspect_handoff(db, payload.support_id, user.username)


@router.get('/recovery-dispatches')
def dispatches(db=Depends(session), _user=Depends(current_user)):
    return recovery_dispatch.dispatch_list(db)


@router.get('/recovery-dispatches/{key}')
def dispatch_detail(key: int, db=Depends(session), _user=Depends(current_user)):
    return recovery_dispatch.dispatch_detail(db, load(db, RecoveryDispatch, key, '补派单'))


@router.post('/recovery-dispatches', status_code=201)
def propose(payload: RecoveryRequest, db=Depends(session), user=Depends(operators)):
    return recovery_dispatch.propose(db, payload, user.username)


@router.post('/recovery-dispatches/{key}/release')
def release(key: int, payload: ReviewNote, db=Depends(session), user=Depends(managers)):
    return recovery_dispatch.release(db, key, payload, user.username)


@router.post('/recovery-dispatches/{key}/verify')
def verify(key: int, payload: RecoveryVerification, db=Depends(session), user=Depends(operators)):
    return recovery_dispatch.verify(db, key, payload, user.username)


@router.post('/recovery-dispatches/{key}/replan')
def replan(key: int, payload: SupportPlan, db=Depends(session), user=Depends(operators)):
    return recovery_dispatch.replan(db, key, payload, user.username)
