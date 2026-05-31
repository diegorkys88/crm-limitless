from agents.base import BaseAgent

SYSTEM_PROMPT = """
You are the Classifier Agent for an AI-powered CRM system built for a 
leadership coaching company that serves the U.S. automotive industry.

Your job is to analyze a contact's profile and assign a lead score.

IDEAL CLIENT PROFILE:
- Title: C-Level, VP, Director, or General Manager
- Industry: Automotive (dealerships, distributors, manufacturers, parts)
- Company size: 20+ employees
- Location: United States
- Signal: Decision-maker with budget authority

SCORING RULES:
- hot:  Matches 4-5 criteria above. High probability of converting.
- warm: Matches 2-3 criteria. Worth contacting, needs nurturing.
- cold: Matches 0-1 criteria. Low priority for now.

You MUST respond ONLY with a valid JSON object — no markdown, no backticks, no extra text.
Format:
{
  "score": "hot",
  "reason": "One sentence explaining why",
  "priority": 8
}
"""


class ClassifierAgent(BaseAgent):
    name = "classifier"

    def classify(self, contact, db) -> dict:
        profile = f"""
Contact profile:
- Name:     {contact.first_name} {contact.last_name}
- Title:    {contact.title or 'Unknown'}
- Company:  {contact.company or 'Unknown'}
- Industry: {contact.industry or 'Unknown'}
- Region:   {contact.region or 'Unknown'}
- Source:   {contact.source}
"""
        raw    = self.run(profile, SYSTEM_PROMPT, max_tokens=200)
        result = self.parse_json(raw)

        if not result:
            result = {"score": "warm", "reason": "Could not parse response", "priority": 5}

        contact.score = result.get("score", "warm")
        db.commit()

        self.log(db, contact.id, "scored_contact", profile, raw)
        return result


classifier_agent = ClassifierAgent()
