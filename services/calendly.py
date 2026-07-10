import os
import httpx
from dotenv import load_dotenv

load_dotenv()

CALENDLY_API_KEY  = os.getenv("CALENDLY_API_KEY")
CALENDLY_BASE_URL = os.getenv("CALENDLY_BASE_URL", "https://calendly.com/your-link")
CALENDLY_API_BASE = "https://api.calendly.com"

HEADERS = {
    "Authorization": f"Bearer {CALENDLY_API_KEY}",
    "Content-Type":  "application/json",
}


class CalendlyService:

    def get_user(self) -> dict | None:
        """Get the current Calendly user — useful to verify the API key works"""
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{CALENDLY_API_BASE}/users/me", headers=HEADERS)
        resp.raise_for_status()
        return resp.json().get("resource")

    def get_event_types(self) -> list[dict]:
        """
        Get all event types for the user.
        Each event type has a scheduling_url we use as the Calendly link.
        """
        user = self.get_user()
        if not user:
            return []

        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{CALENDLY_API_BASE}/event_types",
                params  = {"user": user.get("uri")},
                headers = HEADERS,
            )
        resp.raise_for_status()
        return resp.json().get("collection", [])

    def build_link(self, contact_id: str, event_slug: str = None) -> str:
        """
        Build a unique Calendly link per contact.
        Includes contact_id as UTM so we know who booked when webhook fires.
        """
        base = event_slug or CALENDLY_BASE_URL
        return f"{base}?utm_content={contact_id}"

    def register_webhook(self, webhook_url: str, organization_uri: str) -> dict:
        """
        Register the CRM webhook URL in Calendly.
        Calendly will POST to this URL when someone books or cancels.
        Requires paid plan.
        """
        payload = {
            "url":          webhook_url,
            "events":       ["invitee.created", "invitee.canceled"],
            "organization": organization_uri,
            "scope":        "organization",
        }
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                f"{CALENDLY_API_BASE}/webhook_subscriptions",
                json    = payload,
                headers = HEADERS,
            )
        resp.raise_for_status()
        return resp.json()

    def get_event_details(self, event_uri: str) -> dict | None:
        """Get details of a specific scheduled event"""
        with httpx.Client(timeout=15) as client:
            resp = client.get(event_uri, headers=HEADERS)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("resource")


    def list_webhooks(self) -> list[dict]:
        """List all registered webhooks"""
        user = self.get_user()
        if not user:
            return []
        org = user.get("current_organization")
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                f"{CALENDLY_API_BASE}/webhook_subscriptions",
                params={"organization": org, "scope": "organization"},
                headers=HEADERS,
            )
        resp.raise_for_status()
        return resp.json().get("collection", [])

    def delete_webhook(self, webhook_uuid: str) -> bool:
        """Delete a webhook by UUID"""
        with httpx.Client(timeout=15) as client:
            resp = client.delete(
                f"{CALENDLY_API_BASE}/webhook_subscriptions/{webhook_uuid}",
                headers=HEADERS,
            )
        return resp.status_code in (200, 204)


calendly_service = CalendlyService()
