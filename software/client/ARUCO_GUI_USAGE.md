# ArUco Tag Configuration GUI

This guide explains how to use the web-based ArUco tag configuration interface to assign tags to different regions and carousel platforms.

## Overview

The ArUco Tag Configuration GUI replaces hardcoded tag assignments with a dynamic, persistent JSON-based system. Instead of editing Python code to change which ArUco tags define which regions, users can now use an interactive web interface.

## Accessing the GUI

1. Start the application normally
2. Open a web browser and navigate to: `http://localhost:8000/aruco`
3. You should see the feeder camera feed on the left and tag management panels on the right

## How It Works

### Components

**Feeder Camera Feed (Left Side)**
- Displays the live video from the feeder camera
- Shows detected objects and ArUco tags
- Updates automatically approximately every 500ms

**Unassigned Tags (Top Right)**
- Shows all detected ArUco tags that haven't been assigned to any region yet
- Purple gradient tags are unassigned tags

**Assignments Panel (Middle Right)**
- Shows all categories with their assigned tags
- Each category displays role slots that can contain tags
- Empty slots have a dashed border
- Filled slots show the tag ID and role name

### Workflow

#### Initial Setup (First Time)

1. **Place tags on your sorting regions**:
   - Place center tag + 2 radius tags in each c-channel region
   - Place 4 corner tags on each carousel platform

2. **Capture tags with camera**:
   - Run the vision system to detect all placed tags
   - Tags are automatically added to the "Unassigned Tags" section
   - Refresh the page if new tags don't appear (checks every 5 seconds)

3. **Assign tags to regions**:
   - Click on an unassigned tag (it will highlight with white border)
   - Click on the empty role slot where you want to assign it
   - The tag moves to that category and the page updates automatically

#### Reassigning Tags

- To move a tag from one role to another:
  - Click the tag in its current role (this unassigns it)
  - It returns to "Unassigned Tags"
  - Click it again and click a new role slot

#### Viewing Configuration

- **See current assignments**: All categories show their filled roles
- **Reset if needed**: Unassign all tags to start fresh
- **Export/Backup**: The configuration is automatically saved to `aruco_config.json`

## Configuration File

The ArUco configuration is stored in `aruco_config.json` with this structure:

```json
{
  "unassigned": [20, 31, 7],
  "second_c_channel": {
    "tags": {
      "center": 20,
      "radius1": 31,
      "radius2": 7
    }
  },
  "third_c_channel": {
    "tags": {
      "center": null,
      "radius1": null,
      "radius2": null
    }
  },
  "carousel_platform_1": {
    "tags": {
      "corner1": null,
      "corner2": null,
      "corner3": null,
      "corner4": null
    }
  },
  "carousel_platform_2": {
    "tags": {
      "corner1": null,
      "corner2": null,
      "corner3": null,
      "corner4": null
    }
  },
  "carousel_platform_3": {
    "tags": {
      "corner1": null,
      "corner2": null,
      "corner3": null,
      "corner4": null
    }
  },
  "carousel_platform_4": {
    "tags": {
      "corner1": null,
      "corner2": null,
      "corner3": null,
      "corner4": null
    }
  }
}
```

- `unassigned`: List of tag IDs that haven't been assigned
- `[category]/tags/[role]`: The tag ID assigned to that role, or `null` if empty

## API Endpoints

The GUI uses these REST API endpoints (for reference):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/aruco/config` | Get full configuration |
| GET | `/api/aruco/categories` | Get all categories with assignments |
| GET | `/api/aruco/tags/unassigned` | Get list of unassigned tag IDs |
| GET | `/api/aruco/tags/all` | Get all known tags |
| POST | `/api/aruco/assign?tag_id=X&category=Y&role=Z` | Assign a tag |
| POST | `/api/aruco/unassign?tag_id=X` | Unassign a tag |
| GET | `/api/aruco/category/{name}` | Get specific category details |

## Integration with Vision System

Once tags are assigned via the GUI:

1. **Python Application**: 
   - Loads `aruco_config.json` at startup
   - Updates `irl/config.py` to use GUI-assigned tags instead of hardcoded values
   - Vision system uses loaded configuration for calibration

2. **Geometric Calibration**:
   - C-channel regions: Uses center tag + 2 radius tags to define circle geometry
   - Carousel platforms: Uses 4 corner tags to define platform boundaries

3. **Object Routing**:
   - Detected objects routed to correct rotor based on their ArUco-defined region
   - No code edits needed to recalibrate after tag reassignment

## Troubleshooting

### Camera feed shows "Camera not available"
- Ensure the feeder camera endpoint `/video_feed/feeder` is configured
- Check that the camera capture is running

### Tags don't appear in GUI
- Ensure ArUco detection is running (should print detected tag IDs)
- Try refreshing the page (checks for new tags every 5 seconds)
- Manual override: Edit `aruco_config.json` and add tag IDs to "unassigned" list

### Changes not persisting after restart
- Verify `aruco_config.json` exists in the client directory
- Check file permissions (should be readable/writable)
- Verify JSON syntax if manually editing

### Categories missing slots
- Supported categories:
  - `second_c_channel`: 3 roles (center, radius1, radius2)
  - `third_c_channel`: 3 roles (center, radius1, radius2)
  - `carousel_platform_1` through `4`: 4 roles each (corner1-4)
- Adding new categories requires updating `aruco_config.json` manually

## Best Practices

1. **Label your physical tags**: Write tag IDs on the physical tags for easy reference
2. **Document your setup**: Take a photo of your tag placements for records
3. **Test after assignment**: Run a sorting cycle to verify calibration is correct
4. **Backup configuration**: Copy `aruco_config.json` when you have a working setup

## Next Steps

- Auto-update vision system to load tags from JSON
- Add visual overlay showing detected tags in real-time on camera feed
- Add tag search functionality for large deployments
