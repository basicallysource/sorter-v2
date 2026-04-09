# Hive Sorter Client

Python client for the Hive machine API. Used by sorting machines to send heartbeats and upload classification samples.

## Installation

The client requires the `requests` library:

```bash
pip install requests
```

## Python Usage

```python
from pathlib import Path
from hive_client import HiveClient

client = HiveClient(
    api_url="https://hive.example.com",
    api_token="your-machine-api-token",
)

# Send heartbeat
client.heartbeat(hardware_info={"cpu": "RPi5", "camera": "picam3"})

# Upload a sample
result = client.upload_sample(
    source_session_id="session-2025-01-15-001",
    local_sample_id="sample-0042",
    image_path=Path("captures/sample_0042.png"),
    source_role="classification",
    capture_reason="carousel_snap",
    detection_algorithm="nanodet",
    detection_count=1,
    detection_score=0.95,
)
print(result)
```

## curl Examples

### Heartbeat

```bash
curl -X POST https://hive.example.com/api/machine/heartbeat \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"hardware_info": {"cpu": "RPi5", "camera": "picam3"}}'
```

### Upload a Sample

```bash
curl -X POST https://hive.example.com/api/machine/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F 'metadata={"source_session_id": "session-2025-01-15-001", "local_sample_id": "sample-0042", "source_role": "classification", "capture_reason": "carousel_snap", "detection_algorithm": "nanodet", "detection_count": 1, "detection_score": 0.95}' \
  -F "image=@captures/sample_0042.png"
```

### Upload with Full Frame and Overlay

```bash
curl -X POST https://hive.example.com/api/machine/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F 'metadata={"source_session_id": "session-2025-01-15-001", "local_sample_id": "sample-0043"}' \
  -F "image=@captures/sample_0043.png" \
  -F "full_frame=@captures/full_frame_0043.png" \
  -F "overlay=@captures/overlay_0043.png"
```

### Metadata JSON Structure

```json
{
  "source_session_id": "session-2025-01-15-001",
  "local_sample_id": "sample-0042",
  "source_role": "classification",
  "capture_reason": "carousel_snap",
  "captured_at": "2025-01-15T14:30:00Z",
  "session_name": "Evening sorting run",
  "detection_algorithm": "nanodet",
  "detection_bboxes": [{"x": 100, "y": 150, "w": 64, "h": 64}],
  "detection_count": 1,
  "detection_score": 0.95
}
```

Required fields: `source_session_id`, `local_sample_id`

All other fields are optional.
