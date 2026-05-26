"""Find register-incoming parser definition."""
with open(r'C:\Users\17699\mozhi_platform\src\utils\file_lifecycle.py', 'r', encoding='utf-8') as f:
    src = f.read()

idx = src.find('"register-incoming"')
if idx < 0:
    idx = src.find("'register-incoming'")
print(f"Found at: {idx}")
print(src[idx:idx+2000])
