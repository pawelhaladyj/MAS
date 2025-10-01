from spade.message import Message
from .acl_messages import AclMessage

def to_spade_message(acl: AclMessage, to_jid: str) -> Message:
    """
    Z AclMessage buduje SPADE Message z odpowiednimi metadanymi i JSON body.
    """
    msg = Message(to=to_jid)
    msg.set_metadata("performative", acl.performative.value)
    msg.set_metadata("conversation_id", acl.conversation_id)
    msg.set_metadata("ontology", acl.ontology)
    msg.set_metadata("language", acl.language)
    msg.body = acl.to_json()
    return msg
