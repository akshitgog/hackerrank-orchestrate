import sys
import argparse
import csv
import json
import asyncio
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent))

from src.core.config import config
from src.core.data_loader import load_data
from src.tools.risk_engine import process_user_risk
from src.tools.extractor_engine import extractor_engine
from src.tools.vlm_engine import vlm_engine
from src.tools.decision_engine import decision_engine
from src.tools.explanation_generator import explanation_generator

def get_evidence_requirements(obj: str, reqs: list) -> str:
    for r in reqs:
        if r.get("claim_object", "").lower() == obj.lower():
            return r.get("minimum_image_evidence", "")
    return "Provide clear image of the damaged object."

async def process_image_with_semaphore(semaphore, uid, img_id, full_img_path, claim_text, extracted, ev_req, cache_file, use_cache):
    # Try loading from cache first
    if use_cache and cache_file.exists():
        from src.models.vlm import VLMOutput
        with open(cache_file, "r") as f:
            vlm_out = VLMOutput(**json.load(f))
        print(f"  [VLM] Loaded {img_id} instantly from local cache.")
        return img_id, vlm_out

    # Enforce concurrency limit with Semaphore
    async with semaphore:
        try:
            print(f"  [VLM] Assessing {img_id} via AWS Bedrock...")
            vlm_out = await vlm_engine.assess_image(
                user_id=uid, image_id=img_id, image_path=full_img_path,
                claim_text=claim_text, object_type=extracted.object,
                component=extracted.component, issue=extracted.issue, evidence_reqs=ev_req
            )
            print(f"  [VLM] {img_id} finished. Risk: {vlm_out.authenticity_risk}, Support: {vlm_out.support_signal}")
            
            if use_cache:
                dump_data = vlm_out.model_dump()
                with open(cache_file, "w") as f:
                    json.dump(dump_data, f, indent=2)
                    
            return img_id, vlm_out
        except Exception as e:
            print(f"Warning: VLM failed for {img_id}: {e}")
            return img_id, None

async def run_pipeline(env: str, use_cache: bool = False):
    paths = config.get_dataset_paths(env)
    
    claims_file = paths.get("claims_file")
    history_file = paths.get("user_history_file", paths.get("users_file"))
    req_file = paths.get("evidence_requirements_file")
    out_file = paths.get("output_file", "output.csv")
    
    print(f"Loading datasets for environment: {env.upper()}")
    claims_data = load_data(claims_file)
    users_data = load_data(history_file)
    reqs_data = load_data(req_file) if req_file else []
    
    user_dict = {u["user_id"]: u for u in users_data}
    final_output = []
    
    # Global semaphore to limit concurrent AWS Bedrock calls based on VLM limits
    vlm_concurrency = config.providers.get("vlm", {}).get("concurrency", 5)
    semaphore = asyncio.Semaphore(vlm_concurrency)
    
    print(f"Processing {len(claims_data)} claims...")
    
    for row in claims_data:
        claim = row["claim_input"] if "claim_input" in row else row
            
        uid = claim["user_id"]
        img_paths_str = claim.get("image_paths", "")
        img_paths = img_paths_str.split(";") if img_paths_str else []
        claim_text = claim.get("user_claim", "")
        obj_type = claim.get("claim_object", "unknown")
        
        print(f"\n--- Processing Claim: {uid} ---")
        
        # 1. Risk Engine
        history_flags = process_user_risk(user_dict[uid]) if uid in user_dict else []
            
        # 2. Extractor (Async)
        print(f"  [Extractor] Analyzing claim text: '{claim_text}'")
        extracted = await extractor_engine.extract_claim_details(uid, claim_text)
        print(f"  [Extractor] Found -> Object: {extracted.object}, Component: {extracted.component}, Issue: {extracted.issue}")
        
        # 3. Reqs
        ev_req = get_evidence_requirements(obj_type, reqs_data)
        
        # 4. VLM Engine (Async + Gather)
        vlm_results = {}
        cache_dir = Path("test_cache")
        if use_cache:
            cache_dir.mkdir(exist_ok=True)
            
        tasks = []
        for path in img_paths:
            img_id = Path(path).stem
            full_img_path = str(Path(paths.get("base_dir", "dataset")) / path)
            cache_file = cache_dir / f"{uid}_{img_id}.json"
            
            # Queue up the task
            task = asyncio.create_task(
                process_image_with_semaphore(
                    semaphore, uid, img_id, full_img_path, claim_text, 
                    extracted, ev_req, cache_file, use_cache
                )
            )
            tasks.append(task)
            
        # Wait for all images in this claim to process concurrently
        results = await asyncio.gather(*tasks)
        for img_id, vlm_out in results:
            if vlm_out:
                vlm_results[img_id] = vlm_out
                
        # 5. Decision Engine
        print("  [Decision Engine] Aggregating multi-modal evidence...")
        decision = decision_engine.decide(vlm_results, history_flags)
        print(f"  [Decision Engine] Final Status: {decision['claim_status']}")
        
        # 6. Explanation Generator (Async)
        print("  [Generator] Drafting final explanation...")
        expl = await explanation_generator.generate(decision)
        print(f"  [Generator] Justification: {expl['claim_status_justification']}")
        
        # Build CSV Row
        final_row = {
            "user_id": uid,
            "image_paths": img_paths_str,
            "user_claim": claim_text,
            "claim_object": obj_type,
            "evidence_standard_met": decision["evidence_standard_met"],
            "evidence_standard_met_reason": expl["evidence_standard_met_reason"],
            "risk_flags": ";".join(decision["risk_flags_array"]) if decision["risk_flags_array"] else "none",
            "issue_type": extracted.issue,
            "object_part": extracted.component,
            "claim_status": decision["claim_status"],
            "claim_status_justification": expl["claim_status_justification"],
            "supporting_image_ids": ";".join(decision["supporting_image_ids"]),
            "valid_image": decision["valid_image"],
            "severity": decision["severity"]
        }
        final_output.append(final_row)
        
    print(f"\nWriting {len(final_output)} records to {out_file}...")
    
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=final_output[0].keys(), quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(final_output)
        
    print("Pipeline Execution Complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the HackerRank Orchestrate Pipeline")
    parser.add_argument("--env", default="mock", choices=["mock", "test", "production"], help="Environment to run against")
    parser.add_argument("--cache", action="store_true", help="Cache VLM outputs locally to speed up prompt iteration")
    args = parser.parse_args()
    
    # Run the async event loop
    asyncio.run(run_pipeline(args.env, args.cache))
