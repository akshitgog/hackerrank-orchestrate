import json
from src.core.config import config
from src.models.extractor import ExtractorOutput
import instructor
from litellm import acompletion

class ExtractorEngine:
    def __init__(self):
        self.model = config.providers.get("extractor", {}).get("model", "mock")
        
        if self.model == "mock":
            # Extract expected values directly from mock_claims.json to simulate an LLM
            paths = config.get_dataset_paths("mock")
            with open(paths["claims_file"], "r", encoding="utf-8") as f:
                mock_claims = json.load(f)
                
            self.mock_db = {}
            for row in mock_claims:
                uid = row["claim_input"]["user_id"]
                expected = row["expected_output"]
                self.mock_db[uid] = ExtractorOutput(
                    object=expected["claim_object"],
                    component=expected["object_part"],
                    issue=expected["issue_type"]
                )
                
    async def extract_claim_details(self, user_id: str, user_claim: str) -> ExtractorOutput:
        if self.model == "mock":
            if user_id in self.mock_db:
                return self.mock_db[user_id]
            else:
                print(f"[Extractor Mock] Warning: user {user_id} not found in mock DB. Returning generic mock data.")
                return ExtractorOutput(object="car", component="door", issue="dent")
        else:
            prompt = f"""Extract the damaged object, the specific component, and the issue from this user claim.

Allowed object values: car, laptop, package, unknown

Allowed component values per object:
- car: front_bumper, rear_bumper, door, hood, windshield, side_mirror, headlight, taillight, fender, quarter_panel, body, unknown
- laptop: screen, keyboard, trackpad, hinge, lid, corner, port, base, body, unknown
- package: box, package_corner, package_side, seal, label, contents, item, unknown

Allowed issue values: dent, scratch, crack, glass_shatter, broken_part, missing_part, torn_packaging, crushed_packaging, water_damage, stain, none, unknown

Important Rules:
1. You MUST pick the closest matching value from the allowed lists above.
2. If multiple components are mentioned, pick the PRIMARY one the user is most focused on.
3. If the object is not explicitly mentioned and cannot be confidently deduced from the component (e.g. user just says "it's broken"), you MUST output 'unknown' for the object instead of guessing.

Claim: {user_claim}"""
            client = instructor.from_litellm(acompletion, mode=instructor.Mode.MD_JSON)
            try:
                resp = await client.chat.completions.create(
                    model=self.model,
                    response_model=ExtractorOutput,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=180,
                    max_retries=1
                )
                return resp
            except Exception as e:
                print(f"[Extractor] API Failed: {e}")
                return ExtractorOutput(object="unknown", component="unknown", issue="unknown")

extractor_engine = ExtractorEngine()
