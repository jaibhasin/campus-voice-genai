"""OpenAI-compatible answer client with accurate LangSmith provider metadata."""

from langchain_openai import ChatOpenAI


class OpenRouterChatOpenAI(ChatOpenAI):
    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        # ChatOpenAI otherwise overrides caller metadata with provider=openai.
        params["ls_provider"] = "openrouter"
        return params
