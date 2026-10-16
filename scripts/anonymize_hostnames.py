#!/usr/bin/env python3
"""Anonymize RegisteredAddresses.json hostnames with dictionary words.

The register's hostname column holds device labels (asset numbers, names,
device-type strings) rather than real hostnames. Two modes:

  blank (default)  Replace every non-RFC hostname with a stable dictionary word
                   derived from the device MAC (hash -> word index,
                   collision-skipped so every word is unique and never collides
                   with a kept valid hostname). Deterministic across re-runs.
  scan             Live-resolve real hostnames (ARP cache + reverse-DNS via the
                   engine) and insert them over dictionary-word placeholders
                   ONLY — real/curated hostnames are never overwritten. Use the
                   SAME wordlist that produced the placeholders.

Writes are atomic (temp file + rename) with a `.bak` backup. `--dry-run` prints
the plan without writing anything. Reuses the rotation engine helpers and the
fisheye-gui mac_tools library.

Usage:
    python3 scripts/anonymize_hostnames.py [blank|scan] [--dry-run] [--register PATH] [--wordlist PATH]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()
DIR = HERE.parents[1]
FISHEYE_GUI = DIR.parent / "fisheye-gui"

for _p in (str(FISHEYE_GUI), str(DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.rotation_engine import (  # noqa: E402
    blank_hostnames, is_valid_hostname, registered_path, resolve_hostnames_live,
)

DEFAULT_WORDLIST = (
    "alpine amber anchor apple apricot arctic arrow atlas autumn azure "
    "badger bamboo banana banner basil basin beaver beetle berry birch bison "
    "blade blizzard blossom bluebell board bolt boulder branch brass breeze "
    "brick bridge brook brush buckle bud buffalo butterfly button cactus "
    "camellia camel canyon carbon cardinal carrot cedar celery chanterelle "
    "charcoal cherry chestnut chisel cinnamon citron clay cliff cloud clover "
    "coal cobalt cocoa coconut coffee comet condor copper coral cotton cougar "
    "crabapple crane cream crest cricket crystal cucumber currant cyclone "
    "daffodil daisy dandelion dawn delta diamond dill dolphin dome dove "
    "dragonfly driftwood dusk eagle ebony echo eel elm ember emerald falcon "
    "fern fiddlehead fig finch firefly flannel flint flower fog forest fox "
    "frost galaxy gardenia garnet gecko ginger ginkgo glacier glow gneiss "
    "goldfinch granite grapefruit grass gravel gull hail harbor hazel heather "
    "helix heron hibiscus honey horizon hornbeam huckleberry hummingbird "
    "iceberg iguana indigo iris ivy jade jasmine jasper juniper kelp kestrel "
    "kiwi lagoon lapis larch laurel lavender lemon lichen lightning lilac lily "
    "limestone linden linen lion lizard lotus lynx magnolia mahogany maize "
    "mango maple marble marigold marmot marsh meadow meridian mica mint mist "
    "mockingbird moose moss moth mousse mulberry myrtle narwhal nasturtium "
    "nebula nectar neon nettle nickel nightingale nutmeg oak obsidian ocean "
    "octopus olive onion opal orange orchid oriole osprey otter oyster "
    "paintbrush palm panda papaya parakeet parsley peach peacock pebble "
    "pelican peony pepper periwinkle persimmon petal pewter phlox picnic "
    "pigeon pine pinecone pistachio plum pomegranate poplar poppy porpoise "
    "potato prairie primrose prism pumpkin puffin quartz quill radish rainbow "
    "raven redwood reed rhino rhododendron robin rocket rose rosemary ruby "
    "saffron sage salmon sandstone sapphire scallop seafoam seagull sequoia "
    "shadow shark shell shingle silver skylark slate sleet sloth snowdrop "
    "sparrow spearmint spice spider sponge spruce squall squid squirrel "
    "starling steel stork storm strawberry sugar summer sunflower surf swallow "
    "swan swift sycamore talon tarragon teak tempest thistle thyme tide tiger "
    "timber titanium toad topaz torrent trout tulip tumbleweed tundra "
    "turquoise turtle twilight urchin valley vanilla violet viper volcano "
    "walnut wasp waterfall wave weasel wattle wheat whippoorwill willow wind "
    "wintergreen wolf wren yarrow yellowstone yew zebra"
).split()


def load_register(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} is not a JSON array")
    return data


def atomic_write(data, path):
    """Write ``data`` atomically; return the backup path created (or None)."""
    dst = os.path.abspath(path)
    d = os.path.dirname(dst)
    bak = None
    if os.path.isfile(dst):
        bak = f"{dst}.bak"
        shutil.copy2(dst, bak)
    fd, tmp = tempfile.mkstemp(prefix=".anonymize-", suffix=".json", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return bak


def load_wordlist(path):
    with open(path, "r", encoding="utf-8") as f:
        return [w.strip() for w in f if w.strip()]


def run_blank(devices, wordlist, dry_run):
    out, blanks = blank_hostnames(devices, wordlist)
    print(f"[i] {len(devices)} devices, {len(blanks)} hostnames to blank")
    for b in blanks[:5]:
        print(f"    {b['mac']}  {b['old']!r} -> {b['new']}")
    if len(blanks) > 10:
        print("    ...")
    for b in blanks[-3:]:
        print(f"    {b['mac']}  {b['old']!r} -> {b['new']}")
    if dry_run:
        print("[i] --dry-run: no changes written")
        return blanks, None
    return blanks, out


def run_scan(devices, wordlist, dry_run):
    placeholders = {w.lower() for w in wordlist}
    macs = [d.get("mac", "") for d in devices]
    print(f"[i] resolving {len(macs)} devices on the network (ARP + reverse-DNS)...")
    live, _last_seen = resolve_hostnames_live(macs, known_map={})
    changes = []
    out = [dict(d) for d in devices]
    for d in out:
        cur = str(d.get("hostname", "") or "").strip()
        if cur.lower() not in placeholders:
            continue
        found = str(live.get(d.get("mac", "")) or "").strip()
        if found and is_valid_hostname(found) and found != cur:
            changes.append({"mac": d.get("mac", ""), "old": cur, "new": found})
            d["hostname"] = found
    print(f"[i] {len(changes)} placeholder hostnames replaced by live hostnames")
    for c in changes[:10]:
        print(f"    {c['mac']}  {c['old']!r} -> {c['new']}")
    if len(changes) > 12:
        print("    ...")
    if dry_run:
        print("[i] --dry-run: no changes written")
        return changes, None
    return changes, out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=["blank", "scan"], default="blank",
                        help="blank (default) or scan mode")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan without writing any changes")
    parser.add_argument("--register", default=None, help="Path to RegisteredAddresses.json")
    parser.add_argument("--wordlist", default=None, help="Custom wordlist file (one word per line)")
    args = parser.parse_args(argv)

    reg = args.register or registered_path()
    try:
        devices = load_register(reg)
    except (OSError, ValueError) as e:
        print(f"[-] Cannot read register {reg}: {e}", file=sys.stderr)
        return 1

    if args.wordlist:
        try:
            wordlist = load_wordlist(args.wordlist)
        except OSError as e:
            print(f"[-] Cannot read wordlist {args.wordlist}: {e}", file=sys.stderr)
            return 1
    else:
        wordlist = DEFAULT_WORDLIST

    try:
        if args.mode == "blank":
            changes, out = run_blank(devices, wordlist, args.dry_run)
        else:
            changes, out = run_scan(devices, wordlist, args.dry_run)
    except ValueError as e:
        print(f"[-] {e}", file=sys.stderr)
        return 1

    if out is not None:
        bak = atomic_write(out, reg)
        if bak:
            print(f"[+] wrote {reg} (backup: {bak})")
        else:
            print(f"[+] wrote {reg}")
        print(f"[+] {len(changes)} hostname changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
