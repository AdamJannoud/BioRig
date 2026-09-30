#!/usr/bin/env python3
"""Compares the regenerated storage layouts (evidence/i6/storageLayout.{original,prei6,after}.*).
Exit 0 only if: every original entry at slots 0-7 equals the after entry (label, slot, offset, normalized type,
and the type definition), the normalized layouts differ by exactly one appended storage entry, and that entry is
_baseTokenURI at slot 8. The appended entry is printed as found; nothing is filtered to hide it."""
import hashlib, json, subprocess, sys
D = "evidence/i6/storageLayout."
def load(n): return json.load(open(f"{D}{n}.normalized.json"))
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
o, p, a = load("original"), load("prei6"), load("after")
ok = True
print("### normalized layout JSON hashes (evidence/normalize_layout.py, unmodified)")
for n in ("original", "prei6", "after"):
    print(sha(f"{D}{n}.normalized.json"), f"storageLayout.{n}.normalized.json")
print("\nprei6 == original (normalized):", p == o); ok &= p == o

print("\n### storage entries, original vs after")
print("original entries:", len(o["storage"]), " after entries:", len(a["storage"]))
for e in o["storage"]:
    same = e in a["storage"] and o["types"][e[3]] == a["types"][e[3]]
    print(("SAME " if same else "DIFF ") + json.dumps(e)); ok &= same
extra = [e for e in a["storage"] if e not in o["storage"]]
print("appended (in after, not in original):"); [print("  " + json.dumps(e)) for e in extra]
ok &= extra == [["_baseTokenURI", "8", 0, "t_string_storage"]]
ok &= a["storage"][: len(o["storage"])] == o["storage"]
print("original entries are an exact prefix of after:", a["storage"][: len(o["storage"])] == o["storage"])
newtypes = sorted(set(a["types"]) - set(o["types"])); print("types added:", newtypes)
ok &= newtypes == ["t_string_storage"] and not (set(o["types"]) - set(a["types"]))

print("\n### forge inspect table rows for slots 0-7 (original vs after)")
def rows(n): return [l for l in open(f"{D}{n}.txt") if l.startswith("| ") and not l.startswith("| Name")]
ro, ra = rows("original"), rows("after")
r07 = [r for r in ra if r.split("|")[3].strip() in map(str, range(8))]
print("rows original:", len(ro), " after:", len(ra))
print(hashlib.sha256("".join(ro).encode()).hexdigest(), " original rows 0-7")
print(hashlib.sha256("".join(r07).encode()).hexdigest(), " after rows 0-7")
ok &= ro == r07
print("after rows beyond slot 7:"); [print("  " + r.rstrip()) for r in ra if r not in r07]
print("\n$ diff storageLayout.original.normalized.json storageLayout.after.normalized.json")
print(subprocess.run(["diff", f"{D}original.normalized.json", f"{D}after.normalized.json"], capture_output=True, text=True).stdout)
print("RESULT:", "PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
