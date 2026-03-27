from openai import OpenAI
from .base import BaseLLM


class OpenAILLM(BaseLLM):

    def __init__(self, model="gpt-4o-mini"):
        self.client = OpenAI()
        self.model = model

    def generate(self, prompt: str, **kwargs):

        response = self.client.responses.create(
            model=self.model,
            input=prompt
        )

        return response.output_text