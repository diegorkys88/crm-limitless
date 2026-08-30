from agents.base import BaseAgent

SYSTEM_PROMPT = """
You are the Copywriter Agent for a CRM system serving a leadership coaching 
company in the U.S. automotive industry.

Your job is to write a personalized outreach email for each prospect.

COMPANY CONTEXT:
- We offer leadership coaching for executives in the automotive industry
- The first step is a FREE analysis session (no commitment)
- We help companies improve leadership retention, team performance, and results

WRITING RULES:
- Write in English, professional but warm tone
- Keep it SHORT — max 120 words in the body
- Reference the contact's specific title and company when possible
- Do NOT sound like a mass email — it must feel 1-on-1
- End with a clear call to action using the Calendly link provided
- Do NOT use buzzwords like "synergy", "leverage", "game-changer"
- Do NOT use em-dashes (—) anywhere. Use commas, periods, or normal hyphens instead.

You MUST respond ONLY with a valid JSON object — no markdown, no backticks, no extra text.
Format:
{
  "subject": "Email subject line",
  "body": "Full email body text"
}
"""


class CopywriterAgent(BaseAgent):
    name = "copywriter"

    def write_email(self, contact, calendly_link: str, db) -> dict:
        profile = f"""
Write an outreach email for this contact:
- Name:     {contact.first_name or 'there'}
- Title:    {contact.title or 'Executive'}
- Company:  {contact.company or 'your company'}
- Industry: {contact.industry or 'automotive'}
- Region:   {contact.region or 'United States'}
- Score:    {contact.score or 'warm'}

Include this Calendly link in the call to action: {calendly_link}
"""
        raw    = self.run(profile, SYSTEM_PROMPT, max_tokens=600)
        result = self.parse_json(raw)

        if not result:
            result = {
                "subject": f"A quick question for {contact.first_name or 'you'}",
                "body": raw
            }

        # Safety net: strip any em-dashes the model may have used
        if result.get("body"):
            result["body"] = _strip_emdash(result["body"])
        if result.get("subject"):
            result["subject"] = _strip_emdash(result["subject"])

        self.log(db, contact.id, "generated_email", profile, raw)
        return result


def _strip_emdash(text: str) -> str:
    """Replace em-dashes and en-dashes with a comma, cleaning surrounding spaces."""
    import re
    # Replace " — " or "—" (and en-dash –) with ", "
    text = re.sub(r'\s*[—–]\s*', ', ', text)
    # Avoid doubled commas if the model already had one nearby
    text = re.sub(r',\s*,', ',', text)
    return text


copywriter_agent = CopywriterAgent()
