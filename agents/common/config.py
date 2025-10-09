from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    xmpp_domain: str = os.getenv("XMPP_DOMAIN", "xmpp.pawelhaladyj.pl")
    xmpp_host: str = os.getenv("XMPP_HOST", "85.215.177.75")
    xmpp_port: int = int(os.getenv("XMPP_PORT", "5222"))
    presenter_jid: str = os.getenv("XMPP_PRESENTER_JID", "presenter@xmpp.pawelhaladyj.pl")
    coordinator_jid: str = os.getenv("XMPP_COORDINATOR_JID", "coordinator@xmpp.pawelhaladyj.pl")
    presenter_pass: str = os.getenv("XMPP_PRESENTER_PASS","presenter")
    coordinator_pass: str = os.getenv("XMPP_COORDINATOR_PASS","coordinator")
    verify_security: bool = os.getenv("VERIFY_SECURITY", "true").lower() == "true"
    acl_max_body_bytes: int = os.getenv("ACL_MAX_BODY_BYTES","65536")
    acl_max_idle_ticks: int = os.getenv("ACL_MAX_IDLE_TICKS","0")
    api_bridge_jid: str = os.getenv("API_BRIDGE_JID", "bridge@xmpp.pawelhaladyj.pl")
    api_bridge_pass: str = os.getenv("API_BRIDGE_PASS", "bridge")
    
    
    
settings = Settings()