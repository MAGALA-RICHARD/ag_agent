
__package__ = 'app'
from .ollam import OllamaLLM
from .openAI import OpenAILLM
from .deep_seek import DeepSeekLLM


def load_llm(provider: str, model: str):
    if provider == "openai":
        return OpenAILLM(model)

    if provider == "deepseek":
        return DeepSeekLLM(model)

    if provider == "ollama":
        return OllamaLLM(model)

    raise ValueError("Unknown provider")


if __name__ == "__main__":
    llm = load_llm(
        provider="deepseek",
        model="deepseek-reasoner"
    )

    agent = APSIMAgent(llm, tools)

    agent.run("optimize maize yield")
