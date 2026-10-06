from typing import Dict, List
from src.models.vlm import VLMOutput

class DecisionEngine:
    def decide(self, vlm_outputs: Dict[str, VLMOutput], history_flags: List[str]) -> dict:
        valid_image = False
        supporting_image_ids = []
        contradicting_image_ids = []
        best_reasoning = None
        severity_per_image = {}
        
        has_contradict = False
        has_support = False
        
        all_risk_flags = set(history_flags)
        
        # 1. Aggregate VLM responses across all images for the claim
        for img_id, vlm in vlm_outputs.items():
            for risk in vlm.risk_flags:
                if risk != "none":
                    all_risk_flags.add(risk)
                    
            if vlm.support_signal == "support":
                # TWEAK 2: Lazy LLM Check
                if (vlm.reasoning.object_evidence == vlm.reasoning.component_evidence == vlm.reasoning.issue_evidence):
                    continue # Treat this specific image's output as invalid
                
                # TWEAK 1: Ambiguity Threshold
                if vlm.support_strength < 4 and vlm.image_quality in ["acceptable", "poor"]:
                    continue # Reject weak support on bad images
                    
                has_support = True
                valid_image = True
                supporting_image_ids.append(img_id)
                if not best_reasoning:
                    best_reasoning = vlm.reasoning.model_dump()
                    
            elif vlm.support_signal == "contradict":
                has_contradict = True
                valid_image = True
                contradicting_image_ids.append(img_id)
                if not best_reasoning:
                    best_reasoning = vlm.reasoning.model_dump()
                
            # Track severity per image
            severity_per_image[img_id] = vlm.issue_severity
                
        # 2. Determine base status (Contradiction overrides Support)
        if has_contradict:
            claim_status = "contradicted"
        elif has_support:
            claim_status = "supported"
        else:
            claim_status = "not_enough_information"
            
        # 3. evidence_standard_met: true if images were sufficient to evaluate
        #    (both supported AND contradicted mean the images were sufficient)
        evidence_met = has_support or has_contradict
            
        # 4. Build final image IDs list
        if claim_status == "supported":
            final_image_ids = supporting_image_ids
        elif claim_status == "contradicted":
            final_image_ids = contradicting_image_ids
        else:
            final_image_ids = ["none"]
            
        # 5. Calculate severity only from the images that drove the decision
        highest_severity = "unknown"
        severity_map = {"unknown": 0, "none": 1, "low": 2, "medium": 3, "high": 4}
        if claim_status != "not_enough_information":
            for img_id in final_image_ids:
                sev = severity_per_image.get(img_id, "unknown")
                if severity_map.get(sev, 0) > severity_map.get(highest_severity, 0):
                    highest_severity = sev
            
        # 5. Apply risk flag escalation: manual_review_required ONLY from user history
        if "user_history_risk" in all_risk_flags:
            all_risk_flags.add("manual_review_required")
                
        return {
            "evidence_standard_met": str(evidence_met).lower(),
            "claim_status": claim_status,
            "supporting_image_ids": final_image_ids,
            "valid_image": str(valid_image).lower(),
            "severity": highest_severity,
            "risk_flags_array": sorted(list(all_risk_flags)),
            "best_image_vlm_reasoning": best_reasoning
        }

decision_engine = DecisionEngine()
