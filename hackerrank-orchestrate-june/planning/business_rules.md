# Business Rules: Risk & Manual Review

These rules define the exact relationship between historical risk and manual review requirements, as decided by the user's architectural review.

### 1. When do we add `user_history_risk`?
**Who decides it:** Risk Engine
**Rule:** Added based on historical statistics:
- If `last_90_days_claim_count >= 3`
- If `rejected_claim >= 2`
- (Or if statically present in legacy CSV)

### 2. When do we add `manual_review_required`?
**Who decides it:** Decision Engine ONLY
**Rule:** 
The Risk Engine NEVER assigns `manual_review_required`. It only assigns `user_history_risk`.
The Decision Engine assigns `manual_review_required` ONLY IF:
1. The claim is currently leaning towards `supported` OR `not_enough_information`, BUT the user has `user_history_risk`.
2. A visual `authenticity_flag` is tripped by the VLM (e.g., manipulated image).

**CRITICAL EXCEPTION (The Auto-Reject Rule):**
If the VLM provides undeniable evidence that the claim is `contradicted` (e.g., the user claims car damage but uploads a photo of a dog), the Decision Engine will output `contradicted` and **will NOT assign** `manual_review_required`, even if the user has a risky history. Why waste a human's time reviewing an obvious lie?
