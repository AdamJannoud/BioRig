#!/usr/bin/env python3
"""Builds the two pre-change contracts the new I-6 tests are run against (evidence/i6/prechange-*.txt).

orig-stubbed.sol   verbatim src/BioRigCoreV5.sol.orig plus DECLARATIONS ONLY so the suite compiles:
                   the IERC6551Account interface and the InvalidNullifier/InvalidTba errors (as in the
                   previous round), and two no-op stubs `setBaseURI(string)` / `baseURI()` with empty
                   bodies (no storage, no event, no access control, no _baseURI override).
prei6-stubbed.sol  the hardened contract exactly as it was before this change (current file with the
                   I-6 additions removed), plus the same two no-op stubs.
"""
import re, sys
root = sys.argv[1]
STUBS = """
    function setBaseURI(string calldata) external {}

    function baseURI() external view returns (string memory) {}
"""

def add_stubs(s):
    i = s.rstrip().rfind('}')
    return s[:i] + STUBS + s[i:]

o = open(f"{root}/src/BioRigCoreV5.sol.orig").read()
if "interface IERC6551Account" not in o:
    o = o.replace("contract BioRigCoreV5", "interface IERC6551Account {\n    function token() external view returns (uint256 chainId, address tokenContract, uint256 tokenId);\n}\n\ncontract BioRigCoreV5", 1)
for e in ("InvalidNullifier", "InvalidTba"):
    if f"error {e}()" not in o:
        o = o.replace("    error InvalidTree();", f"    error InvalidTree();\n    error {e}();", 1)
open(f"{root}/evidence/i6/orig-stubbed.sol", "w").write(add_stubs(o))

h = open(f"{root}/src/BioRigCoreV5.sol").read()
h = re.sub(r"    /// @dev Appended in slot 8.*?\n    string private _baseTokenURI;\n", "", h, flags=re.S)
h = h.replace("    event BaseURIUpdated(string oldBaseURI, string newBaseURI);\n", "")
h = re.sub(r"    /// @notice Base for the tokenURI fallback.*?\n    function pause\(\)", "    function pause()", h, flags=re.S)
h = re.sub(r"    function _baseURI\(\) internal view override.*?\n    }\n\n", "", h, flags=re.S)
h = h.replace(" (_baseURI() + tokenId)", "")
assert "_baseTokenURI" not in h and "_baseURI" not in h and "BaseURIUpdated" not in h
open(f"{root}/evidence/i6/prei6.sol", "w").write(h)
open(f"{root}/evidence/i6/prei6-stubbed.sol", "w").write(add_stubs(h))
