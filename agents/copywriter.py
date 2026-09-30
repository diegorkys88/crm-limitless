from agents.base import BaseAgent

SYSTEM_PROMPT = """
You are the Copywriter Agent for a CRM system serving a leadership coaching 
company in the U.S. automotive industry.

Your job is to write a personalized outreach email for each prospect.

COMPANY CONTEXT:
- We offer leadership coaching for executives in the automotive industry
- The first step is a COMPLIMENTARY analysis session (no commitment)
- We help companies improve leadership retention, team performance, and results

WRITING RULES:
- Write in English, professional but warm tone
- Keep it SHORT — max 120 words in the body
- Reference the contact's specific title and company when possible
- Do NOT sound like a mass email — it must feel 1-on-1
- End with a clear call to action using the Calendly link provided
- Do NOT use buzzwords like "synergy", "leverage", "game-changer"
- Do NOT use em-dashes (—) anywhere. Use commas, periods, or normal hyphens instead.
- Use the word "complimentary" instead of "free" when describing the analysis session.
- If you sign the email with a name, sign as "Josh Parnell". Never sign as "The Bearded Leader".

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

        # Safety nets: strip em-dashes, fix signature and wording
        if result.get("body"):
            result["body"] = _clean_text(result["body"])
        if result.get("subject"):
            result["subject"] = _clean_text(result["subject"])

        self.log(db, contact.id, "generated_email", profile, raw)
        return result


def _clean_text(text: str) -> str:
    """Strip em-dashes, replace 'free' with 'complimentary', fix the signature."""
    import re
    # Em-dashes → comma
    text = re.sub(r'\s*[—–]\s*', ', ', text)
    text = re.sub(r',\s*,', ',', text)
    # Signature: The Bearded Leader → Josh Parnell (any case)
    text = re.sub(r'[Tt]he\s+[Bb]earded\s+[Ll]eader', 'Josh Parnell', text)
    # "free analysis session" → "complimentary analysis session" (case-insensitive on "free")
    text = re.sub(r'\bfree\b(?=\s+analysis)', 'complimentary', text, flags=re.IGNORECASE)
    # Also catch "free session" and "free consultation"
    text = re.sub(r'\bfree\b(?=\s+(session|consultation|call))', 'complimentary', text, flags=re.IGNORECASE)
    return text


copywriter_agent = CopywriterAgent()
