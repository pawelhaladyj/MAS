from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    xmpp_domain: str = os.getenv("XMPP_DOMAIN", "localhost")
    xmpp_host: str = os.getenv("XMPP_HOST", "127.0.0.1")
    xmpp_port: int = int(os.getenv("XMPP_PORT", "5222"))
    presenter_jid: str = os.getenv("XMPP_PRESENTER_JID", "presenter@localhost")
    coordinator_jid: str = os.getenv("XMPP_COORDINATOR_JID", "coordinator@localhost")
    presenter_pass: str = os.getenv("XMPP_PRESENTER_PASS","presenter")
    coordinator_pass: str = os.getenv("XMPP_COORDINATOR_PASS","coordinator")
    verify_security: bool = os.getenv("VERIFY_SECURITY", "false").lower() == "true"
    
settings = Settings()