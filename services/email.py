import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from dotenv import load_dotenv

load_dotenv()

# Gmail SMTP (Google Workspace) — replaces SendGrid
SMTP_HOST       = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER")       # connect@limitlessleadership.co
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD")   # Google App Password (16 chars)
EMAIL_FROM      = os.getenv("EMAIL_FROM",      SMTP_USER or "crm@yourcompany.com")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Limitless Leadership")


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
        """Send an email via Gmail SMTP (Google Workspace) using the Limitless Leadership HTML template."""

        if not SMTP_USER or not SMTP_PASSWORD:
            return {"success": False, "error": "SMTP_USER / SMTP_PASSWORD not configured", "status_code": 500}

        sender = sender_name or EMAIL_FROM_NAME

        # Replace [Your Name] placeholder
        body = body.replace("[Your Name]", sender).replace("[YOUR NAME]", sender)

        html_body  = build_email_html(body, sender)
        plain_body = body

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = formataddr((sender, EMAIL_FROM))
        msg["To"]      = formataddr((to_name or "", to_email))
        if reply_to:
            msg["Reply-To"] = reply_to

        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body,  "html",  "utf-8"))

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(EMAIL_FROM, [to_email], msg.as_string())

            return {
                "success":     True,
                "status_code": 250,
                "message_id":  msg.get("Message-ID"),
            }

        except smtplib.SMTPAuthenticationError as e:
            return {"success": False, "error": f"SMTP auth failed — check App Password: {e}", "status_code": 535}
        except smtplib.SMTPRecipientsRefused as e:
            return {"success": False, "error": f"Recipient refused: {e}", "status_code": 550}
        except Exception as e:
            return {"success": False, "error": str(e), "status_code": 500}

    def send_batch(self, emails: list[dict]) -> list[dict]:
        """Send multiple emails reusing one SMTP connection."""
        if not SMTP_USER or not SMTP_PASSWORD:
            return [{"success": False, "error": "SMTP not configured"} for _ in emails]

        results = []
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)

                for email in emails:
                    try:
                        sender = email.get("sender_name") or EMAIL_FROM_NAME
                        body   = (email.get("body") or "").replace("[Your Name]", sender).replace("[YOUR NAME]", sender)

                        msg = MIMEMultipart("alternative")
                        msg["Subject"] = email.get("subject", "")
                        msg["From"]    = formataddr((sender, EMAIL_FROM))
                        msg["To"]      = formataddr((email.get("to_name") or "", email["to_email"]))
                        if email.get("reply_to"):
                            msg["Reply-To"] = email["reply_to"]

                        msg.attach(MIMEText(body, "plain", "utf-8"))
                        msg.attach(MIMEText(build_email_html(body, sender), "html", "utf-8"))

                        server.sendmail(EMAIL_FROM, [email["to_email"]], msg.as_string())
                        results.append({"success": True, "to_email": email["to_email"]})
                    except Exception as e:
                        results.append({"success": False, "to_email": email.get("to_email"), "error": str(e)})
        except Exception as e:
            # Connection-level failure — mark remaining as failed
            done = len(results)
            for email in emails[done:]:
                results.append({"success": False, "to_email": email.get("to_email"), "error": f"SMTP connection error: {e}"})

        return results


email_service = EmailService()
