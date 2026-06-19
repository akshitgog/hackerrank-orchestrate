import csv
import json
from pathlib import Path

def load_data(file_path: str) -> list[dict]:
    """
    Seamlessly loads either a CSV or JSON file into a list of Python dictionaries.
    This completely hides the file format from the Orchestrator, allowing it to easily
    switch between 'production' CSVs and 'mock' JSONs without changing any pipeline logic.
    """
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"Data file not found: {path}")
        
    try:
        if path.suffix.lower() == '.csv':
            with open(path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                return [row for row in reader]
                
        elif path.suffix.lower() == '.json':
            with open(path, mode='r', encoding='utf-8-sig') as f:
                data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError(f"JSON root must be a list of dictionaries. Got {type(data).__name__}.")
                if len(data) > 0 and not isinstance(data[0], dict):
                    raise ValueError(f"JSON list must contain dictionaries. Got {type(data[0]).__name__}.")
                
                # Normalize JSON-native types to CSV-equivalent flat strings
                for row in data:
                    for key, value in row.items():
                        if isinstance(value, list):
                            row[key] = ";".join(str(v) for v in value)
                        elif value is None:
                            row[key] = ""
                        elif isinstance(value, (int, float, bool)):
                            row[key] = str(value)
                            
                return data
                
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}. Loader only supports .csv or .json")
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON file at {path}: {str(e)}")
    except Exception as e:
        raise ValueError(f"Error reading file {path}: {str(e)}")
