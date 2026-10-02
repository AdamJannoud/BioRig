"""Every word the dashboard puts on screen, in one place.

English only for now. A second language is a second dict with the same keys in LANGUAGES, not a change to any
screen: views call t("key", **values) and never hold their own copy.

The planter flow uses plain words; the operator view keeps the protocol terms on purpose (it is the technical
panel, and its labels are what the tests and the browser gate read). The plan's word list maps one to the other:
spatialNullifier -> plot protection ID, TBA -> tree smart wallet, eth_call simulation -> pre-flight check,
initialDBH -> trunk diameter, H3 res -> plot size, salt -> plot reference, NullifierInUse -> "this plot already has a
tree registered on it", VERIFIER_ROLE -> "you can register trees", broadcast mintTree -> register this tree on Celo,
initialBiomass -> stored biomass (computed). Protocol identifiers in the operator view's tables (field and function
names such as getTreeStats.tbaAddress) are data labels, not wording, and stay beside the code that reads them.
"""
from __future__ import annotations

EN: dict[str, str] = {
    # ------------------------------------------------------------------ shell
    "page.title": "BioRig",
    "page.title_chain": "BioRig · {chain} demo",
    "brand.alt": "BioRig brandmark",
    "view.label": "Viewing as",
    "view.planter": "Planter",
    "view.operator": "Operator",
    "credit": "BioRig — project lead, author and sole deployer: Adam Jannoud",
    "connecting": "Connecting to the chain…",
    "chain.unreachable": "Could not reach the chain: {error}",

    # ------------------------------------------------------------------ planter: steps
    "step.1": "Measure tree",
    "step.2": "Locate plot",
    "step.3": "Claim & register",
    "step.1.short": "Measure",
    "step.2.short": "Locate",
    "step.3.short": "Register",
    "nav.continue": "Continue →",
    "nav.back": "← Back",
    "nav.start_over": "Start over",

    # step 1
    "measure.title": "How thick is the trunk?",
    "measure.lede": "Measure around the trunk at chest height, then divide by 3.14. "
                    "If you don't have a tape, pick the closest one.",
    "measure.slider": "Trunk diameter",
    "measure.biomass": "Stored biomass",
    "measure.carbon": "Carbon",
    "measure.co2e": "CO₂ kept out",
    "measure.assumes": "Assumes a tree about {height:.1f} m tall (from its diameter) with wood density "
                       "{density} g/cm³.",
    "measure.note": "Worked out with the standard pantropical formula (Chave et al. 2014), so the number is one a "
                    "reviewer can check — not a number you typed. **Operator view** still has the manual override "
                    "box.",

    # step 2
    "locate.title": "Where is the tree?",
    "locate.lede": "Stand next to the trunk and tap the button. Nothing leaves your phone except the position.",
    "locate.gps_button": "📍 Use my location",
    "locate.gps_waiting": "Asking your browser for the position…",
    "locate.gps_found": "Position found (within about {accuracy} m).",
    "locate.gps_denied": "Location access was refused. Type the coordinates instead.",
    "locate.gps_unavailable": "Your browser could not find a position. Type the coordinates instead.",
    "locate.gps_unsupported": "This browser has no location access. Type the coordinates instead.",
    "locate.permission_note": "Your browser will ask permission once. No location access? Typing the coordinates "
                              "works the same way.",
    "locate.type_instead": "Type the coordinates instead",
    "locate.lat": "Latitude",
    "locate.lng": "Longitude",
    "locate.size": "Plot size",
    "locate.size.small": "Small",
    "locate.size.medium": "Medium",
    "locate.size.large": "Large",
    "locate.size_value": "{size} plot (≈{across:,.0f} m across)",
    "locate.reference": "Plot reference (optional)",
    "locate.reference_help": "A name for this tree, e.g. \"north field, tree 3\". A new name lets you register "
                             "another tree in the same plot. Left empty, it is \"{default}\".",
    "locate.reference_placeholder": "e.g. north field, tree 3",
    "locate.coords": "Coordinates",
    "locate.from": "From",
    "locate.from.gps": "Your phone's GPS",
    "locate.from.typed": "Typed in",
    "locate.from.default": "The pilot plot (Nairobi)",
    "locate.plot_id": "Unique plot ID",
    "locate.map_caption": "your plot · ≈{area:,.0f} m²",
    "locate.map_alt": "The plot's grid cell drawn around the tree's position",
    "locate.free": "**This plot is free.** Nobody has registered a tree here yet.",
    "locate.taken": "**This plot already has a tree registered on it.** Pick another spot, or give this tree its "
                    "own plot reference.",
    "locate.bad_coords": "Those coordinates are not on the map: {error}",
    "locate.note": "The grid cell is worked out in the background, and the plot ID is just the plot's fingerprint, "
                   "shown so the same plot can't be claimed twice. The coordinates themselves never go on chain.",

    # step 3
    "claim.title": "Claim & register",
    "claim.lede": "One last look, then the pre-flight check.",
    "claim.wallet": "Your wallet address",
    "claim.wallet_help": "The tree is registered to this wallet. It starts as the demo's own account; paste a "
                         "planter's wallet to register the tree to them.",
    "claim.registered_to": "Tree gets registered to",
    "claim.dbh": "Trunk diameter",
    "claim.dbh_value": "{dbh} cm",
    "claim.biomass": "Stored biomass",
    "claim.biomass_value": "{kg:,} kg",
    "claim.plot": "Plot",
    "claim.plot_free": "free",
    "claim.plot_taken": "already registered",
    "claim.wallet_tree": "Tree smart wallet",
    "claim.wallet_tree_pending": "worked out by the check",
    "claim.wallet_tree_help": "a wallet that belongs to the tree itself",
    "claim.check": "Check this tree →",
    "claim.checking": "Checking the plot… this only reads the chain. Nothing has been sent, and nothing costs "
                      "anything yet.",
    "claim.idle": "The check only reads the chain. Nothing is sent, and nothing costs anything.",
    "claim.ready": "**Ready.** This tree can be registered as #{token}. Network fee: about {fee} CELO, charged "
                   "once.",
    "claim.ready_nofee": "**Ready.** This tree can be registered as #{token}.",
    "claim.not_this_one": "**Not this one.** {reason}",
    "claim.reason.NullifierInUse": "This plot already has a tree registered on it.",
    "claim.reason.InvalidNullifier": "The plot could not be worked out from these coordinates.",
    "claim.reason.EnforcedPause": "Registrations are paused on BioRig right now.",
    "claim.reason.AccessControlUnauthorizedAccount": "This demo's account is not allowed to register trees.",
    "claim.reason.wallet": "That wallet address doesn't look right. It should start with 0x and be 42 characters.",
    "claim.reason.other": "The chain would refuse this registration. Operator view shows the technical reason.",
    "claim.no_account": "**Read-only — you can look, not register.** This demo has no registration account set up, "
                        "so the pre-flight check can't run here.",
    "claim.demo_readonly": "**Registration is not enabled on this demo.** Everything above is exactly what would be "
                           "registered; the public demo stops here and never sends a transaction.",
    "claim.confirm": "I confirm: register this tree on Celo from this demo's account",
    "claim.register": "Register this tree on Celo",
    "claim.registering": "Registering on Celo and waiting for the receipt…",
    "claim.register_failed": "Registration failed: {error}",
    "claim.registered": "**Registered.** Your tree is #{token} on Celo.",
    "claim.explorer": "See it on the explorer",
    "claim.download": "Download the record",
    "claim.note": "This demo deployment never sends a transaction unless its owner switches registration on: the "
                  "button runs the same check the real one does, then stops.",

    # live trees
    "trees.title": "On Celo now",
    "trees.lede": "Every tree registered on BioRig, read live from the chain.",
    "trees.badge": "Tree #{token}",
    "trees.alive": "alive",
    "trees.dead": "lost",
    "trees.facts": "{dbh} cm · {kg:,} kg",
    "trees.explorer": "Explorer",
    "trees.none": "No trees registered yet.",
    "trees.contract": "Verified contract (upgradeable)",

    # ------------------------------------------------------------------ operator view (protocol terms kept)
    "op.proxy_source": "Proxy resolved from `{source}`",
    "op.proxy_skipped": " (skipped: {skipped})",
    "op.signing_disabled": "Signing disabled, showing read-only telemetry. {problem}",
    "op.register": "Register a tree",
    "op.planter": "planter",
    "op.planter_help": "Wallet that receives the tree NFT. Defaults to the verifier account; paste a smallholder "
                       "wallet to mint to them.",
    "op.dbh": "initialDBH (cm, uint96)",
    "op.biomass": "initialBiomass (kg, uint96)",
    "op.lat": "lat",
    "op.lng": "lng",
    "op.res": "H3 res",
    "op.salt": "salt",
    "op.salt_help": "Same cell + same salt = same nullifier, which the contract refuses twice (NullifierInUse). A "
                    "new salt registers another tree in the same plot.",
    "op.nullifier_label": "spatialNullifier (auto) · keccak256(uint64(h3Cell) ++ salt)",
    "op.sim_label": "eth_call simulation (runs on every change, never broadcasts)",
    "op.sim_needs_key": "Simulation needs the verifier account, and signing is disabled (see the PRIVATE_KEY "
                        "warning).",
    "op.no_key": "PRIVATE_KEY is not set in .env, so the verifier account is unavailable.",
    "op.invalid_input": "Invalid input: {error}",
    "op.read_only": "Read-only deployment: the form and the eth_call simulation run, the broadcast does not. Set "
                    "ALLOW_MINT=true in Secrets to enable signing a real mintTree.",
    "op.confirm": "I confirm: broadcast this mintTree from the server-side verifier key",
    "op.mint": "Mint tree",
    "op.minting": "Signing on the server and waiting for the receipt…",
    "op.mint_failed": "Mint failed: {error}",
    "op.minted": "✔ minted token #{token} · tx {tx} · block {block:,} · gas {gas:,}",
    "op.view_tx": "view tx on Blockscout",
    "op.token_id": "tokenId",
    "op.live_state": "Live state · getTreeStats({token})",
    "op.stats_reverted": "getTreeStats({token}) reverted: {reason}. No tree with this id yet.",
    "op.tba_title": "ERC-6551 token bound account",
    "op.tba_failed": "TBA derivation failed: {error}",
    "op.tba_caption": "Derived as CREATE2(registry, salt = keccak256(tokenId ++ planter ++ spatialNullifier), "
                      "ERC-1167(implementation) ++ abi.encode(salt, chainId, proxy, tokenId)), exactly as mintTree "
                      "calls createAccount; the planter comes from the mint's Transfer log.",
}

LANGUAGES: dict[str, dict[str, str]] = {"en": EN}
LANGUAGE = "en"


def t(key: str, **values) -> str:
    """The wording for key in the current language, formatted with values. A missing key is a bug, so it raises."""
    text = LANGUAGES[LANGUAGE][key]
    return text.format(**values) if values else text
