import os
from agents.base import BaseAgent

SYSTEM_PROMPT = """
You are the Prospector Agent for a CRM system serving a leadership coaching 
company in the U.S. automotive industry.

You receive a list of raw contacts found in Apollo (no emails yet).
Your job is to filter and select the BEST candidates before we spend credits enriching them.

IDEAL CLIENT PROFILE:
- Title: C-Level, VP, Director, General Manager, or Owner
- Industry: Automotive (dealerships, distributors, OEM, parts, repair)
- Company: Mid to large size preferred (20+ employees)
- Location: United States

IMPORTANT: We pay per email enrichment. Only approve contacts worth the credit.
Be selective — quality over quantity.

You MUST respond ONLY with valid JSON — no markdown, no backticks.
Format:
{
  "approved_ids": ["apollo_id_1", "apollo_id_2"],
  "rejected_ids": ["apollo_id_3"],
  "summary": "Brief summary of what was found and why you approved/rejected"
}
"""


class ProspectorAgent(BaseAgent):
    name = "prospector"

    def filter_contacts(self, raw_contacts: list[dict], db) -> list[dict]:
        """
        Claude reviews contacts WITHOUT emails and selects the best ones.
        Saves credits — we only enrich the approved ones.
        """
        if not raw_contacts:
            return []

        contact_list = "\n".join([
            f"- id:{c.get('apollo_id')} | {c.get('first_name')} {c.get('last_name')} | "
            f"{c.get('title', 'N/A')} | {c.get('company', 'N/A')} | "
            f"{c.get('region', 'N/A')} | industry:{c.get('industry', 'N/A')}"
            for c in raw_contacts
        ])

        prompt = f"""
Review these {len(raw_contacts)} contacts and select the best ones for leadership coaching outreach.
Remember: we pay per enrichment — only approve the most relevant profiles.

{contact_list}
"""
        raw    = self.run(prompt, SYSTEM_PROMPT, max_tokens=1000)
        result = self.parse_json(raw)

        if not result or not result.get("approved_ids"):
            print("[Prospector] Claude fallback: approving all contacts")
            return raw_contacts

        approved_ids = set(result.get("approved_ids", []))
        approved     = [c for c in raw_contacts if c.get("apollo_id") in approved_ids]

        print(f"[Prospector] Claude approved {len(approved)}/{len(raw_contacts)}")
        print(f"[Prospector] Summary: {result.get('summary')}")

        self.log(db, None, "filtered_contacts", contact_list, raw)
        return approved

    def search_and_import(
        self,
        titles:    list[str],
        region:    str,
        industry:  str,
        limit:     int,
        db,
        enrich:    bool = True,
    ) -> dict:
        """
        Full prospecting flow:
        1. Search Apollo FREE — names, titles, companies (no credits)
        2. Claude filters the best candidates
        3. If enrich=True: get emails via enrichment (1 credit each)
        4. Save approved contacts to DB
        """
        from services.apollo import apollo_service
        from database import Contact, SyncLog
        import uuid

        stats = {
            "found":    0,
            "approved": 0,
            "enriched": 0,
            "imported": 0,
            "skipped":  0,
            "summary":  ""
        }

        # ── Step 1: Search Apollo (FREE) ──────────────────────────────────────
        print(f"[Prospector] Searching Apollo — region: {region}, limit: {limit}")
        try:
            raw_contacts, pagination = apollo_service.search_people(
                titles    = titles,
                locations = [region],
                keywords  = industry,
                per_page  = min(limit, 100),
            )
            stats["found"] = len(raw_contacts)
            print(f"[Prospector] Apollo returned {len(raw_contacts)} contacts (no credits used)")
        except Exception as e:
            print(f"[Prospector] Apollo search error: {e}")
            return {**stats, "error": str(e)}

        if not raw_contacts:
            stats["summary"] = "No contacts found — try different titles or region"
            return stats

        # ── Step 2: Claude filters the best ones ──────────────────────────────
        if enrich:
            # Only filter when we're going to spend credits
            approved = self.filter_contacts(raw_contacts, db)
        else:
            # Preview mode — return all without filtering or saving
            approved = raw_contacts
            stats["approved"] = len(approved)
            stats["summary"]  = f"Preview mode (enrich=false): found {len(approved)} contacts. Set enrich=true to get emails and save to DB."
            return stats

        stats["approved"] = len(approved)

        if not approved:
            stats["summary"] = "Claude filtered out all contacts — try different search criteria"
            return stats

        # ── Step 3: Enrich to get emails (costs 1 credit per person) ──────────
        imported = 0
        skipped  = 0

        for contact_data in approved:
            apollo_id = contact_data.get("apollo_id")

            # Skip if already in DB by apollo_id
            if apollo_id:
                existing = db.query(Contact).filter(Contact.apollo_id == apollo_id).first()
                if existing:
                    skipped += 1
                    continue

            # Enrich to get email
            email = None
            try:
                enriched = apollo_service.enrich_person(
                    first_name   = contact_data.get("first_name"),
                    last_name    = contact_data.get("last_name"),
                    domain       = contact_data.get("domain"),
                    linkedin_url = contact_data.get("linkedin_url"),
                )
                if enriched:
                    email = enriched.get("email")
                    # Update contact_data with enriched info
                    contact_data.update({k: v for k, v in enriched.items() if v})
                stats["enriched"] += 1
            except Exception as e:
                print(f"[Prospector] Enrichment error: {e}")

            # Skip if no email found
            if not email:
                skipped += 1
                continue

            # Skip duplicate emails
            existing_email = db.query(Contact).filter(Contact.email == email).first()
            if existing_email:
                skipped += 1
                continue

            # Save to DB
            contact = Contact(
                id         = str(uuid.uuid4()),
                first_name = contact_data.get("first_name"),
                last_name  = contact_data.get("last_name"),
                email      = email,
                title      = contact_data.get("title"),
                company    = contact_data.get("company"),
                industry   = contact_data.get("industry") or industry,
                region     = contact_data.get("region") or region,
                source     = "apollo",
                apollo_id  = apollo_id,
                status     = "pending",
            )
            db.add(contact)

            db.add(SyncLog(
                id         = str(uuid.uuid4()),
                contact_id = contact.id,
                platform   = "apollo",
                action     = "contact_imported",
                tag        = "prospector",
                status     = "success",
            ))
            imported += 1

        db.commit()

        stats["imported"] = imported
        stats["skipped"]  = skipped
        stats["summary"]  = (
            f"Found {stats['found']}, approved {stats['approved']}, "
            f"enriched {stats['enriched']}, imported {imported}, skipped {skipped}"
        )

        return stats


prospector_agent = ProspectorAgent()
