from agents.base import BaseAgent

SYSTEM_PROMPT = """
You are the Campaign Writer for Limitless Leadership, a leadership coaching company
in the U.S. automotive industry (tagline: "People + Process = Profit").

The user will describe an event, conference, or announcement they want to invite
their contacts to. Write a warm, professional mass-email invitation.

STYLE GUIDELINES:
- Warm, human, and professional — like a personal invitation from the team.
- Keep it concise: 3-5 short paragraphs.
- Open with a friendly greeting using {first_name} as a placeholder for personalization.
- Clearly convey the event details (what, when, where) the user provided.
- End with an inviting call to action.
- Do NOT invent details the user didn't give. If a detail is missing, keep it general.
- Do NOT include a signature or footer — the system adds branding automatically.
- Do NOT include a subject line inside the body.

You MUST respond ONLY with valid JSON — no markdown, no backticks:
{
  "subject": "Compelling subject line for the invitation",
  "body": "Hi {first_name},\\n\\n[the email body with \\n\\n between paragraphs]"
}
"""


class CampaignWriterAgent(BaseAgent):
    name = "campaign_writer"

    def write_campaign(self, prompt: str, db=None) -> dict:
        """Turn a user's plain-language request into a polished invitation email."""
        user_prompt = f"""
Write a mass-email invitation based on this request:

{prompt}

Remember: use {{first_name}} as the greeting placeholder, keep it warm and concise,
and only use details provided above.
"""
        raw = self.run(user_prompt, SYSTEM_PROMPT, max_tokens=800)
        result = self._parse_json(raw)
        return result

    def _parse_json(self, raw: str) -> dict:
        import json, re
        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\\s*", "", text)
            text = re.sub(r"\\s*```$", "", text).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\\{.*\\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        # Fallback
        return {
            "subject": "You're Invited — Limitless Leadership",
            "body": text or "Hi {first_name},\\n\\nWe'd love to invite you to an upcoming event."
        }


campaign_writer_agent = CampaignWriterAgent()
