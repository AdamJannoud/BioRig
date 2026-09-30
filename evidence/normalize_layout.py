#!/usr/bin/env python3
"""Reduce a `forge inspect ... storageLayout --json` dump to what determines storage compatibility:
per variable (label, slot, offset, type), plus each type's encoding/size/members. AST node ids
(astId, and the numeric suffix solc embeds in struct type ids) and the source path/contract name (including the
`struct <Contract>.` qualifier in type labels) are dropped, since they change with any edit to the file and say nothing about the layout."""
import json, re, sys

def norm_type(t):
    return re.sub(r'\)\d+_', ')_', t)

d = json.load(open(sys.argv[1]))
out = {
    "storage": [(s["label"], s["slot"], s["offset"], norm_type(s["type"])) for s in d["storage"]],
    "types": {
        norm_type(k): {
            "encoding": v["encoding"], "label": re.sub(r'struct \w+\.', 'struct ', v["label"]), "numberOfBytes": v["numberOfBytes"],
            "key": norm_type(v.get("key", "")), "value": norm_type(v.get("value", "")),
            "members": [(m["label"], m["slot"], m["offset"], norm_type(m["type"])) for m in v.get("members", [])],
        }
        for k, v in sorted(d["types"].items())
    },
}
print(json.dumps(out, indent=1, sort_keys=True))
