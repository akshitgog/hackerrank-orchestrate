import json
from src.core.config import config
from src.models.vlm import VLMOutput

import instructor
from litellm import completion, acompletion

class VLMEngine:
    """
    A unified 5-line VLM Engine powered by LiteLLM.
    We drop the bloated Providers architecture. 
    LiteLLM abstracts 100+ providers via strings (e.g. 'bedrock/anthropic.claude-sonnet').
    """
    def __init__(self):
        # We read the single model string from providers.yaml
        self.model = config.providers.get("vlm", {}).get("model", "mock")
        
        # If mock, pre-load the JSON database into memory
        if self.model == "mock":
            paths = config.get_dataset_paths("mock")
            with open(paths["vlm_data_file"], 'r', encoding='utf-8') as f:
                self.mock_data = json.load(f)
                
    async def assess_image(
        self, 
        user_id: str, 
        image_id: str, 
        image_path: str, 
        claim_text: str, 
        object_type: str, 
        component: str, 
        issue: str, 
        evidence_reqs: str
    ) -> VLMOutput:
        """
        Builds the prompt and executes the VLM call.
        """
        import asyncio
        # 1. Build the dynamic VLM prompt from the external text file
        prompt_path = "code/prompts/vlm_system_prompt.txt"
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            base_prompt = f.read()
            
        prompt = base_prompt.replace("{object}", object_type) \
                            .replace("{component}", component) \
                            .replace("{issue}", issue) \
                            .replace("{user_claim}", claim_text) \
                            .replace("{evidence_requirements}", evidence_reqs) \
                            .replace("{image_id}", image_id)
        
        # 2. Execute against the configured LiteLLM model
        if self.model == "mock":
            if image_id not in self.mock_data:
                print(f"[VLM Mock] Warning: {image_id} not found in mock DB. Generating generic mock response.")
                fallback = {
                    "image_id": image_id,
                    "object_detected": object_type,
                    "object_confidence": 5,
                    "object_match": True,
                    "component_detected": component,
                    "component_visible": True,
                    "component_visibility": 5,
                    "component_match": True,
                    "issue_detected": issue,
                    "issue_visible": True,
                    "issue_strength": 5,
                    "issue_match": True,
                    "issue_location_description": "center",
                    "issue_severity": "low",
                    "image_quality": "good",
                    "image_quality_strength": 5,
                    "authenticity_risk": "low",
                    "risk_flags": ["none"],
                    "support_signal": "support",
                    "support_strength": 5,
                    "requirement_failures": ["none"],
                    "reasoning": {
                        "object_evidence": "Mock object detected",
                        "component_evidence": "Mock component detected",
                        "issue_evidence": "Mock issue detected"
                    }
                }
                return VLMOutput(**fallback)
                
            return VLMOutput(**self.mock_data[image_id])
            
        else:
            import base64
            from PIL import Image
            import io
            
            # Convert any weird formats (like hidden AVIFs) to pure JPEG in memory
            with Image.open(image_path) as img:
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG")
                encoded_string = base64.b64encode(buf.getvalue()).decode('utf-8')
                
            image_url = f"data:image/jpeg;base64,{encoded_string}"
            
            client = instructor.from_litellm(acompletion, mode=instructor.Mode.MD_JSON)
            
            import asyncio
            vlm_config = config.providers.get("vlm", {})
            sleep_time = vlm_config.get("sleep_seconds", 0)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            
            try:
                resp = await client.chat.completions.create(
                    model=self.model,
                    response_model=VLMOutput,
                    messages=[
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt}, 
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ]}
                    ],
                    timeout=180,
                    max_retries=vlm_config.get("max_retries", 1)
                )
                return resp
            except Exception as e:
                print(f"[VLM] API Failed: {e}")
                raise e

vlm_engine = VLMEngine()
