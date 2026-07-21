from agents.base import BaseAgent

SYSTEM_PROMPT = """
You are the Scheduler Agent for a CRM system serving a leadership coaching 
company in the U.S. automotive industry.

When a prospect books a meeting, your job is to prepare a concise briefing 
for the sales rep who will take the call.

BRIEFING MUST INCLUDE:
1. Who is this person (title, company, industry)
2. How they came into the CRM (source)
3. Their lead score and why
4. What to focus on in the conversation
5. Suggested opening question

Keep it under 150 words. Write in a direct, practical tone — 
this is for a sales rep reading it 5 minutes before the call.
"""


class SchedulerAgent(BaseAgent):
    name = "scheduler"

    def generate_summary(self, contact, appointment, db) -> str:
        """
        Generates a pre-meeting briefing for the sales rep.
        """
        # Convert stored UTC time to business timezone (Eastern) for the briefing
        scheduled_display = "TBD"
        if appointment.scheduled_at:
            try:
                from zoneinfo import ZoneInfo
                from datetime import timezone as _tz
                dt = appointment.scheduled_at
                aware = dt.replace(tzinfo=_tz.utc) if dt.tzinfo is None else dt
                local = aware.astimezone(ZoneInfo("America/New_York"))
                scheduled_display = local.strftime("%B %d, %Y at %I:%M %p ET")
            except Exception:
                scheduled_display = str(appointment.scheduled_at)

        profile = f"""
Prepare a pre-meeting briefing for this appointment:

CONTACT:
- Name:     {contact.first_name} {contact.last_name}
- Title:    {contact.title or 'Unknown'}
- Company:  {contact.company or 'Unknown'}
- Industry: {contact.industry or 'Unknown'}
- Region:   {contact.region or 'Unknown'}
- Source:   {contact.source}
- Score:    {contact.score or 'warm'}
- Status:   {contact.status}

MEETING:
- Scheduled: {scheduled_display}
"""
        summary = self.run(
            prompt        = profile,
            system_prompt = SYSTEM_PROMPT,
            max_tokens    = 400
        )

        # Save summary to the appointment
        appointment.ai_summary = summary
        db.commit()

        # Log it
        self.log(
            db          = db,
            contact_id  = contact.id,
            action      = "generated_meeting_summary",
            input_text  = profile,
            output_text = summary
        )

        return summary


# Singleton
scheduler_agent = SchedulerAgent()
