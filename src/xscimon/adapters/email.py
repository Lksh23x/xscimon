import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class ProtonMailAdapter:
    """Sends via locally running Proton Mail Bridge (SMTP on localhost)."""

    def __init__(self):
        self._host = os.environ.get("SMTP_HOST", "127.0.0.1")
        self._port = int(os.environ.get("SMTP_PORT", "1025"))
        self._user = os.environ["SMTP_USER"]
        self._password = os.environ["SMTP_PASSWORD"]
        self._from = os.environ["EMAIL_FROM"]

    def send(self, to: str, subject: str, html_body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(self._host, self._port) as server:
            server.login(self._user, self._password)
            server.sendmail(self._from, to, msg.as_string())
