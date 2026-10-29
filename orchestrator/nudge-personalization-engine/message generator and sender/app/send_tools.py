"""
Send tools — email (Gmail SMTP, free) and LinkedIn (Unipile API).

Email:  Uses Gmail SMTP with an App Password. No paid service needed.
        Setup: Google Account → Security → 2FA on → App Passwords → generate one.

LinkedIn: Uses Unipile's API to send a DM or InMail via a connected account.
          Unipile handles the LinkedIn session — you just pass the message.
"""

import smtplib
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from .config import settings


# ------------------------------------------------------------------
# EMAIL — Gmail SMTP (free)
# ------------------------------------------------------------------

def send_email(
    to_address: str,
    subject: str,
    body: str,
) -> dict:
    """
    Send an email via Gmail SMTP using an App Password.
    Requires GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env
    """
    if not settings.GMAIL_ADDRESS or not settings.GMAIL_APP_PASSWORD:
        return {"success": False, "error": "GMAIL_ADDRESS or GMAIL_APP_PASSWORD not configured in .env"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject or "(no subject)"
        msg["From"] = settings.GMAIL_ADDRESS
        msg["To"] = to_address
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            server.sendmail(settings.GMAIL_ADDRESS, to_address, msg.as_string())

        return {"success": True, "channel": "email", "to": to_address}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ------------------------------------------------------------------
# LINKEDIN — Unipile API
# ------------------------------------------------------------------

def send_linkedin_dm(
    account_id: str,
    message: str,
    attendee_provider_id: Optional[str] = None,
    attendee_name: Optional[str] = None,
) -> dict:
    """
    Send a LinkedIn DM via Unipile.

    account_id: your Unipile-connected LinkedIn account ID
    attendee_provider_id: the prospect's LinkedIn member URN or username
                          (e.g. "ACoAAA..." or "sarah-chen")

    Requires UNIPILE_API_KEY and UNIPILE_DSN in .env
    """
    if not settings.UNIPILE_API_KEY or not settings.UNIPILE_DSN:
        return {"success": False, "error": "UNIPILE_API_KEY or UNIPILE_DSN not configured in .env"}

    if not attendee_provider_id:
        return {"success": False, "error": "attendee_provider_id (LinkedIn member ID) is required"}

    try:
        url = f"https://{settings.UNIPILE_DSN}/api/v1/chats"
        headers = {
            "X-API-KEY": settings.UNIPILE_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "account_id": account_id,
            "attendees_ids": [attendee_provider_id],
            "text": message,
        }

        response = httpx.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        return {
            "success": True,
            "channel": "linkedin_dm",
            "chat_id": data.get("id"),
            "to": attendee_name or attendee_provider_id,
        }

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"Unipile API error {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
