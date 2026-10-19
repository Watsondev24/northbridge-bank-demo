import re
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

app = FastAPI(title="Language Sensitivity Guardrail Plugin", version="1.0.0")

class PluginRequest(BaseModel):
    payload: Dict[str, Any]
    context: Dict[str, Any]

@app.post('/agent_pre_invoke')
def agent_pre_invoke(data: PluginRequest):
    payload = data.payload
    messages = payload.get('messages') or []
    if not messages:
        return {'continue_processing': True}
    latest = messages[-1]
    content = latest.get('content') or {}
    user_text = content.get('text') or ''
    if not re.search(r'\bsilly\b', user_text, re.IGNORECASE):
        return {'continue_processing': True}
    # Replace the original message with a version containing soft conversation guidance.
    # Agent-generated warnings are not guaranteed UI notices.
    import copy
    modified = copy.deepcopy(payload)
    modified['messages'][-1]['content']['text'] = (
        user_text + '\n\n[Agent instruction: Briefly acknowledge the user\'s '
        'frustration, politely encourage respectful language, then address '
        'their original request. Do not refuse solely because of this wording.]'
    )
    return {'continue_processing': True, 'modified_payload': modified}
