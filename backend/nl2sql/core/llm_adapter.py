import json
import requests


class LLMAdapter:
    def __init__( #set parameters
        self,
        model: str = "qwen2.5-coder:14b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0,
        num_ctx: int = 4096,
        num_predict: int = 1024,
        timeout: int = 180,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.timeout = timeout

    #part that actually queries the LLM
    def generate(self, prompt: str, system: str | None = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        url = f"{self.base_url}/api/generate"
        resp = requests.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
