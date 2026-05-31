import os
import re
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL  = "claude-sonnet-4-6"


def clean_json(text: str) -> str:
    """
    Claude sometimes wraps JSON in ```json ... ``` markdown blocks.
    This strips them out so json.loads() works correctly.
    """
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.replace("```", "")
    return text.strip()


class BaseAgent:
    name: str = "base"

    def run(self, prompt: str, system_prompt: str, max_tokens: int = 1000) -> str:
        response = client.messages.create(
            model      = MODEL,
            max_tokens = max_tokens,
            system     = system_prompt,
            messages   = [{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    def parse_json(self, raw: str) -> dict:
        """Clean and parse JSON from Claude response"""
        try:
            return json.loads(clean_json(raw))
        except json.JSONDecodeError:
            return {}

    def log(self, db, contact_id: str, action: str, input_text: str, output_text: str):
        from database import AgentLog
        import uuid
        log = AgentLog(
            id         = str(uuid.uuid4()),
            contact_id = contact_id,
            agent_name = self.name,
            action     = action,
            input      = input_text,
            output     = output_text,
        )
        db.add(log)
        db.commit()
