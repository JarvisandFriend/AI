# AI
**Installation**
```sh
   
curl -fsSL https://ollama.com/install.sh | sh
```
**Run The Server**
```sh 
   ollama serve
```
**Pull The Model**
```sh
   ollama pull llama3.2
```
# To Run It In The Background

```sh
   # Start ollama in background
nohup ollama serve > ollama.log 2>&1 &

# Wait a few seconds for it to start
sleep 3

# Now pull the model
ollama pull llama3.2 # 3.1 for more parameters
```
**List Installed**
```
    ollama list

```
**Necessary libraries**

```sh
   pip install fastapi uvicorn requests pydantic
```