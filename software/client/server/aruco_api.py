"""
ArUco tag configuration API endpoints.
Provides REST API for managing tag assignments via the web GUI.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# Global config manager instance (will be set by main server)
aruco_manager = None

router = APIRouter(prefix="/api/aruco", tags=["aruco"])


def set_aruco_manager(manager):
    """Set the global ArUco manager instance."""
    global aruco_manager
    aruco_manager = manager


@router.get("/config")
async def get_aruco_config() -> Dict[str, Any]:
    """Get current ArUco tag configuration."""
    if not aruco_manager:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return aruco_manager.get_config_dict()


@router.get("/categories")
async def get_categories() -> Dict[str, Any]:
    """Get all categories with their tags."""
    if not aruco_manager:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    
    categories = {}
    for cat_name, cat_data in aruco_manager.config["categories"].items():
        categories[cat_name] = {
            "description": cat_data.get("description", ""),
            "tags": cat_data.get("tags", [])
        }
    return categories


@router.get("/tags/unassigned")
async def get_unassigned_tags() -> List[int]:
    """Get list of unassigned tag IDs."""
    if not aruco_manager:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return aruco_manager.get_unassigned_tags()


@router.get("/tags/all")
async def get_all_tags() -> List[int]:
    """Get all detected tag IDs."""
    if not aruco_manager:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return aruco_manager.get_all_tags()


@router.post("/assign")
async def assign_tag(tag_id: int, category: str, role: str) -> Dict[str, Any]:
    """
    Assign a tag to a category and role.
    Example: POST /api/aruco/assign?tag_id=20&category=second_c_channel&role=center
    """
    if not aruco_manager:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    
    if not isinstance(tag_id, int) or tag_id < 0:
        raise HTTPException(status_code=400, detail="Invalid tag_id")
    
    if not category or not role:
        raise HTTPException(status_code=400, detail="category and role are required")
    
    success = aruco_manager.assign_tag(tag_id, category, role)
    if success:
        logger.info(f"Assigned tag {tag_id} to {category}/{role}")
        return {"success": True, "message": f"Tag {tag_id} assigned to {category}/{role}"}
    else:
        raise HTTPException(status_code=400, detail=f"Failed to assign tag {tag_id}")


@router.post("/unassign")
async def unassign_tag(tag_id: int) -> Dict[str, Any]:
    """
    Move a tag back to unassigned.
    Example: POST /api/aruco/unassign?tag_id=20
    """
    if not aruco_manager:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    
    if not isinstance(tag_id, int) or tag_id < 0:
        raise HTTPException(status_code=400, detail="Invalid tag_id")
    
    success = aruco_manager.unassign_tag(tag_id)
    if success:
        logger.info(f"Unassigned tag {tag_id}")
        return {"success": True, "message": f"Tag {tag_id} moved to unassigned"}
    else:
        raise HTTPException(status_code=400, detail=f"Failed to unassign tag {tag_id}")


@router.get("/category/{category_name}")
async def get_category(category_name: str) -> Dict[str, Any]:
    """Get a specific category's configuration."""
    if not aruco_manager:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    
    cat = aruco_manager.get_category(category_name)
    if not cat:
        raise HTTPException(status_code=404, detail=f"Category {category_name} not found")
    
    return {
        "name": category_name,
        "description": cat.get("description", ""),
        "tags": cat.get("tags", [])
    }
