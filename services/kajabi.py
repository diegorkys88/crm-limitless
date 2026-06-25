import os
import httpx
import time
from dotenv import load_dotenv

load_dotenv()

KAJABI_CLIENT_ID     = os.getenv("KAJABI_CLIENT_ID")
KAJABI_CLIENT_SECRET = os.getenv("KAJABI_CLIENT_SECRET")
KAJABI_SITE_ID        = os.getenv("KAJABI_SITE_ID")  # optional — auto-detected if not set

# Verified working URLs (confirmed via curl tests)
KAJABI_TOKEN_URL = "https://api.kajabi.com/v1/oauth/token"
KAJABI_API_BASE  = "https://api.kajabi.com/v1"


class KajabiService:
    """
    Handles OAuth2 client_credentials authentication and contact operations with Kajabi.
    Token is cached in memory and refreshed automatically when expired.
    """

    def __init__(self):
        self._token        = None
        self._token_expiry = 0
        self._site_id      = KAJABI_SITE_ID

    # ── OAuth2 ─────────────────────────────────────────────────────────────────
    def _get_token(self) -> str:
        """Get a valid access token — reuses cached token if not expired"""
        if self._token and time.time() < self._token_expiry:
            return self._token

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                KAJABI_TOKEN_URL,
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     KAJABI_CLIENT_ID,
                    "client_secret": KAJABI_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

        if resp.status_code != 200:
            raise Exception(f"Kajabi auth failed: {resp.status_code} — {resp.text}")

        data = resp.json()
        self._token        = data["access_token"]
        self._token_expiry  = time.time() + data.get("expires_in", 3600) - 60

        return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept":        "application/vnd.api+json",
            "Content-Type":  "application/vnd.api+json",
        }

    # ── Account info ───────────────────────────────────────────────────────────
    def get_me(self) -> dict:
        """GET /v1/me — verify token works and see permissions"""
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{KAJABI_API_BASE}/me", headers=self._headers())
        resp.raise_for_status()
        return resp.json().get("data", {})

    def get_site_id(self) -> str:
        """
        Auto-detect the site_id if not configured.
        Most accounts have a single site — we grab the first one.
        """
        if self._site_id:
            return self._site_id

        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{KAJABI_API_BASE}/sites", headers=self._headers())
        resp.raise_for_status()
        sites = resp.json().get("data", [])
        if sites:
            self._site_id = sites[0]["id"]
            return self._site_id
        return None

    # ── Contacts ───────────────────────────────────────────────────────────────
    def list_contacts(self, page: int = 1, page_size: int = 50) -> tuple[list[dict], dict]:
        """
        List contacts from Kajabi, paginated.
        Returns (contacts, meta) — meta includes 'total' count.
        Automatically includes site_id filter — required if account has multiple sites.
        """
        params = {
            "page[number]": page,
            "page[size]":   min(page_size, 100),
        }

        site_id = self.get_site_id()
        if site_id:
            params["filter[site_id]"] = site_id

        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{KAJABI_API_BASE}/contacts",
                params=params,
                headers=self._headers(),
            )

        if resp.status_code != 200:
            raise Exception(f"Kajabi list_contacts failed: {resp.status_code} — {resp.text}")

        data     = resp.json()
        contacts = [self._normalize_contact(c) for c in data.get("data", [])]
        meta     = data.get("meta", {})
        links    = data.get("links", {})

        return contacts, {**meta, "has_next": "next" in links}

    def list_all_contacts(self, max_pages: int = 100) -> list[dict]:
        """
        Fetch ALL contacts across all pages (page size 100 each).
        max_pages protects against runaway loops — 100 pages = up to 10,000 contacts.
        """
        all_contacts = []
        page = 1
        while page <= max_pages:
            contacts, meta = self.list_contacts(page=page, page_size=100)
            if not contacts:
                break
            all_contacts.extend(contacts)
            if not meta.get("has_next"):
                break
            page += 1
        return all_contacts

    def get_contact(self, contact_id: str) -> dict | None:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{KAJABI_API_BASE}/contacts/{contact_id}",
                headers=self._headers(),
            )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._normalize_contact(resp.json().get("data", {}))

    def _normalize_contact(self, raw: dict) -> dict:
        """
        Convert Kajabi JSON:API contact format to our CRM format.
        Verified format from real API response:
        {"id": "...", "attributes": {"name": "Pamela Martin", "email": "...", "phone_number": null, ...}}
        """
        attrs = raw.get("attributes", {})
        full_name = (attrs.get("name") or "").strip()
        name_parts = full_name.split(" ", 1) if full_name else ["", ""]

        return {
            "kajabi_id":  raw.get("id"),
            "first_name": name_parts[0] if name_parts else None,
            "last_name":  name_parts[1] if len(name_parts) > 1 else None,
            "email":      attrs.get("email"),
            "phone":      attrs.get("phone_number"),
            "company":    attrs.get("business_number"),
            "subscribed": "true" if attrs.get("subscribed") else "false",
            "source":     "kajabi",
        }

    # ── Tags ───────────────────────────────────────────────────────────────────
    def list_tags(self) -> list[dict]:
        """
        GET /v1/contact_tags — list all tags that exist in Kajabi.
        Tags must already exist here — the API can't create new ones.
        """
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{KAJABI_API_BASE}/contact_tags", headers=self._headers())
        resp.raise_for_status()
        tags = resp.json().get("data", [])
        return [{"id": t["id"], "name": t.get("attributes", {}).get("name")} for t in tags]

    def get_tag_id_by_name(self, tag_name: str) -> str | None:
        """Find a tag's ID by its name (case-insensitive match)"""
        tags = self.list_tags()
        for tag in tags:
            if (tag.get("name") or "").lower() == tag_name.lower():
                return tag["id"]
        return None

    def add_tag(self, contact_id: str, tag_id: str) -> bool:
        """Add an existing tag to a contact"""
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{KAJABI_API_BASE}/contacts/{contact_id}/relationships/tags",
                json={"data": [{"type": "contact_tags", "id": tag_id}]},
                headers=self._headers(),
            )
        return resp.status_code in (200, 201, 204)

    def remove_tag(self, contact_id: str, tag_id: str) -> bool:
        """Remove a tag from a contact"""
        with httpx.Client(timeout=15) as client:
            resp = client.request(
                "DELETE",
                f"{KAJABI_API_BASE}/contacts/{contact_id}/relationships/tags",
                json={"data": [{"type": "contact_tags", "id": tag_id}]},
                headers=self._headers(),
            )
        return resp.status_code in (200, 204)

    def tag_contact_by_name(self, contact_id: str, tag_name: str) -> bool:
        """
        Convenience method: find tag by name and add it to a contact.
        IMPORTANT: the tag must already exist in Kajabi (Settings > Tags) —
        create 'crm-contacted', 'crm-scheduled', 'crm-closed' there first.
        """
        tag_id = self.get_tag_id_by_name(tag_name)
        if not tag_id:
            print(f"[Kajabi] Tag '{tag_name}' not found in Kajabi — create it in the dashboard first")
            return False
        return self.add_tag(contact_id, tag_id)

    # ── Webhooks ───────────────────────────────────────────────────────────────
    def list_webhooks(self) -> list[dict]:
        """GET /v1/hooks — list all registered webhooks"""
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{KAJABI_API_BASE}/hooks", headers=self._headers())
        resp.raise_for_status()
        return resp.json().get("data", [])

    def create_webhook(self, target_url: str, event: str) -> dict:
        """
        Register a webhook in Kajabi.
        event examples: 'contact.tag_added', 'form.submitted', 'purchase.created'
        Check GET /v1/hooks/{event}_sample for exact payload formats.
        """
        site_id = self.get_site_id()
        if not site_id:
            raise Exception("Could not determine site_id — cannot create webhook")

        payload = {
            "data": {
                "type": "hooks",
                "attributes": {
                    "target_url": target_url,
                    "event":      event,
                },
                "relationships": {
                    "site": {
                        "data": {"type": "sites", "id": site_id}
                    }
                }
            }
        }

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{KAJABI_API_BASE}/hooks",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201):
            raise Exception(f"Kajabi webhook creation failed: {resp.status_code} — {resp.text}")

        return resp.json().get("data", {})

    def delete_webhook(self, hook_id: str) -> bool:
        with httpx.Client(timeout=15) as client:
            resp = client.delete(f"{KAJABI_API_BASE}/hooks/{hook_id}", headers=self._headers())
        return resp.status_code in (200, 204)


kajabi_service = KajabiService()
