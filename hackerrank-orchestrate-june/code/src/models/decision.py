from pydantic import BaseModel
from typing import List, Literal
from src.models.vlm import VLMReasoning

class DecisionIntermediateState(BaseModel):
    evidence_standard_met: bool
    claim_status: Literal["supported", "contradicted", "not_enough_information"]
    supporting_image_ids: List[str]
    valid_image: bool
    severity: Literal["none", "low", "medium", "high", "unknown"]
    issue_type: str
    object_part: str
    risk_flags_array: List[str]
    best_image_vlm_reasoning: VLMReasoning
