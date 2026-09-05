"""The one place an OpenAI-compatible chat client is built.

OPENAI_BASE_URL points at whichever OpenAI-compatible endpoint is in use -
OpenAI itself, or a LiteLLM proxy such as UF's NaviGator Toolkit
(https://api.ai.it.ufl.edu), which serves open-weight models under the same
API. Building the client here, and nowhere else, is what stops a module from
quietly hard-coding api.openai.com and bypassing the proxy.

The realtime speech-to-speech path (server/agent/pipeline.py) is separate:
it needs OpenAI's realtime model, which proxies do not serve.
"""

from openai import OpenAI

from . import config

DEFAULT_BASE_URL = "https://api.openai.com/v1"


def chat_client(timeout: float = 60) -> OpenAI:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL or DEFAULT_BASE_URL, timeout=timeout)
