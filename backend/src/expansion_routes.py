from fastapi import APIRouter, Depends

from . import expansion
from .auth import allow, current_user
from .db import session
from .expansion_models import ShiftFollowup, ShiftSupport
from .expansion_schemas import (
    FollowupPlan, ReviewNote, SupportCompletion, SupportDecision, SupportPlan, SupportRequest,
)

router = APIRouter()
operators = allow('admin', 'analyst')
managers = allow('admin')


@router.get('/followups')
def followups(db=Depends(session), _user=Depends(current_user)):
    return expansion.followup_list(db)


@router.get('/followups/{key}')
def followup(key: int, db=Depends(session), _user=Depends(current_user)):
    return expansion.followup_detail(db, expansion.load(db, ShiftFollowup, key, '班次复测'))


@router.post('/followups', status_code=201)
def schedule(payload: FollowupPlan, db=Depends(session), user=Depends(operators)):
    return expansion.schedule_followup(db, payload, user.username)


@router.post('/followups/{key}/measure')
def measure(key: int, db=Depends(session), user=Depends(operators)):
    return expansion.measure_followup(db, key, user.username)


@router.post('/followups/{key}/review')
def review(key: int, payload: ReviewNote, db=Depends(session), user=Depends(managers)):
    return expansion.review_followup(db, key, payload, user.username)


@router.get('/supports')
def supports(db=Depends(session), _user=Depends(current_user)):
    return expansion.support_list(db)


@router.get('/supports/{key}')
def support(key: int, db=Depends(session), _user=Depends(current_user)):
    return expansion.support_detail(db, expansion.load(db, ShiftSupport, key, '支援单'))


@router.post('/supports', status_code=201)
def request_support(payload: SupportRequest, db=Depends(session), user=Depends(operators)):
    return expansion.request_support(db, payload, user.username)


@router.post('/supports/{key}/resubmit')
def resubmit(key: int, payload: SupportPlan, db=Depends(session), user=Depends(operators)):
    return expansion.resubmit_support(db, key, payload, user.username)


@router.post('/supports/{key}/decide')
def decide(key: int, payload: SupportDecision, db=Depends(session), user=Depends(managers)):
    return expansion.decide_support(db, key, payload, user.username)


@router.post('/supports/{key}/complete')
def complete(key: int, payload: SupportCompletion, db=Depends(session), user=Depends(operators)):
    return expansion.complete_support(db, key, payload, user.username)
