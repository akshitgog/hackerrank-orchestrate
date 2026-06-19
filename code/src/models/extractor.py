from pydantic import BaseModel, Field

from typing import Literal

class ExtractorOutput(BaseModel):
    object: Literal["car", "laptop", "package", "unknown"] = Field(..., description="The main object claimed")
    component: Literal[
        "front_bumper", "rear_bumper", "door", "hood", "windshield", "side_mirror", "headlight", "taillight", "fender", "quarter_panel", "body",
        "screen", "keyboard", "trackpad", "hinge", "lid", "corner", "port", "base",
        "box", "package_corner", "package_side", "seal", "label", "contents", "item", "unknown"
    ] = Field(..., description="The specific part claimed. If multiple, pick the primary one.")
    issue: Literal[
        "dent", "scratch", "crack", "glass_shatter", "broken_part", "missing_part", "torn_packaging", "crushed_packaging", "water_damage", "stain", "none", "unknown"
    ] = Field(..., description="The specific issue claimed")
