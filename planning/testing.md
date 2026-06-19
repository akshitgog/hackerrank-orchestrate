# Testing Strategy

The testing stack isolates different layers of the system. The key principle is to not use one dataset for all three purposes:

### 1. Logic Regression Dataset
- **Purpose**: Test the Risk Engine, Decision Engine, and Output Generator without VLM API costs.
- **Mechanism**: Configure `providers.yaml` to `provider: mock`. The `mock.py` client intercepts requests and returns static JSON fixtures.
- **Mock Generation Required**:
  - **50 Mock Users**: JSON objects matching the `user_history` schema.
  - **50 Mock Claims**: JSON objects simulating extractor output.
  - **~125 Mock VLM Outputs**: Because each claim contains 2-3 images, the `mock.py` provider needs around 125 unique VLM JSON responses to return when queried.
- **Expected Result**: The Decision Engine automatically ingests the user history and the ~125 VLM outputs. We assert its final output against 50 expected final CSV rows.

### 2. Synthetic Claim Dataset
- **Purpose**: Test full pipeline behavior on complex edge cases (e.g., multiple conflicting images, annotated images, zoomed images, wrong components).
- **Input**: Generated claims, user history, expected VLM outputs, and (optionally) generated matching images.
- **Target**: 20-30 edge claims.
- **Expected**: Final CSV rows matching edge-case behavior.

### 3. Organizer Dataset
- **Purpose**: Measure actual competition performance.
- **Input**: The provided `dataset/sample_claims.csv` and provided test images.
- **Target**: Real competition data.
- **Expected**: Output matches provided expected CSV.
