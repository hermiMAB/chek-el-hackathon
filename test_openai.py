from openai import AzureOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version="2024-02-01"
)
model = os.getenv("AZURE_OPENAI_MODEL")

try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Explain photosynthesis in simple terms."}
        ],
        max_tokens=100
    )
    print("Success! Response:", response.choices[0].message.content)
except Exception as e:
    print("Error:", str(e))