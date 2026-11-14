"""The API providers the service registers for the session executor (D-310, D-311), each a dialect behind
api_sessions.Calls: the nine of OpenAI's shape (openai_chat), Claude on the Anthropic API (anthropic) and on Claude in
Amazon Bedrock (bedrock), Bedrock's Converse for its other models (bedrock-converse) and Vertex AI in express mode
(vertex). Cursor's agents API is registered beside them (cursor_agents).

allowed(text) reads the service's configuration, TOWER_API_MODELS, {"<provider>": ["<model>", ...]}: a provider runs
only the models it names, and a provider it does not name runs none, so no API provider spends by default.
providers(models, key, region, environ) makes them all; key(name) reads /tower/sessions/<name> when a call needs it;
Bedrock signs with the task role in the region. unknown(models, made) names the providers the configuration names but
the service does not have. Standard library only (the SDK and boto3 are imported when a client is first made).
"""
import json

from . import api_sessions, bedrock_converse, claude_api, gemini_api, openai_chat


def allowed(text):
    found = json.loads(text or '{}')
    if not isinstance(found, dict):
        raise ValueError('TOWER_API_MODELS is {"<provider>": ["<model>", ...]}')
    return {name: tuple(str(model) for model in models) for name, models in found.items() if isinstance(models, list)}


def providers(models, key, region, environ):
    made = openai_chat.providers(models, key, environ)
    dialects = {'anthropic': claude_api.Claude(claude_api.anthropic_api(key('anthropic'))),
                'bedrock': claude_api.Claude(claude_api.bedrock(region)),
                'bedrock-converse': bedrock_converse.Converse(bedrock_converse.runtime(region)),
                'vertex': gemini_api.Gemini(gemini_api.BASE, key('vertex'))}
    made.update({name: api_sessions.Calls(dialect, models=models.get(name, ())) for name, dialect in dialects.items()})
    return made


def unknown(models, made):
    return sorted(set(models) - set(made))
