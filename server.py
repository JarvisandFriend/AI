from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import time

app = FastAPI(title="Self-Hosted AI API", version="1.0.0")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    domain: str = "general"

class ChatResponse(BaseModel):
    response: str
    model: str
    processing_time: float

@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Self-hosted AI chat endpoint - NO external APIs, NO rate limits!
    """
    start_time = time.time()
    
    try:
        # Create a domain-specific system prompt
        system_prompts = {
            "forex trading": "You are an expert forex trader with 20 years of experience. Provide detailed, practical advice about trading strategies, indicators, risk management, and market analysis.",
            "cybersecurity": "You are a cybersecurity expert specializing in penetration testing, vulnerability assessment, and security best practices. Provide technical, accurate information.",
            "bug bounty": "You are an experienced bug bounty hunter. Help identify vulnerabilities, explain exploitation techniques ethically, and provide methodologies for finding security issues.",
            "electrical engineering": "You are an electrical engineer with expertise in circuit design, electronics, power systems, and embedded systems. Provide technical explanations with practical examples.",
            "mechatronics": "You are a mechatronics engineer specializing in robotics, automation, control systems, and electromechanical systems integration.",
            "robotics": "You are a robotics expert with knowledge of kinematics, dynamics, control systems, sensors, actuators, and robot programming.",
            "AI development": "You are an AI/ML engineer with expertise in neural networks, deep learning, model training, deployment, and AI system architecture.",
            "general": "You are a knowledgeable assistant. Provide accurate, helpful information."
        }
        
        system_prompt = system_prompts.get(request.domain, system_prompts["general"])
        
        # Call Ollama API
        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                "model": "llama3.2",
                "prompt": f"{system_prompt}\n\nQuestion: {request.message}\n\nAnswer:",
                "stream": False
            },
            timeout=120
        )
        
        result = response.json()
        processing_time = time.time() - start_time
        
        return ChatResponse(
            response=result['response'],
            model="llama3.2-self-hosted",
            processing_time=round(processing_time, 2)
        )
    
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Model took too long to respond")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        # Check if Ollama is responding
        response = requests.get('http://localhost:11434', timeout=5)
        return {
            "status": "healthy",
            "model": "llama3.2",
            "type": "self-hosted",
            "rate_limits": "none",
            "ollama_status": "running"
        }
    except:
        return {
            "status": "unhealthy",
            "ollama_status": "not responding"
        }

@app.get("/")
async def root():
    return {
        "message": "🚀 Self-Hosted AI API - No Rate Limits!",
        "model": "Llama 3.2 (3B)",
        "endpoints": {
            "chat": "POST /api/chat",
            "health": "GET /health",
            "docs": "GET /docs"
        },
        "supported_domains": [
            "forex trading",
            "cybersecurity", 
            "bug bounty",
            "electrical engineering",
            "mechatronics",
            "robotics",
            "AI development",
            "general"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Self-Hosted AI API...")
    print("📝 API will be available at: http://localhost:8000")
    print("📚 Interactive docs at: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)