import os
import yaml
import litellm
from pathlib import Path
from dotenv import load_dotenv

# Since config.py is inside code/src/core/
# parent 1: core, parent 2: src, parent 3: code, parent 4: root
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = BASE_DIR / "config"

class AppConfig:
    def __init__(self):
        # Load API keys and environment variables from .env file
        load_dotenv(BASE_DIR / ".env")
        
        # Configure LiteLLM to drop unsupported parameters (like tool_choice on certain Bedrock models)
        litellm.drop_params = True
        litellm.set_verbose = False
        
        # Load dataset config
        with open(CONFIG_DIR / "dataset.yaml", "r") as f:
            self.dataset_config = yaml.safe_load(f)
            
        # Load provider config
        with open(CONFIG_DIR / "providers.yaml", "r") as f:
            self.providers = yaml.safe_load(f)

    def get_dataset_paths(self, env: str = "production") -> dict:
        """
        Returns the specific dataset paths based on the environment ('production', 'sample', or 'mock').
        This ensures the pipeline correctly switches between CSV files in production and JSON files in mock.
        """
        if env not in self.dataset_config:
            raise ValueError(f"Environment '{env}' not found in dataset.yaml")
        
        # Resolve all paths relative to BASE_DIR
        paths = self.dataset_config[env]
        resolved = {}
        for key, relative_path in paths.items():
            resolved[key] = str(BASE_DIR / relative_path)
        return resolved

config = AppConfig()
