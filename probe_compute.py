"""What can a CI actually compute? The proof-of-work task needs a brute-force search.
Test the instrument's real capability before recommending a fix.
"""
import pathlib
import sys

REPO = pathlib.Path.home() / "Code" / "colony"
sys.path.insert(0, str(REPO))
from colony import instruments                                        # noqa: E402

CASES = [
    ("arithmetic", "2*3+1"),
    ("aggregate", "sum([1,2,3])"),
    ("min/max", "min([3,1,2]) + max([3,1,2])"),
    ("power op", "2^10"),
    ("pow()", "pow(2,10)"),
    ("range", "range(5)"),
    ("list comp", "[n*n for n in range(4)]"),
    ("conditional comp", "[n for n in range(10) if n % 2 == 0]"),
    ("min over comp", "min(n for n in range(10) if n > 5)"),
    ("string", "'a' + 'b'"),
    ("str()", "str(12)"),
    ("slice", "'abcdef'[:3]"),
    ("len()", "len([1,2,3])"),
    ("abs/round", "abs(-3) + round(2.6)"),
    ("attribute", "'abc'.upper()"),
    ("import", "import hashlib"),
    ("hashlib", "hashlib.sha256(b'x').hexdigest()"),
    ("sha256 name", "sha256('colony-5348161:0')"),
]

for label, expr in CASES:
    try:
        out = instruments.safe_eval(expr)
        print(f"  OK   {label:18} {expr[:52]:54} -> {str(out)[:40]}")
    except Exception as exc:                                          # noqa: BLE001
        print(f"  NO   {label:18} {expr[:52]:54} -> {type(exc).__name__}: {str(exc)[:60]}")

print("\n--- the exact expression the PoW task needs (would it work if sha256 existed?) ---")
expr = ("min(n for n in range(300000) if sha256('colony-5348161:' + str(n))[:4] == '0000')")
try:
    print("  OK ->", instruments.safe_eval(expr))
except Exception as exc:                                              # noqa: BLE001
    print(f"  NO -> {type(exc).__name__}: {str(exc)[:160]}")

source = pathlib.Path(REPO / "colony" / "instruments.py").read_text()
for node in ("ast.ListComp", "ast.GeneratorExp", "ast.Subscript", "ast.Slice", "ast.Call",
             "ast.Attribute", "ast.Compare", "ast.BoolOp", "ast.IfExp", "ast.Lambda",
             "ast.Dict", "ast.Set", "ast.Tuple", "ast.Constant", "ast.BinOp", "ast.UnaryOp"):
    print(f"  {node:18} whitelisted: {node in source}")
print("\n  allowed function names found in the file:")
for line in source.splitlines():
    stripped = line.strip()
    if stripped.startswith('"') and stripped.endswith('":'):
        print("   ", stripped)
