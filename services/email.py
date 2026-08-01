import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv()

# Brevo transactional email API (HTTPS — works on Railway Hobby plan)
BREVO_API_KEY   = os.getenv("BREVO_API_KEY")
BREVO_API_URL   = "https://api.brevo.com/v3/smtp/email"
EMAIL_FROM      = os.getenv("EMAIL_FROM",      "connect@limitlessleadership.co")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "Limitless Leadership")
LOGO_URL        = os.getenv("LOGO_URL", "https://web-production-5bd62.up.railway.app/static/blanco.png")

# Social links
SOCIAL = {
    "linkedin":  "https://www.linkedin.com/in/thebeardedleader/",
    "youtube":   "https://www.youtube.com/@thebeardedleader",
    "facebook":  "https://www.facebook.com/profile.php?id=100081354573295",
    "instagram": "https://www.instagram.com/thebeardedleader/",
    "tiktok":    "https://www.tiktok.com/@leadershippodcast",
    "linktree":  "https://linktr.ee/joshparnell",
}
WEBSITE = "https://limitlessleadership.co/"


def build_email_html(body: str, sender_name: str = "The Limitless Leadership Team") -> str:
    """
    Professional HTML email for Limitless Leadership.
    - Logo on blue header
    - Calendly link becomes a button + a plain-text link below it (better deliverability)
    - Footer with website + discreet text social links (legitimacy without heavy marketing signals)
    """
    # Find Calendly link
    calendly_url = None
    m = re.search(r'https?://calendly\.com[^\s\n]+', body)
    if m:
        calendly_url = m.group(0)

    # Body → paragraphs, skipping the raw calendly line and CTA filler
    html_lines = []
    for line in body.split('\n'):
        line = line.strip()
        if not line:
            continue
        if calendly_url and (calendly_url in line or
           any(kw in line.lower() for kw in ['grab a time', 'schedule here', 'book here',
                                             'click here', 'you can book', 'book a time'])):
            continue
        html_lines.append(
            f'<p style="margin:0 0 16px 0;color:#2c2c2c;font-size:15px;line-height:1.7">{line}</p>'
        )
    body_html = '\n'.join(html_lines)

    # CTA: button + plain-text link underneath
    cta = ""
    if calendly_url:
        cta = f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:28px 0 8px">
          <tr>
            <td align="center">
              <a href="{calendly_url}"
                 style="display:inline-block;background-color:#00187d;color:#ffffff;font-size:15px;font-weight:bold;text-decoration:none;padding:14px 36px;border-radius:4px;letter-spacing:0.5px">
                Book a Free Discovery Call
              </a>
            </td>
          </tr>
        </table>
        <p style="margin:0 0 8px 0;text-align:center;color:#888888;font-size:13px;line-height:1.6">
          Or use this link: <a href="{calendly_url}" style="color:#00187d;text-decoration:underline">{calendly_url}</a>
        </p>
        <p style="margin:0 0 20px 0;text-align:center;color:#aaaaaa;font-size:12px">
          You can also simply reply to this email and we'll coordinate a time.
        </p>"""

    social_html = " &nbsp;·&nbsp; ".join(
        f'<a href="{url}" style="color:#777777;text-decoration:none">{label.capitalize()}</a>'
        for label, url in [
            ("LinkedIn",  SOCIAL["linkedin"]),
            ("YouTube",   SOCIAL["youtube"]),
            ("Instagram", SOCIAL["instagram"]),
            ("Facebook",  SOCIAL["facebook"]),
            ("TikTok",    SOCIAL["tiktok"]),
            ("Linktree",  SOCIAL["linktree"]),
        ]
    )

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
               style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">

          <!-- HEADER -->
          <tr>
            <td bgcolor="#00187d" style="padding:32px 40px 26px;text-align:center">
              <img src="{LOGO_URL}" alt="Limitless Leadership" width="66"
                   style="display:block;margin:0 auto 14px;width:66px;height:auto">
              <div style="color:#ffffff;font-size:20px;letter-spacing:3px;font-weight:bold">LIMITLESS LEADERSHIP</div>
              <div style="color:rgba(255,255,255,0.75);font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-top:6px">People + Process = Profit</div>
            </td>
          </tr>

          <!-- BODY -->
          <tr>
            <td style="padding:36px 40px 24px">
              {body_html}
              {cta}
              <p style="margin:8px 0 0;color:#2c2c2c;font-size:15px;line-height:1.7">
                Looking forward to connecting,<br><strong>{sender_name}</strong>
              </p>
            </td>
          </tr>

          <!-- DIVIDER -->
          <tr><td style="padding:0 40px"><hr style="border:none;border-top:1px solid #eeeeee;margin:0"></td></tr>

          <!-- FOOTER -->
          <tr>
            <td style="padding:24px 40px 30px;text-align:center">
              <div style="color:#555555;font-size:13px;font-weight:bold;margin-bottom:4px">Limitless Leadership</div>
              <div style="color:#999999;font-size:12px;margin-bottom:14px">People + Process = Profit</div>
              <div style="margin-bottom:14px">
                <a href="{WEBSITE}" style="color:#00187d;font-size:13px;text-decoration:none;font-weight:600">limitlessleadership.co</a>
              </div>
              <div style="color:#bbbbbb;font-size:12px;line-height:1.9">{social_html}</div>
              <div style="color:#cccccc;font-size:10px;line-height:1.6;margin-top:18px">
                You're receiving this because you expressed interest in leadership coaching.<br>
                To unsubscribe, reply with "unsubscribe" in the subject line.
              </div>
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
        """Send an email via Brevo API using the Limitless Leadership HTML template."""
        if not BREVO_API_KEY:
            return {"success": False, "error": "BREVO_API_KEY not configured", "status_code": 500}

        sender = sender_name or EMAIL_FROM_NAME
        body   = body.replace("[Your Name]", sender).replace("[YOUR NAME]", sender)

        html_body  = build_email_html(body, sender)
        plain_body = body

        payload = {
            "sender":      {"email": EMAIL_FROM, "name": sender},
            "to":          [{"email": to_email, "name": to_name or to_email}],
            "subject":     subject,
            "htmlContent": html_body,
            "textContent": plain_body,
            "replyTo":     {"email": reply_to or EMAIL_FROM, "name": sender},
        }

        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(
                    BREVO_API_URL, json=payload,
                    headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json", "Accept": "application/json"}
                )
            if resp.status_code in (200, 201):
                return {"success": True, "status_code": resp.status_code, "message_id": resp.json().get("messageId")}
            return {"success": False, "error": resp.text, "status_code": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e), "status_code": 500}

    def send_batch(self, emails: list[dict]) -> list[dict]:
        results = []
        for email in emails:
            result = self.send(**email)
            result["to_email"] = email.get("to_email")
            results.append(result)
        return results


email_service = EmailService()
