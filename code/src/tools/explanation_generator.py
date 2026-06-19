from pydantic import BaseModel
import instructor
from litellm import completion, acompletion
from src.core.config import config
import os

class GeneratorOutput(BaseModel):
    evidence_standard_met_reason: str
    claim_status_justification: str

class ExplanationGenerator:
    def __init__(self):
        # Default to the generator config, fallback to VLM config
        generator_config = config.providers.get("generator", config.providers.get("vlm", {}))
        self.model = generator_config.get("model", "mock")
        
        # Load the prompt template
        prompt_path = "code/prompts/generator_system_prompt.txt"
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                self.base_prompt = f.read()
        else:
            self.base_prompt = "Status: {claim_status}. Write a justification based on Object: {object_evidence}, Component: {component_evidence}, Issue: {issue_evidence}."
                
    async def generate(self, decision_state: dict) -> dict:
        status = decision_state.get("claim_status", "unknown")
        flags = decision_state.get("risk_flags_array", [])
        
        # The decision engine passes the raw reasoning dict from the best image (with safe fallback for None)
        reasoning = decision_state.get("best_image_vlm_reasoning") or {}
        obj_ev = reasoning.get("object_evidence", "No evidence provided.")
        comp_ev = reasoning.get("component_evidence", "No evidence provided.")
        issue_ev = reasoning.get("issue_evidence", "No evidence provided.")
        
        # 1. Handle Mock Environment
        if self.model == "mock":
            if status == "supported":
                met = "The submitted images provide clear and sufficient visible evidence."
                just = f"Visual evidence confirms the claim. Mock Evidence: {obj_ev}"
            elif status == "contradicted":
                met = "The submitted images contradict the user's claim."
                just = f"Visible evidence directly conflicts with the stated claim. Mock Evidence: {obj_ev}"
            else:
                met = "The submitted images do not provide enough clear evidence."
                just = f"Could not verify the claim from the provided images due to lack of visibility. Mock Evidence: {obj_ev}"
            return {"evidence_standard_met_reason": met, "claim_status_justification": just}
            
        # 2. Real LLM Execution
        prompt = self.base_prompt.replace("{claim_status}", status) \
                                 .replace("{risk_flags}", ", ".join(flags) if flags else "None") \
                                 .replace("{object_evidence}", obj_ev) \
                                 .replace("{component_evidence}", comp_ev) \
                                 .replace("{issue_evidence}", issue_ev)
                                 
        import asyncio
        client = instructor.from_litellm(acompletion, mode=instructor.Mode.MD_JSON)
        
        gen_config = config.providers.get("generator", {})
        sleep_time = gen_config.get("sleep_seconds", 0)
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        
        try:
            # Real LLM API Call
            resp = await client.chat.completions.create(
                model=self.model,
                response_model=GeneratorOutput,
                messages=[{"role": "user", "content": prompt}],
                timeout=180,
                max_retries=gen_config.get("max_retries", 1)
            )
            return resp.model_dump()
        except Exception as e:
            print(f"Generator LLM Execution Failed: {e}")
            # Fallback in case of API failure
            return {
                "evidence_standard_met_reason": "API generation failed.",
                "claim_status_justification": "API generation failed."
            }

explanation_generator = ExplanationGenerator()
