from openai import OpenAI
from .base import BaseLLM


class DeepSeekLLM(BaseLLM):

    def __init__(self, model="deepseek-chat", api_key = None):
        self.client = OpenAI(
            base_url="https://api.deepseek.com",
            api_key= api_key
        )
        self.model = model

    def generate(self, prompt: str):

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.choices[0].message.content