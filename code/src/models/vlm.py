from pydantic import BaseModel, Field
from typing import List, Literal

class VLMReasoning(BaseModel):
    object_evidence: str
    component_evidence: str
    issue_evidence: str

class VLMOutput(BaseModel):
    image_id: str
    object_detected: str
    object_confidence: int = Field(ge=1, le=5)
    object_match: bool
    component_detected: str
    component_visible: bool
    component_visibility: int = Field(ge=1, le=5)
    component_match: bool
    issue_detected: str
    issue_visible: bool
    issue_strength: int = Field(ge=1, le=5)
    issue_match: bool
    issue_location_description: str
    issue_severity: Literal["none", "low", "medium", "high", "unknown"]
    image_quality: Literal["good", "acceptable", "poor", "unusable"]
    image_quality_strength: int = Field(ge=1, le=5)
    authenticity_risk: Literal["low", "medium", "high"]
    risk_flags: List[Literal["none", "blurry_image", "cropped_or_obstructed", "low_light_or_glare", "wrong_angle", "wrong_object", "wrong_object_part", "damage_not_visible", "claim_mismatch", "possible_manipulation", "non_original_image", "text_instruction_present"]]
    support_signal: Literal["support", "contradict", "insufficient"]
    support_strength: int = Field(ge=1, le=5)
    requirement_failures: List[Literal["none", "claimed_object_not_visible", "claimed_component_not_visible", "issue_not_visible", "image_quality_insufficient", "claimed_component_not_visible_due_to_crop", "authenticity_concern"]]
    reasoning: VLMReasoning
