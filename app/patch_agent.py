import re

path = "agent.py"
with open(path, "r") as f:
    text = f.read()

old1 = 'HF_TOKEN = os.environ.get("HF_TOKEN")\nSPACE_URL = "https://rtgcortex-movies.hf.space"'
new1 = 'SPACE_URL = os.environ.get("FINCH_SERVER_URL", "https://counters-editors-tunnel-survey.trycloudflare.com")'
assert text.count(old1) == 1
text = text.replace(old1, new1)

old2 = '''    resp = requests.post(
        f"{SPACE_URL}/chat/stream",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        json=payload,
        stream=True
    )'''
new2 = '''    resp = requests.post(
        f"{SPACE_URL}/chat/stream",
        json=payload,
        stream=True
    )'''
assert text.count(old2) == 1
text = text.replace(old2, new2)

old3 = '''    if not HF_TOKEN:
        print(f"{YELLOW}Warning: HF_TOKEN is not set in environment.{RESET}")

    print_banner(args.no_thinking)'''
new3 = '''    print_banner(args.no_thinking)'''
assert text.count(old3) == 1
text = text.replace(old3, new3)

with open(path, "w") as f:
    f.write(text)

print("patched agent.py")
