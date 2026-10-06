import os
from pathlib import Path
from src.core.config import config

def resolve_image_paths(image_paths_string: str, env: str = "production") -> list[Path]:
    """
    Takes the semicolon-separated image paths from claims.csv and resolves them to absolute Paths.
    Provides robust fallbacks to ensure images are found regardless of how they are formatted in the CSV.
    """
    if not image_paths_string or str(image_paths_string).lower().strip() == "none":
        return []
        
    dataset_paths = config.get_dataset_paths(env)
    base_images_dir = Path(dataset_paths.get("images_dir", "dataset/images"))
    
    resolved_paths = []
    raw_paths = [p.strip() for p in image_paths_string.split(";") if p.strip()]
    
    for raw_path in raw_paths:
        # 1. Try treating it as an absolute path (in case user pasted full path)
        p = Path(raw_path)
        if p.is_absolute() and p.exists():
            resolved_paths.append(p)
            continue
            
        # 2. Try resolving it relatively against the configured images directory
        relative_p = base_images_dir / raw_path
        if relative_p.exists():
            resolved_paths.append(relative_p.resolve())
            continue
            
        # 3. Fallback: if the CSV accidentally included the 'dataset/images/' prefix, strip it and try again
        if raw_path.startswith("dataset/images/"):
            stripped = raw_path.replace("dataset/images/", "")
            fallback_p = base_images_dir / stripped
            if fallback_p.exists():
                resolved_paths.append(fallback_p.resolve())
                continue
                
        # 4. If the file is simply missing from disk, we still append the target path
        # so the pipeline can gracefully fail (e.g. flag it as missing rather than crash)
        resolved_paths.append(relative_p.resolve())
        
    return resolved_paths
