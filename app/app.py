from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import requests
import json

app = FastAPI(title="Cortex AI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SYSTEM_PROMPT = "You are Cortex AI, an advanced artificial intelligence assistant."

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_stream(request: ChatRequest):
    def generate():
        try:
            response = requests.post(
                'http://127.0.0.1:11434/api/generate',
                json={
                    "model": "llama3.2",
                    "prompt": f"{SYSTEM_PROMPT}\n\nUser: {request.message}\n\nCortex AI:",
                    "stream": True
                },
                stream=True,
                timeout=120
            )
            
            for line in response.iter_lines():
                if line:
                    json_response = json.loads(line)
                    if 'response' in json_response and json_response['response']:
                        yield json_response['response']
        except Exception as e:
            yield f"\n[Error: {str(e)}]"
    
    return StreamingResponse(generate(), media_type="text/plain")

@app.get("/")
async def root():
    return {"name": "Cortex AI", "status": "running"}

@app.get("/health")
async def health():
    try:
        response = requests.get('http://127.0.0.1:11434', timeout=5)
        return {"status": "healthy", "ollama": "running"}
    except:
        return {"status": "unhealthy"}