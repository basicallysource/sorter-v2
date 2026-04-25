"""
Lightweight Onshape REST API client using API key + secret (HTTP Basic Auth).

Credentials are loaded from ~/.config/onshape/credentials.json:
  {
    "cad": {
      "url": "https://cad.onshape.com/",
      "accessKey": "...",
      "secretKey": "..."
    }
  }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

CREDENTIALS_PATH = Path.home() / ".config" / "onshape" / "credentials.json"
API_VERSION = "v6"


@dataclass
class Element:
    id: str
    name: str
    element_type: str  # "PARTSTUDIO", "ASSEMBLY", "BILLOFMATERIALS", etc.


@dataclass
class Part:
    part_id: str
    name: str
    element_id: str
    body_type: str = "solid"   # "solid" | "composite" | "sheet" | etc.
    is_hidden: bool = False
    microversion_id: str = ""  # Onshape microversion at which this part last changed


class OnshapeClient:
    """Simple Onshape API client backed by requests + API key auth."""

    def __init__(self, base_url: str, access_key: str, secret_key: str):
        self._base = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.auth = (access_key, secret_key)
        self._session.headers["Accept"] = "application/json"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, **params: Any) -> Any:
        url = f"{self._base}/api/{API_VERSION}{path}"
        resp = self._session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _get_raw(self, path: str, **params: Any) -> bytes:
        """Return raw response bytes (for binary exports like STL).

        Onshape export endpoints redirect to a regional subdomain (e.g.
        cad-usw2.onshape.com). requests strips Basic Auth on cross-origin
        redirects, so we follow redirects manually to preserve credentials.
        """
        url = f"{self._base}/api/{API_VERSION}{path}"
        for _ in range(10):
            resp = self._session.get(
                url, params=params, headers={"Accept": "*/*"}, allow_redirects=False
            )
            params = {}  # only send query params on the first request
            if resp.is_redirect:
                url = resp.headers["Location"]
                continue
            resp.raise_for_status()
            return resp.content
        raise RuntimeError("Too many redirects fetching binary export")

    # ------------------------------------------------------------------
    # Document / element queries
    # ------------------------------------------------------------------

    def get_elements(self, did: str, wid: str) -> list[Element]:
        """Return all elements (tabs) in a document workspace."""
        raw = self._get(f"/documents/d/{did}/w/{wid}/elements")
        return [
            Element(
                id=e["id"],
                name=e["name"],
                element_type=e["elementType"],
            )
            for e in raw
        ]

    def get_part_studios(self, did: str, wid: str) -> list[Element]:
        """Return only the Part Studio elements in a document workspace."""
        return [e for e in self.get_elements(did, wid) if e.element_type == "PARTSTUDIO"]

    # ------------------------------------------------------------------
    # Part queries
    # ------------------------------------------------------------------

    def get_parts_in_element(self, did: str, wid: str, eid: str) -> list[Part]:
        """Return all parts defined in a single Part Studio element."""
        raw = self._get(f"/parts/d/{did}/w/{wid}/e/{eid}")
        return [
            Part(
                part_id=p["partId"],
                name=p["name"],
                element_id=eid,
                body_type=p.get("bodyType", "solid"),
                is_hidden=p.get("isHidden", False),
                microversion_id=p.get("microversionId", ""),
            )
            for p in raw
        ]

    def get_parts_in_document(self, did: str, wid: str) -> list[Part]:
        """Return all parts across every Part Studio in the workspace, in one API call."""
        raw = self._get(f"/parts/d/{did}/w/{wid}")
        return [
            Part(
                part_id=p["partId"],
                name=p["name"],
                element_id=p.get("elementId", ""),
                body_type=p.get("bodyType", "solid"),
                is_hidden=p.get("isHidden", False),
                microversion_id=p.get("microversionId", ""),
            )
            for p in raw
        ]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def get_bom_quantities(self, did: str, wid: str, eid: str) -> dict[tuple[str, str], int]:
        """
        Fetch the flat BOM for an assembly element and return a mapping of
        (element_id, part_id) -> print quantity.

        Returns an empty dict if the element is not an assembly or has no BOM.
        """
        try:
            raw = self._get(
                f"/assemblies/d/{did}/w/{wid}/e/{eid}/bom",
                indented=False,
                multiLevel=False,
            )
        except Exception:
            return {}

        headers = raw.get("headers", [])
        qty_id = next((h["id"] for h in headers if h["name"] == "Quantity"), None)
        if not qty_id:
            return {}

        quantities: dict[tuple[str, str], int] = {}
        for row in raw.get("rows", []):
            src = row.get("itemSource", {})
            element_id = src.get("elementId", "")
            part_id = src.get("partId", "")
            qty = row.get("headerIdToValue", {}).get(qty_id, 1) or 1
            if element_id and part_id:
                quantities[(element_id, part_id)] = int(qty)

        return quantities

    def export_part_stl(
        self,
        did: str,
        wid: str,
        eid: str,
        part_id: str,
        *,
        units: str = "millimeter",
        mode: str = "binary",
    ) -> bytes:
        """Return the raw STL bytes for a single part."""
        return self._get_raw(
            f"/parts/d/{did}/w/{wid}/e/{eid}/partid/{part_id}/stl",
            mode=mode,
            units=units,
            grouping=True,
        )


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def client_from_credentials(credentials_path: Path = CREDENTIALS_PATH) -> tuple[OnshapeClient, dict]:
    """
    Load credentials from disk and return a ready-to-use OnshapeClient.
    Also returns the raw credentials dict for callers that need the URL, etc.
    """
    if not credentials_path.exists():
        raise FileNotFoundError(f"Onshape credentials not found at {credentials_path}")
    creds = json.loads(credentials_path.read_text())["cad"]
    return OnshapeClient(creds["url"], creds["accessKey"], creds["secretKey"]), creds
