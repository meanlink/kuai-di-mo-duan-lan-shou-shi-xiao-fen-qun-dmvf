from pydantic import Field

from .expansion_schemas import ReviewNote, SupportPlan
from .schemas import Input


class HandoffRequest(Input):
    support_id: int = Field(gt=0)


class RecoveryRequest(SupportPlan):
    audit_id: int = Field(gt=0)


class RecoveryVerification(ReviewNote):
    batch_code: str = Field(min_length=1, max_length=32)
