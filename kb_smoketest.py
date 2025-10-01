from agents.protocol.acl_messages import AclMessage, Performative
msg = AclMessage.build_request("demo-1", {"type": "PING"})
print("OK performative:", msg.performative)
print("OK json:", msg.to_json())