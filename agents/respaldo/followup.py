import json
from agents.base import BaseAgent

SYSTEM_PROMPT = """
You are the Follow-Up Agent for a CRM system serving a leadership coaching 
company in the U.S. automotive industry.

A prospect received an initial outreach email but has not responded.
Your job is to write a short, non-pushy follow-up email.

RULES:
- Max 80 words in the body — shorter than the original
- Acknowledge that they are busy — don't guilt-trip
- Add ONE new piece of value (a quick insight, stat, or question)
- Keep the same Calendly call to action
- Do NOT say "just following up" or "circling back"
- Do NOT repeat the original email — this must feel fresh

You MUST respond ONLY with a valid JSON object — no extra text, no markdown.
Format:
{
  "subject": "Follow-up subject line",
  "body": "Follow-up email body"
}
"""


class FollowUpAgent(BaseAgent):
    name = "follow_up"

    def write_followup(self, contact, original_outreach, days_since: int, db) -> dict:
        """
        Writes a follow-up email for a contact that hasn't responded.
        """
        profile = f"""
Write a follow-up email for this contact who hasn't responded:

CONTACT:
- Name:     {contact.first_name or 'there'}
- Title:    {contact.title or 'Executive'}
- Company:  {contact.company or 'their company'}
- Score:    {contact.score or 'warm'}

ORIGINAL EMAIL SENT {days_since} days ago:
Subject: {original_outreach.subject}
Body: {original_outreach.body[:300] if original_outreach.body else 'N/A'}...

Calendly placeholder: [CALENDLY_LINK]
"""
        raw = self.run(
            prompt        = profile,
            system_prompt = SYSTEM_PROMPT,
            max_tokens    = 400
        )

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "subject": f"Quick follow-up — {contact.company or 'your team'}",
                "body": raw
            }

        # Replace Calendly placeholder
        if original_outreach.calendly_link:
            result["body"] = result.get("body", "").replace(
                "[CALENDLY_LINK]",
                original_outreach.calendly_link
            )

        # Log it
        self.log(
            db          = db,
            contact_id  = contact.id,
            action      = f"generated_followup_day_{days_since}",
            input_text  = profile,
            output_text = raw
        )

        return result


# Singleton
followup_agent = FollowUpAgent()
