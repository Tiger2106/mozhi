# Test: does Python 3.14 accept U+FF0C inside a triple-quoted string?
x = """hello\uff0c world"""
print(x)
