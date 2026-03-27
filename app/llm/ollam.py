import requests
from .base import BaseLLM


class OllamaLLM(BaseLLM):

    def __init__(self, model="llama3"):
        self.model = model

    def generate(self, prompt: str):

        r = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": self.model,
                "prompt": prompt
            }
        )

        return r.json()["response"]