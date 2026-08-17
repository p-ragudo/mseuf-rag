import uuid

KB_NAMESPACE = uuid.UUID("a3bb189e-8bf9-4888-9912-ace4e6543002")

def generate_uuid(name: str) -> str:
    return str(uuid.uuid5(KB_NAMESPACE, name))