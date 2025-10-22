from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import requests
import json
import subprocess
import time
import atexit
import signal
import os

app = FastAPI(title="Cortex AI API", version="1.0.0")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variable to store Ollama process
ollama_process = None

def start_ollama():
    """Start Ollama server as subprocess"""
    global ollama_process
    try:
        print("🚀 Starting Ollama server...")
        # Start Ollama serve in background
        ollama_process = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid  # Create new process group
        )
        
        # Wait for Ollama to be ready
        max_retries = 30
        for i in range(max_retries):
            try:
                response = requests.get('http://127.0.0.1:11434', timeout=1)
                if response.status_code == 200:
                    print("✅ Ollama server started successfully!")
                    return True
            except:
                time.sleep(1)
                print(f"⏳ Waiting for Ollama... ({i+1}/{max_retries})")
        
        print("❌ Failed to start Ollama server")
        return False
    except Exception as e:
        print(f"❌ Error starting Ollama: {e}")
        return False

def stop_ollama():
    """Stop Ollama server"""
    global ollama_process
    if ollama_process:
        print("🛑 Stopping Ollama server...")
        try:
            # Kill the entire process group
            os.killpg(os.getpgid(ollama_process.pid), signal.SIGTERM)
            ollama_process.wait(timeout=5)
        except:
            # Force kill if graceful shutdown fails
            try:
                os.killpg(os.getpgid(ollama_process.pid), signal.SIGKILL)
            except:
                pass
        print("✅ Ollama server stopped")

# Register cleanup on exit
atexit.register(stop_ollama)

@app.on_event("startup")
async def startup_event():
    """Start Ollama when FastAPI starts"""
    start_ollama()

@app.on_event("shutdown")
async def shutdown_event():
    """Stop Ollama when FastAPI stops"""
    stop_ollama()

class ChatRequest(BaseModel):
    message: str

# Cortex AI System Prompt
SYSTEM_PROMPT = "You are Cortex AI, an advanced artificial intelligence assistant. You provide accurate, helpful, and detailed information across all domains including technology, science, business, and more. Be clear, concise, and professional in your responses."

@app.post("/api/chat")
async def chat_stream(request: ChatRequest):
    """
    Cortex AI streaming endpoint - returns raw text without JSON wrapper
    """
    try:
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
                            # Send raw text only
                            yield json_response['response']
            
            except Exception as e:
                yield f"\n[Error: {str(e)}]"
        
        return StreamingResponse(generate(), media_type="text/plain")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/json")
async def chat_json(request: ChatRequest):
    """
    Cortex AI JSON endpoint - returns complete response as JSON
    """
    try:
        start_time = time.time()
        response = requests.post(
            'http://127.0.0.1:11434/api/generate',
            json={
                "model": "llama3.2",
                "prompt": f"{SYSTEM_PROMPT}\n\nUser: {request.message}\n\nCortex AI:",
                "stream": False
            },
            timeout=120
        )
        
        result = response.json()
        processing_time = time.time() - start_time
        
        return {
            "response": result['response'],
            "model": "cortex-ai-llama3.2",
            "processing_time": round(processing_time, 2)
        }
    
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Model took too long to respond")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        response = requests.get('http://127.0.0.1:11434', timeout=5)
        return {
            "status": "healthy",
            "model": "llama3.2",
            "type": "self-hosted",
            "rate_limits": "none",
            "ollama_status": "running",
            "streaming": "plain text"
        }
    except:
        return {
            "status": "unhealthy",
            "ollama_status": "not responding",
            "message": "Ollama may be starting up or not available"
        }

@app.get("/")
async def root():
    return {
        "name": "Cortex AI",
        "version": "1.0.0",
        "message": "🧠 Cortex AI - Advanced Self-Hosted Assistant",
        "model": "Llama 3.2 (3B)",
        "features": ["real-time streaming", "no rate limits", "self-hosted"],
        "endpoints": {
            "chat": "POST /api/chat (streaming text)",
            "chat_json": "POST /api/chat/json (complete JSON)",
            "health": "GET /health",
            "docs": "GET /docs"
        }
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Self-Hosted AI API with Integrated Ollama...")
    print("📝 API will be available at: http://localhost:8000")
    print("📚 Interactive docs at: http://localhost:8000/docs")
    print("🔄 Plain text streaming enabled!")
    uvicorn.run(app, host="0.0.0.0", port=3000)
