"""
ArUco tag configuration manager.
Handles loading, saving, and assigning ArUco tags to different regions.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class TagAssignment:
    tag_id: int
    category: str
    role: str  # e.g., "center", "radius1", "radius2", "corner1", etc.


class ArucoConfigManager:
    """Manages ArUco tag configuration and persistence."""
    
    def __init__(self, config_path: str = "aruco_config.json"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = self._load_or_create_config()
        self._ensure_schema()
        self._sync_to_storage()

    def _ensure_schema(self) -> None:
        categories = self.config.setdefault("categories", {})

        for channel in ["second_c_channel", "third_c_channel"]:
            category = categories.setdefault(channel, {})
            category.setdefault("description", f"{channel} calibration")
            category.setdefault("radius_multiplier", 1.0)
            tags = category.setdefault("tags", {})
            tags.setdefault("center", None)
            tags.setdefault("output_guide", None)
            tags.setdefault("radius1", None)
            tags.setdefault("radius2", None)
            tags.setdefault("radius3", None)
            tags.setdefault("radius4", None)
            tags.setdefault("radius5", None)
    
    def _load_or_create_config(self) -> Dict[str, Any]:
        """Load config from file or create default if it doesn't exist."""
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                return json.load(f)
        
        # Create default config
        default_config = {
            "version": "1.0",
            "categories": {
                "unassigned": {
                    "description": "Tags that haven't been assigned yet",
                    "tags": []
                },
                "second_c_channel": {
                    "description": "Second C-channel rotor circular region",
                    "radius_multiplier": 1.0,
                    "tags": {
                        "center": None,
                        "output_guide": None,
                        "radius1": None,
                        "radius2": None,
                        "radius3": None,
                        "radius4": None,
                        "radius5": None,
                    }
                },
                "third_c_channel": {
                    "description": "Third C-channel rotor circular region",
                    "radius_multiplier": 1.0,
                    "tags": {
                        "center": None,
                        "output_guide": None,
                        "radius1": None,
                        "radius2": None,
                        "radius3": None,
                        "radius4": None,
                        "radius5": None,
                    }
                },
                "carousel_platform_1": {
                    "description": "Carousel platform 1 corners",
                    "tags": {"corner1": None, "corner2": None, "corner3": None, "corner4": None}
                },
                "carousel_platform_2": {
                    "description": "Carousel platform 2 corners",
                    "tags": {"corner1": None, "corner2": None, "corner3": None, "corner4": None}
                },
                "carousel_platform_3": {
                    "description": "Carousel platform 3 corners",
                    "tags": {"corner1": None, "corner2": None, "corner3": None, "corner4": None}
                },
                "carousel_platform_4": {
                    "description": "Carousel platform 4 corners",
                    "tags": {"corner1": None, "corner2": None, "corner3": None, "corner4": None}
                },
            }
        }
        
        # Save to file
        with open(self.config_path, 'w') as f:
            json.dump(default_config, f, indent=2)
        
        return default_config
    
    def _sync_to_storage(self):
        """Write current config to file."""
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get_all_tags(self) -> List[int]:
        """Get all known tag IDs across all categories."""
        tags = set()
        for category_name, category_data in self.config["categories"].items():
            if category_name == "unassigned":
                tags.update(category_data["tags"])
            else:
                for tag_id in category_data["tags"].values():
                    if tag_id is not None:
                        tags.add(tag_id)
        return sorted(list(tags))
    
    def get_unassigned_tags(self) -> List[int]:
        """Get list of unassigned tag IDs."""
        return self.config["categories"]["unassigned"]["tags"]
    
    def get_category(self, category_name: str) -> Dict[str, Any]:
        """Get a specific category's configuration."""
        return self.config["categories"].get(category_name)
    
    def assign_tag(self, tag_id: int, category: str, role: str) -> bool:
        """
        Assign a tag to a category and role.
        Returns True if successful, False otherwise.
        """
        # Remove from unassigned if present
        if tag_id in self.config["categories"]["unassigned"]["tags"]:
            self.config["categories"]["unassigned"]["tags"].remove(tag_id)
        
        # Remove from other assignments
        for cat_name, cat_data in self.config["categories"].items():
            if cat_name == "unassigned":
                continue
            if isinstance(cat_data.get("tags"), dict):
                for role_name, assigned_tag in cat_data["tags"].items():
                    if assigned_tag == tag_id:
                        cat_data["tags"][role_name] = None
        
        # Assign to new location
        if category in self.config["categories"]:
            cat_data = self.config["categories"][category]
            if "tags" in cat_data:
                if isinstance(cat_data["tags"], dict):
                    if role in cat_data["tags"]:
                        cat_data["tags"][role] = tag_id
                    else:
                        return False
                elif isinstance(cat_data["tags"], list):
                    cat_data["tags"].append(tag_id)
            else:
                return False
        else:
            return False
        
        self._sync_to_storage()
        return True
    
    def unassign_tag(self, tag_id: int) -> bool:
        """Move a tag back to unassigned."""
        # Remove from all assignments
        for cat_name, cat_data in self.config["categories"].items():
            if cat_name == "unassigned":
                continue
            if isinstance(cat_data.get("tags"), dict):
                for role_name, assigned_tag in list(cat_data["tags"].items()):
                    if assigned_tag == tag_id:
                        cat_data["tags"][role_name] = None
        
        # Add to unassigned
        if tag_id not in self.config["categories"]["unassigned"]["tags"]:
            self.config["categories"]["unassigned"]["tags"].append(tag_id)
        
        self._sync_to_storage()
        return True
    
    def get_config_dict(self) -> Dict[str, Any]:
        """Get full configuration as dictionary."""
        return self.config

    def set_radius_multiplier(self, category: str, value: float) -> bool:
        """Set radius multiplier for a c-channel category."""
        if category not in self.config["categories"]:
            return False
        if category not in ["second_c_channel", "third_c_channel"]:
            return False
        if value <= 0:
            return False
        self.config["categories"][category]["radius_multiplier"] = float(value)
        self._sync_to_storage()
        return True
    
    def populate_detected_tags(self, detected_tag_ids: List[int]) -> bool:
        """
        Called when new tags are detected to populate unassigned list.
        Only adds tags that aren't already assigned anywhere.
        """
        existing_tags = set(self.get_all_tags())
        new_tags = [tag_id for tag_id in detected_tag_ids if tag_id not in existing_tags]
        
        if new_tags:
            self.config["categories"]["unassigned"]["tags"].extend(new_tags)
            self.config["categories"]["unassigned"]["tags"] = sorted(
                list(set(self.config["categories"]["unassigned"]["tags"]))
            )
            self._sync_to_storage()
            return True
        return False
