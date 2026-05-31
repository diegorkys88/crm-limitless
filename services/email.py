import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, To, From, ReplyTo
from dotenv import load_dotenv

load_dotenv()

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_FROM       = os.getenv("EMAIL_FROM",      "crm@yourcompany.com")
EMAIL_FROM_NAME  = os.getenv("EMAIL_FROM_NAME", "Your Company")


class EmailService:

    def __init__(self):
        self.client = SendGridAPIClient(api_key=SENDGRID_API_KEY)

    def send(
        self,
        to_email:   str,
        to_name:    str,
        subject:    str,
        body:       str,
        reply_to:   str = None,
        sender_name:str = None,
    ) -> dict:
        """
        Send a single email via SendGrid.
        Returns dict with status and message_id.
        """
        # Replace [Your Name] placeholder if sender_name is provided
        if sender_name:
            body = body.replace("[Your Name]", sender_name)
            body = body.replace("[YOUR NAME]", sender_name)

        # Convert plain text body to simple HTML
        html_body = self._to_html(body)

        message = Mail(
            from_email = From(EMAIL_FROM, sender_name or EMAIL_FROM_NAME),
            to_emails  = To(to_email, to_name),
            subject    = subject,
            html_content = html_body,
            plain_text_content = body,
        )

        if reply_to:
            message.reply_to = ReplyTo(reply_to)

        try:
            response = self.client.send(message)
            return {
                "success":    True,
                "status_code": response.status_code,
                "message_id": response.headers.get("X-Message-Id"),
            }
        except Exception as e:
            return {
                "success":    False,
                "error":      str(e),
                "status_code": 500,
            }

    def send_batch(self, emails: list[dict]) -> list[dict]:
        """
        Send multiple emails one by one.
        Each dict must have: to_email, to_name, subject, body
        Returns list of results.
        """
        results = []
        for email in emails:
            result = self.send(**email)
            result["to_email"] = email.get("to_email")
            results.append(result)
        return results

    def _to_html(self, text: str) -> str:
        """
        Convert plain text to simple HTML.
        Preserves line breaks and makes links clickable.
        """
        import re

        # Escape HTML special chars
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Make URLs clickable
        url_pattern = r'(https?://[^\s]+)'
        text = re.sub(url_pattern, r'<a href="\1" style="color:#1B4F8A">\1</a>', text)

        # Convert line breaks to <br>
        text = text.replace("\n", "<br>")

        # Wrap in basic HTML
        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; font-size: 15px; 
                     color: #333; line-height: 1.6; max-width: 600px; 
                     margin: 0 auto; padding: 20px;">
            {text}
        </body>
        </html>
        """


# Singleton
email_service = EmailService()
