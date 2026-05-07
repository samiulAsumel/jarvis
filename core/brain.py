# jarvis-os/core/brain.py
import os
import requests
import json


class JarvisBrain:
    def __init__(
        self,
        provider="ollama",
        model="llama3",
        api_key=None,
        base_url="http://localhost:11434/api/generate",
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def query(
        self,
        prompt,
        system_prompt="You are Jarvis, a helpful and proactive AI OS. You can execute shell commands to help the user.",
    ):
        if self.provider == "ollama":
            return self._query_ollama(prompt, system_prompt)
        elif self.provider == "openai":
            return self._query_openai(prompt, system_prompt)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    def _query_ollama(self, prompt, system_prompt):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
        }
        try:
            response = requests.post(self.base_url, json=payload)
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            return f"Error connecting to Ollama: {str(e)}"

    def _query_openai(self, prompt, system_prompt):
        # Implementation for OpenAI API
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Error connecting to OpenAI: {str(e)}"
