from pyngrok import ngrok
import time

# Update the port to match your script's uvicorn.run call
PORT = 3000 

# Ensure any previous tunnels are stopped
ngrok.kill()

# Give the server a moment to start up
time.sleep(5) 

# Create the public tunnel to the new port (3000)
public_url = ngrok.connect(PORT)
print(f"🔥 YOUR PUBLIC API URL IS: {public_url}")
print(f"📖 Interactive Docs are available at: {public_url}/docs")
