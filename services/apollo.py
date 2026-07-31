import os
import httpx
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
APOLLO_BASE    = "https://api.apollo.io/api/v1"

HEADERS = {
    "Cache-Control": "no-cache",
    "Content-Type":  "application/json",
    "accept":        "application/json",
    "x-api-key":     APOLLO_API_KEY,
}


class ApolloService:

    # ── People Search (requires paid plan) ────────────────────────────────────
    def search_people(
        self,
        titles:          list[str],
        locations:       list[str] = None,
        seniorities:     list[str] = None,
        keywords:        str       = None,
        employees_range: str       = None,
        per_page:        int       = 25,
        page:            int       = 1,
    ) -> tuple[list[dict], dict]:
        """
        Search Apollo for people by title/location/industry.
        Requires paid plan (Basic $49/mo).
        Parameters go as URL query strings.
        """
        params = []
        for title in (titles or []):
            params.append(("person_titles[]", title))
        for loc in (locations or ["California, US"]):
            params.append(("person_locations[]", loc))
        for sen in (seniorities or ["owner", "founder", "c_suite", "vp", "director"]):
            params.append(("person_seniorities[]", sen))
        if employees_range:
            params.append(("organization_num_employees_ranges[]", employees_range))
        if keywords:
            params.append(("q_keywords", keywords))
        params.append(("per_page", str(min(per_page, 100))))
        params.append(("page",     str(page)))

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{APOLLO_BASE}/mixed_people/api_search",
                params=params, headers=HEADERS,
            )

        if resp.status_code == 403:
            raise Exception(f"Apollo search requires paid plan: {resp.text}")
        if resp.status_code == 422:
            raise Exception(f"Apollo 422: {resp.text}")
        if resp.status_code == 429:
            raise Exception("Apollo 429: Rate limit exceeded.")

        resp.raise_for_status()
        data = resp.json()
        return [self._normalize_person(p) for p in data.get("people", [])], data.get("pagination", {})

    # ── Enrich single person (FREE) ───────────────────────────────────────────
    def enrich_person(
        self,
        email:        str = None,
        first_name:   str = None,
        last_name:    str = None,
        domain:       str = None,
        linkedin_url: str = None,
        apollo_id:    str = None,
        reveal_email: bool = True,
    ) -> dict | None:
        """
        Enrich one person to get their full profile.
        - reveal_email=True  → also reveals the verified email (costs 1 credit).
          Use for NEW prospects where we don't have an email yet.
        - reveal_email=False → "economic" mode: only title/company/industry/region.
          Use for contacts we ALREADY have an email for (Kajabi). Cheap/free.
        Best match: apollo_id (exact) > email > linkedin_url > name+domain.
        """
        params = [
            ("reveal_personal_emails", "true" if reveal_email else "false"),
            ("reveal_phone_number",    "false"),
        ]
        if apollo_id:    params.append(("id",           apollo_id))
        if email:        params.append(("email",        email))
        if first_name:   params.append(("first_name",   first_name))
        if last_name and last_name.lower() != "none":
            params.append(("last_name", last_name))
        if domain:       params.append(("domain",       domain))
        if linkedin_url: params.append(("linkedin_url", linkedin_url))

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{APOLLO_BASE}/people/match",
                params=params, headers=HEADERS,
            )

        if resp.status_code == 429:
            raise Exception("Apollo 429: Rate limit on enrichment.")

        resp.raise_for_status()
        body   = resp.json()
        person = body.get("person")
        if not person:
            return None

        # The match endpoint returns the org as a separate top-level object
        # sometimes; merge it into the person so _normalize can read it.
        if not person.get("organization") and body.get("organization"):
            person["organization"] = body["organization"]

        return self._normalize_person(person)

    # ── Bulk enrich up to 10 people (FREE) ────────────────────────────────────
    def bulk_enrich(self, contacts: list[dict]) -> list[dict]:
        """
        Enrich up to 10 contacts in one call.
        FREE on all plans.
        Each contact dict should have: first_name, last_name, domain (or email).
        Great for enriching Kajabi/ClickFunnels contacts after import.
        """
        # Apollo bulk_match accepts max 10 per call
        batch = contacts[:10]

        details = []
        for c in batch:
            detail = {}
            if c.get("first_name"): detail["first_name"] = c["first_name"]
            if c.get("last_name"):  detail["last_name"]  = c["last_name"]
            if c.get("email"):      detail["email"]      = c["email"]
            if c.get("domain"):     detail["domain"]     = c["domain"]
            if detail:
                details.append(detail)

        if not details:
            return []

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{APOLLO_BASE}/people/bulk_match",
                params  = [("reveal_personal_emails", "true"), ("reveal_phone_number", "false")],
                json    = {"details": details},
                headers = HEADERS,
            )

        if resp.status_code == 429:
            raise Exception("Apollo 429: Rate limit on bulk enrichment.")

        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        return [self._normalize_person(m) for m in matches if m]

    # ── Enrich organization (FREE) ────────────────────────────────────────────
    def enrich_organization(self, domain: str) -> dict | None:
        """
        Get company data from Apollo by domain.
        FREE — useful to enrich companies from Kajabi contacts.
        e.g. enrich_organization("forddealer.com")
        """
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{APOLLO_BASE}/organizations/enrich",
                params  = [("domain", domain)],
                headers = HEADERS,
            )

        resp.raise_for_status()
        org = resp.json().get("organization")
        if not org:
            return None

        return {
            "company":          org.get("name"),
            "industry":         org.get("industry"),
            "employees":        org.get("estimated_num_employees"),
            "website":          org.get("website_url"),
            "linkedin_url":     org.get("linkedin_url"),
            "founded_year":     org.get("founded_year"),
        }

    # ── Normalize ──────────────────────────────────────────────────────────────
    def _normalize_person(self, raw: dict) -> dict:
        # Organization can arrive as a nested object, or be missing (only organization_id).
        # In the latter case, pull company info from the current employment_history entry.
        org = raw.get("organization") or {}

        # Current job from employment history (where current == True)
        current_job = {}
        for job in (raw.get("employment_history") or []):
            if job.get("current"):
                current_job = job
                break

        # Company name: org object → current job → account name
        company = (
            org.get("name")
            or current_job.get("organization_name")
            or raw.get("organization_name")
        )

        website = org.get("website_url") or ""
        domain  = (
            website.replace("https://", "").replace("http://", "")
            .replace("www.", "").split("/")[0].strip()
        ) or None

        # Corporate phone (free tier). Apollo puts it in several possible places.
        corp_phone = None
        for candidate in [
            raw.get("corporate_phone"),
            org.get("phone"),
            org.get("sanitized_phone"),
            (org.get("primary_phone") or {}).get("number") if isinstance(org.get("primary_phone"), dict) else None,
        ]:
            if candidate:
                corp_phone = str(candidate).lstrip("'").strip()
                break

        num_emp = org.get("estimated_num_employees")
        revenue = (
            org.get("annual_revenue")
            or org.get("organization_revenue")
            or org.get("organization_revenue_printed")
        )

        # Industry: org object, else the raw industry field
        industry = org.get("industry") or raw.get("industry")

        # City/State can be on the person directly
        city  = raw.get("city")
        state = raw.get("state")

        return {
            "first_name":      raw.get("first_name"),
            "last_name":       raw.get("last_name"),
            "email":           raw.get("email"),
            "title":           raw.get("title") or current_job.get("title"),
            "company":         company,
            "industry":        industry,
            "employees":       num_emp,
            "num_employees":   str(num_emp) if num_emp else None,
            "annual_revenue":  str(revenue) if revenue else None,
            "region":          city or state,
            "city":            city,
            "state":           state,
            "linkedin_url":    raw.get("linkedin_url"),
            "phone_corporate": corp_phone,
            "website":         website or None,
            "apollo_id":       raw.get("id"),
            "domain":          domain,
            "source":          "apollo",
        }


apollo_service = ApolloService()
