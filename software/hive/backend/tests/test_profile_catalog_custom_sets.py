from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.errors import APIError
from app.services.profile_catalog import CUSTOM_SET_ANY_COLOR_ID, ProfileCatalogService


def _catalog_service_for_custom_sets() -> ProfileCatalogService:
    service = ProfileCatalogService.__new__(ProfileCatalogService)
    service._parts_data = SimpleNamespace(
        parts={
            "2780": {
                "name": "Pin with Friction Ridges Lengthwise",
                "external_ids": {"BrickLink": ["2780"]},
                "part_img_url": "https://img.example/2780.png",
            },
            "32054": {
                "name": "Axle 2 Notched",
                "external_ids": {"BrickLink": ["32054"]},
                "part_img_url": "https://img.example/32054.png",
            },
        },
        colors={
            5: {"name": "Red", "rgb": "C91A09", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [5]}}},
            7: {"name": "Blue", "rgb": "0055BF", "is_trans": False, "external_ids": {"BrickLink": {"ext_ids": [7]}}},
        },
        rb_to_bl_color={5: 5},
    )
    return service


def _empty_catalog_service() -> ProfileCatalogService:
    service = ProfileCatalogService.__new__(ProfileCatalogService)
    service._parts_data = SimpleNamespace(
        parts={},
        colors={},
        rb_to_bl_color={},
    )
    return service


def test_custom_set_rules_compile_into_runtime_inventory_with_any_color() -> None:
    service = _catalog_service_for_custom_sets()

    set_mappings, set_inventories = service._resolve_set_rule_data(
        [
            {
                "id": "custom-rule-1",
                "rule_type": "set",
                "set_source": "custom",
                "name": "Customer Order",
                "set_num": "custom:customer-order",
                "custom_parts": [
                    {"part_num": "2780", "quantity": 20, "color_id": CUSTOM_SET_ANY_COLOR_ID},
                    {"part_num": "32054", "quantity": 10, "color_id": 5},
                ],
                "set_meta": {"name": "Customer Order"},
            }
        ]
    )

    assert set_mappings["custom-rule-1"] == {
        "any_color-2780": "custom-rule-1",
        "5-32054": "custom-rule-1",
    }
    inventory = set_inventories["custom-rule-1"]
    assert inventory["set_source"] == "custom"
    assert inventory["set_num"] == "custom:customer-order"
    assert inventory["num_parts"] == 30
    assert inventory["parts"][0]["color_id"] == CUSTOM_SET_ANY_COLOR_ID
    assert inventory["parts"][0]["color_name"] == "Any color"
    assert inventory["parts"][1]["part_name"] == "Axle 2 Notched"
    assert inventory["parts"][1]["color_name"] == "Red"


def test_custom_set_rules_reject_unknown_parts() -> None:
    service = _catalog_service_for_custom_sets()

    with pytest.raises(APIError, match="Unknown part"):
        service._resolve_set_rule_data(
            [
                {
                    "id": "custom-rule-1",
                    "rule_type": "set",
                    "set_source": "custom",
                    "name": "Broken Order",
                    "custom_parts": [{"part_num": "does-not-exist", "quantity": 1, "color_id": 5}],
                }
            ]
        )


def test_import_bricklink_csv_maps_bricklink_ids_and_merges_quantities() -> None:
    service = _catalog_service_for_custom_sets()

    result = service.import_bricklink_csv(
        "BLItemNo,BLColorId,Qty,PartName,ColorName\n"
        "2780,5,2,Pin,Red\n"
        "2780,5,3,Pin,Red\n"
        "32054,7,4,Axle,Blue\n",
        filename="Spider mech v4 CVS.csv",
    )

    assert result["suggested_name"] == "Spider mech v4 CVS"
    assert result["imported_rows"] == 3
    assert result["imported_unique_parts"] == 2
    assert result["warning_count"] == 0
    assert result["parts"] == [
        {
            "part_num": "32054",
            "part_name": "Axle 2 Notched",
            "img_url": "https://img.example/32054.png",
            "color_id": 7,
            "color_name": "Blue",
            "part_source": "rebrickable",
            "quantity": 4,
        },
        {
            "part_num": "2780",
            "part_name": "Pin with Friction Ridges Lengthwise",
            "img_url": "https://img.example/2780.png",
            "color_id": 5,
            "color_name": "Red",
            "part_source": "rebrickable",
            "quantity": 5,
        },
    ]


def test_import_bricklink_csv_reports_unknown_rows_but_keeps_valid_ones() -> None:
    service = _catalog_service_for_custom_sets()

    result = service.import_bricklink_csv(
        "BLItemNo,BLColorId,Qty,PartName,ColorName\n"
        "2780,5,2,Pin,Red\n"
        "99999,5,1,Unknown,Red\n"
        "32054,999,4,Axle,Unknown\n",
        filename="test.csv",
    )

    assert result["imported_rows"] == 3
    assert result["imported_unique_parts"] == 3
    assert result["warning_count"] == 2
    assert "imported BrickLink item '99999' without local part mapping" in result["warnings"][0]


def test_import_bricklink_csv_works_without_synced_catalog_by_using_raw_bricklink_ids() -> None:
    service = _empty_catalog_service()

    result = service.import_bricklink_csv(
        "BLItemNo,BLColorId,Qty,PartName,ColorName\n"
        "11477,69,1,Slope,Dark Tan\n"
        "3004,11,2,Brick 1 x 2,Black\n",
        filename="Spider mech v4 CVS.csv",
    )

    assert result["imported_rows"] == 2
    assert result["imported_unique_parts"] == 2
    assert result["warning_count"] == 4
    assert result["parts"][0]["part_source"] == "bricklink"
    assert result["parts"][0]["part_num"] == "3004"
    assert result["parts"][0]["color_id"] == 11


def test_custom_set_rules_compile_bricklink_sourced_parts_without_catalog() -> None:
    service = _empty_catalog_service()

    set_mappings, set_inventories = service._resolve_set_rule_data(
        [
            {
                "id": "custom-rule-1",
                "rule_type": "set",
                "set_source": "custom",
                "name": "BrickLink Order",
                "custom_parts": [
                    {
                        "part_num": "11477",
                        "part_source": "bricklink",
                        "quantity": 2,
                        "color_id": 69,
                        "color_name": "Dark Tan",
                    }
                ],
            }
        ]
    )

    assert set_mappings["custom-rule-1"] == {"69-11477": "custom-rule-1"}
    assert set_inventories["custom-rule-1"]["parts"][0]["part_num"] == "11477"
    assert set_inventories["custom-rule-1"]["parts"][0]["color_id"] == 69
    assert set_inventories["custom-rule-1"]["parts"][0]["rb_part_num"] is None
