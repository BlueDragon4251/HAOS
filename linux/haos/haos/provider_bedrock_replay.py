"""Model/endpoint-bound Converse replay carried by Hermes's public detail seam."""
from copy import deepcopy
import hashlib

TYPE = "haos.bedrock.native_assistant"


def carrier(blocks, model, endpoint):
    return {"type": TYPE, "model": model, "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(), "blocks": blocks}


def restore(messages, model, endpoint):
    output = deepcopy(messages)
    binding = hashlib.sha256(endpoint.encode()).hexdigest()
    for message in output:
        details = message.get("reasoning_details")
        if not isinstance(details, list):
            continue
        candidates = [item for item in details if isinstance(item, dict) and item.get("type") == TYPE]
        message["reasoning_details"] = [item for item in details if not isinstance(item, dict) or item.get("type") != TYPE]
        for item in candidates:
            if (item.get("model") == model and item.get("endpoint_sha256") == binding and isinstance(item.get("blocks"), list)):
                message["bedrock_content_blocks"] = item["blocks"]
                break
    return output
