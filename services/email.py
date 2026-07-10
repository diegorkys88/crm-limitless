import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv()

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_FROM       = os.getenv("EMAIL_FROM",      "crm@yourcompany.com")
EMAIL_FROM_NAME  = os.getenv("EMAIL_FROM_NAME", "Limitless Leadership")


def build_email_html(body: str, sender_name: str = "The Leadership Coaching Team") -> str:
    """
    Professional HTML email template matching Limitless Leadership branding.
    Blue #00187d buttons, clean layout, auto-detects Calendly link for CTA button.
    """
    # Find Calendly link in body
    calendly_url = None
    match = re.search(r'https?://calendly\.com[^\s\n]+', body)
    if match:
        calendly_url = match.group(0)

    # Convert body to HTML paragraphs
    html_lines = []
    for line in body.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Skip raw Calendly URL lines — shown as button instead
        if calendly_url and (calendly_url in line or
           any(kw in line.lower() for kw in ['grab a time', 'schedule here', 'book here', 'click here', 'you can book'])):
            continue
        html_lines.append(
            f'<p style="margin:0 0 16px 0;color:#2c2c2c;font-size:15px;line-height:1.7">{line}</p>'
        )

    body_html = '\n'.join(html_lines)

    cta_button = ""
    if calendly_url:
        cta_button = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:28px 0">
          <tr>
            <td align="center">
              <a href="{calendly_url}"
                 style="display:inline-block;background-color:#00187d;color:#ffffff;
                        font-family:Arial,sans-serif;font-size:15px;font-weight:bold;
                        text-decoration:none;padding:14px 36px;border-radius:4px;
                        letter-spacing:0.5px">
                &#128197; Book a Free Discovery Call
              </a>
            </td>
          </tr>
        </table>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Limitless Leadership</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,Helvetica,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f4f4f4">
    <tr>
      <td align="center" style="padding:32px 16px">
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;
                      overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
          <!-- Header -->
          <tr>
            <td bgcolor="#00187d" style="padding:28px 40px;text-align:center">
              <p style="margin:0;color:#ffffff;font-size:12px;letter-spacing:3px;
                         text-transform:uppercase;font-weight:bold">LIMITLESS LEADERSHIP</p>
              <p style="margin:6px 0 0;color:rgba(255,255,255,0.7);font-size:11px;
                         letter-spacing:2px;text-transform:uppercase">People + Process = Profit</p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:36px 40px 24px">
              {body_html}
              {cta_button}
            </td>
          </tr>
          <!-- Divider -->
          <tr>
            <td style="padding:0 40px">
              <hr style="border:none;border-top:1px solid #eeeeee;margin:0">
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 40px 32px;text-align:center">
              <p style="margin:0 0 4px;color:#555555;font-size:13px;font-weight:bold">
                {sender_name}</p>
              <p style="margin:4px 0 0;color:#888888;font-size:12px">
                <a href="https://limitlessleadership.co"
                   style="color:#00187d;text-decoration:none">limitlessleadership.co</a>
              </p>
              <p style="margin:16px 0 0;color:#cccccc;font-size:10px;line-height:1.6">
                You're receiving this because you expressed interest in leadership coaching.<br>
                To unsubscribe, reply with "unsubscribe" in the subject line.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


class EmailService:

    def send(
        self,
        to_email:    str,
        to_name:     str,
        subject:     str,
        body:        str,
        reply_to:    str = None,
        sender_name: str = None,
    ) -> dict:
        """Send an email via SendGrid using the Limitless Leadership HTML template."""

        sender = sender_name or EMAIL_FROM_NAME

        # Replace [Your Name] placeholder
        body = body.replace("[Your Name]", sender).replace("[YOUR NAME]", sender)

        html_body  = build_email_html(body, sender)
        plain_body = body

        payload = {
            "personalizations": [{"to": [{"email": to_email, "name": to_name}]}],
            "from":             {"email": EMAIL_FROM, "name": sender},
            "subject":          subject,
            "content": [
                {"type": "text/plain", "value": plain_body},
                {"type": "text/html",  "value": html_body},
            ],
        }

        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {SENDGRID_API_KEY}",
                        "Content-Type":  "application/json",
                    }
                )

            if resp.status_code in (200, 202):
                return {
                    "success":    True,
                    "status_code": resp.status_code,
                    "message_id": resp.headers.get("X-Message-Id"),
                }
            else:
                return {"success": False, "error": resp.text, "status_code": resp.status_code}

        except Exception as e:
            return {"success": False, "error": str(e), "status_code": 500}

    def send_batch(self, emails: list[dict]) -> list[dict]:
        """Send multiple emails one by one."""
        results = []
        for email in emails:
            result = self.send(**email)
            result["to_email"] = email.get("to_email")
            results.append(result)
        return results


email_service = EmailService()
