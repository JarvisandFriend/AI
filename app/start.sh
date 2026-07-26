#!/bin/bash
ollama serve &
sleep 10
ollama pull llama3.2:1b
exec uvicorn app:app --host 0.0.0.0 --port 7860