import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MAPS_BASE      = "https://maps.googleapis.com/maps/api/place"
SEARCH_BASE    = "https://www.googleapis.com/customsearch/v1"
SEARCH_CX      = os.getenv("GOOGLE_SEARCH_CX")  # Custom Search Engine ID


class GoogleService:

    # ── Google Maps / Places ────────────────────────────────────────────────
    def search_dealerships(self, region: str, brand: str = None) -> list[dict]:
        """
        Search Google Maps for automotive dealerships in a region.
        Returns company-level data (no direct contact — used to enrich Apollo results).
        """
        query = f"{brand or 'automotive'} dealership {region}"

        with httpx.Client(timeout=20) as client:
            resp = client.get(
                f"{MAPS_BASE}/textsearch/json",
                params={
                    "query":  query,
                    "key":    GOOGLE_API_KEY,
                    "type":   "car_dealer",
                }
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results", [])
        return [self._normalize_place(r) for r in results]

    def _normalize_place(self, raw: dict) -> dict:
        return {
            "company":  raw.get("name"),
            "address":  raw.get("formatted_address"),
            "region":   self._extract_region(raw.get("formatted_address", "")),
            "source":   "google_maps",
        }

    def _extract_region(self, address: str) -> str:
        """Extract state from address string"""
        parts = address.split(",")
        return parts[-2].strip() if len(parts) >= 2 else address

    # ── Google Custom Search ────────────────────────────────────────────────
    def search_profiles(self, title: str, company: str = None, region: str = None) -> list[dict]:
        """
        Search Google for public profiles by title and industry.
        Used as fallback when Apollo doesn't have the contact.
        """
        query_parts = [f'"{title}"', "automotive"]
        if company: query_parts.append(f'"{company}"')
        if region:  query_parts.append(region)
        query_parts.append("site:linkedin.com")

        query = " ".join(query_parts)

        with httpx.Client(timeout=20) as client:
            resp = client.get(
                SEARCH_BASE,
                params={
                    "key": GOOGLE_API_KEY,
                    "cx":  SEARCH_CX,
                    "q":   query,
                    "num": 10,
                }
            )
            resp.raise_for_status()
            data = resp.json()

        items = data.get("items", [])
        return [self._normalize_search(i, title) for i in items]

    def _normalize_search(self, raw: dict, title: str) -> dict:
        """
        Extract name from Google Search result title.
        LinkedIn result titles look like: "John Smith - VP Operations - Ford | LinkedIn"
        """
        parts = raw.get("title", "").split(" - ")
        name_parts = parts[0].split(" ") if parts else ["", ""]

        return {
            "first_name": name_parts[0] if name_parts else None,
            "last_name":  " ".join(name_parts[1:]) if len(name_parts) > 1 else None,
            "title":      title,
            "profile_url":raw.get("link"),
            "source":     "google_search",
            # No email — needs Apollo confirmation
            "email":      None,
        }


google_service = GoogleService()
