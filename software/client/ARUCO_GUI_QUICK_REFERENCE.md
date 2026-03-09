# Quick Reference - ArUco GUI Integration

## 🚀 Quick Start

### Access the GUI
```
http://localhost:8000/aruco
```

### API Endpoints Summary
```
# Configuration
GET  /api/aruco/config                      → Full config JSON
GET  /api/aruco/categories                  → All categories with tags
GET  /api/aruco/tags/unassigned             → Unassigned tag IDs
GET  /api/aruco/tags/all                    → All detected tags
GET  /api/aruco/category/{name}             → Specific category

# Tag Management
POST /api/aruco/assign?tag_id=X&category=Y&role=Z    → Assign tag
POST /api/aruco/unassign?tag_id=X                    → Unassign tag

# Video Streaming
GET  /video_feed/feeder                     → Feeder camera MJPEG
GET  /video_feed/classification_bottom      → Bottom classification camera
GET  /video_feed/classification_top         → Top classification camera
```

## 📁 File Locations

| File | Purpose | Type |
|------|---------|------|
| `aruco_config.json` | Tag→Region assignments (git-ignored, local) | Config (auto-created) |
| `aruco_config_default.json` | Baseline default config (committed) | Config template |
| `aruco_config_manager.py` | Tag mgmt class | Python Module |
| `server/templates/aruco_config.html` | Web interface | HTML/CSS/JS |
| `server/api.py` | REST API + video streaming | FastAPI routes |
| `main.py` | Initialization | Python script |

## 🔌 Integration Points

### main.py
```python
# Import manager and setter function
from aruco_config_manager import ArucoConfigManager
from server.api import setArucoManager, setVisionManager

# In main() function:
aruco_mgr = ArucoConfigManager("aruco_config.json")
setArucoManager(aruco_mgr)
setVisionManager(vision)
```

### server/api.py
```python
# Global variables
aruco_manager: Optional[ArucoConfigManager] = None
vision_manager: Optional[Any] = None

# Setter functions
def setArucoManager(mgr: ArucoConfigManager) -> None
def setVisionManager(mgr: Any) -> None
```

## 💾 Configuration File Structure

```json
{
  "version": "1.0",
  "settings": {
    "aruco_smoothing_time_s": 0.35
  },
  "categories": {
    "unassigned": {
      "description": "...",
      "tags": [20, 31, 7]
    },
    "second_c_channel": {
      "description": "...",
      "radius_multiplier": 1.0,
      "tags": {
        "center": 20,
        "output_guide": null,
        "radius1": 31,
        "radius2": 7,
        "radius3": null,
        "radius4": null,
        "radius5": null
      }
    },
    "carousel_platform_1": {
      "description": "...",
      "tags": {
        "corner1": null,
        "corner2": null,
        "corner3": null,
        "corner4": null
      }
    }
  }
}
```

## 🎯 Key Python Classes

### ArucoConfigManager
```python
# Create instance
mgr = ArucoConfigManager("path/to/aruco_config.json")

# Assign a tag
mgr.assign_tag(tag_id=20, category="second_c_channel", role="center")

# Unassign a tag
mgr.unassign_tag(20)

# Query operations
unassigned = mgr.get_unassigned_tags()          # [20, 31, 7]
all_tags = mgr.get_all_tags()                   # [20, 31, 7, ...]
category = mgr.get_category("second_c_channel") # {...}
config = mgr.get_config_dict()                  # Full configuration

# Auto-discover new tags
mgr.populate_detected_tags([20, 31, 7, 14])     # Add to unassigned
```

## 🧬 Browser Developer Console Commands

### Test API Endpoints
```javascript
// Get current config
fetch('/api/aruco/config').then(r => r.json()).then(d => console.log(d))

// Get unassigned tags
fetch('/api/aruco/tags/unassigned').then(r => r.json()).then(d => console.log(d))

// Assign a tag
fetch('/api/aruco/assign?tag_id=20&category=second_c_channel&role=center', 
  {method: 'POST'}).then(r => r.json()).then(d => console.log(d))

// Unassign a tag
fetch('/api/aruco/unassign?tag_id=20', 
  {method: 'POST'}).then(r => r.json()).then(d => console.log(d))
```

## 🔍 Troubleshooting Commands

### Check if manager initialized
```bash
curl http://localhost:8000/api/aruco/config
```

### Check if video feed working
```bash
curl http://localhost:8000/video_feed/feeder -o frame.jpg
```

### Check JSON syntax
```bash
python3 -m json.tool aruco_config.json
```

### Reset configuration (if corrupt)
```bash
# Backup current config
cp aruco_config.json aruco_config.json.backup

# Delete config (will be re-seeded from aruco_config_default.json on next startup)
rm aruco_config.json

# Restart application
```

## 📊 Data Flow

```
User clicks tag in browser
    ↓
JavaScript sends POST /api/aruco/assign
    ↓
server/api.py assign_tag() endpoint
    ↓
ArucoConfigManager.assign_tag()
    ↓
Update config dict + sync to JSON
    ↓
Response sent to browser
    ↓
Browser updates UI, shows success status
```

## 🎨 HTML Form Workflow

1. Select tag: `<div class="tag">` → `selectTag(tagId)`
2. Assign to slot: `<div class="role-slot">` → `assignTag(category, role)`
3. Unassign: Click filled slot → `unassignTag(tagId)`
4. Auto-refresh: Every 5 seconds via `loadConfig()`

## 🔧 Common Modifications

### Add new category
Edit `aruco_config_manager.py` `_load_or_create_config()`:
```python
"new_category": {
    "description": "...",
    "tags": {"role1": None, "role2": None}
}
```

### Change MJPEG quality
Edit `server/api.py` `video_feed()`:
```python
quality = 85  # 0-100, higher = better quality but larger frames
```

### Change camera stream frame rate
Edit `server/api.py` `generate_frames()`:
```python
time.sleep(0.04)  # 0.04 = 25 FPS, 0.02 = 50 FPS, 0.03 = 33 FPS
```

## 🚨 Error Messages & Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "ArUco manager not initialized" | `setArucoManager()` not called | Check main.py initialization |
| "Vision manager not initialized" | `setVisionManager()` not called | Check main.py initialization |
| "Camera not available" | Camera endpoint not working | Verify `/video_feed/feeder` endpoint |
| "Failed to load config" | Network error or API crash | Check server logs |
| "File not found" | `aruco_config.json` missing | Will be copied from `aruco_config_default.json` on startup |

## 📚 Related Documentation

- `ARUCO_GUI_USAGE.md` - User guide
- `ARUCO_GUI_IMPLEMENTATION.md` - Full implementation details
- `vision_manager.py` - Camera frame interface
- `aruco_config_manager.py` - Tag management class
- `server/api.py` - REST API implementation
