import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.core.image_loader import resolve_image_paths

def test_image_loader():
    print("Testing Image Loader...")
    
    # Test semicolon separation and whitespace
    raw_string = "sample/case_001/img1.jpg; sample/case_001/img2.jpg "
    paths = resolve_image_paths(raw_string, env="sample")
    
    assert len(paths) == 2, "Failed to split semicolons properly"
    assert "img1.jpg" in str(paths[0]), "Failed to extract first image"
    assert "img2.jpg" in str(paths[1]), "Failed to extract second image"
    
    print(f"Successfully resolved to absolute paths:")
    for p in paths:
        print(f" -> {p}")
        
    print("Success: Image loader is robust!")

if __name__ == "__main__":
    test_image_loader()
