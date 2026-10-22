#!/usr/bin/env python3
"""Focused checks for the static files served from the repository root.

Covers the files added for ignitemarketing/dnbc.ca#3 (404.html, robots.txt,
sitemap.xml, favicon.ico) and the removal of the missing navbar background
reference. Runs on stdlib only: python3 scripts/check-static-files.py
"""
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
REQUIRED = ("404.html", "robots.txt", "sitemap.xml", "favicon.ico")

failures = []


def fail(msg):
    failures.append(msg)


def path(rel):
    return os.path.join(ROOT, rel)


def read(rel):
    with open(path(rel), "rb") as fh:
        return fh.read()


def resolve(url_path):
    """/ -> index.html, /pictures -> pictures.html, /a/b -> a/b."""
    rel = url_path.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    candidates = [rel]
    if "." not in os.path.basename(rel):
        candidates += [rel + ".html", rel + "/index.html"]
    for candidate in candidates:
        if os.path.isfile(path(candidate)):
            return candidate
    return None


def check_required():
    for rel in REQUIRED:
        if not os.path.isfile(path(rel)):
            fail("%s is missing" % rel)
        elif os.path.getsize(path(rel)) == 0:
            fail("%s is empty" % rel)


def check_robots():
    if not os.path.isfile(path("robots.txt")):
        return
    lines = [l.strip() for l in read("robots.txt").decode("utf-8").splitlines()]
    if not any(l.lower() == "user-agent: *" for l in lines):
        fail("robots.txt has no 'User-agent: *' group")
    if not any(l.lower() == "allow: /" for l in lines):
        fail("robots.txt does not allow '/'")
    sitemaps = [l for l in lines if l.lower().startswith("sitemap:")]
    if sitemaps != ["Sitemap: https://dnbc.ca/sitemap.xml"]:
        fail("robots.txt must carry exactly one 'Sitemap: https://dnbc.ca/sitemap.xml' "
             "line, found %r" % (sitemaps,))


def check_sitemap():
    if not os.path.isfile(path("sitemap.xml")):
        return
    try:
        root = ET.fromstring(read("sitemap.xml"))
    except ET.ParseError as exc:
        fail("sitemap.xml is not well-formed XML: %s" % exc)
        return
    if root.tag != SITEMAP_NS + "urlset":
        fail("sitemap.xml root is %r, expected urlset in the sitemaps namespace" % root.tag)
        return
    locs = [el.text.strip() for el in root.iter(SITEMAP_NS + "loc") if el.text]
    if not locs:
        fail("sitemap.xml lists no <loc> entries")
    if len(locs) != len(set(locs)):
        fail("sitemap.xml lists duplicate <loc> entries")
    for loc in locs:
        if not re.match(r"^https://dnbc\.ca(/[^?#]*)?$", loc):
            fail("sitemap.xml loc %r is not an https://dnbc.ca URL" % loc)
            continue
        url_path = re.sub(r"^https://dnbc\.ca", "", loc) or "/"
        if resolve(url_path) is None:
            fail("sitemap.xml loc %r does not resolve to a file in this tree" % loc)


def check_favicon():
    if not os.path.isfile(path("favicon.ico")):
        return
    data = read("favicon.ico")
    if len(data) < 22:
        fail("favicon.ico is %d bytes, too short for a two-icon header" % len(data))
        return
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    if (reserved, kind, count) != (0, 1, 2):
        fail("favicon.ico header is %r, expected (0, 1, 2) for two icons"
             % ((reserved, kind, count),))
        return
    if 6 + 16 * count > len(data):
        fail("favicon.ico ends inside its directory table")
        return
    sizes = []
    for i in range(count):
        entry = data[6 + 16 * i:22 + 16 * i]
        width, height, _, _, planes, bits, length, offset = struct.unpack("<BBBBHHII", entry)
        sizes.append((width or 256, height or 256))
        if bits != 32:
            fail("favicon.ico entry %d is %d-bit, expected 32" % (i, bits))
        if planes != 1:
            fail("favicon.ico entry %d declares %d planes" % (i, planes))
        if offset + length > len(data):
            fail("favicon.ico entry %d runs past the end of the file" % i)
    if sorted(sizes) != [(16, 16), (32, 32)]:
        fail("favicon.ico carries %r, expected 16x16 and 32x32" % (sizes,))


def check_404():
    if not os.path.isfile(path("404.html")):
        return
    raw = read("404.html")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        fail("404.html is not ASCII although it declares iso-8859-1: %s" % exc)
        text = raw.decode("utf-8", "replace")
    if 'charset=iso-8859-1' not in text:
        fail("404.html does not declare the site's iso-8859-1 charset")
    if not re.search(r'href="/"', text):
        fail("404.html carries no link back to the site root")
    for ref in re.findall(r'(?:src|href)="(/[^"]*)"', text):
        if resolve(ref.split("#")[0]) is None:
            fail("404.html references %r, which does not exist in this tree" % ref)


def check_no_missing_images():
    pattern = re.compile(r'/images/navbarbg\.gif')
    for rel in sorted(os.listdir(ROOT)):
        if not rel.endswith((".html", ".php")):
            continue
        if pattern.search(read(rel).decode("iso-8859-1")):
            fail("%s still references /images/navbarbg.gif, which the tree does not contain"
                 % rel)


def main():
    check_required()
    check_robots()
    check_sitemap()
    check_favicon()
    check_404()
    check_no_missing_images()
    if failures:
        for msg in failures:
            print("FAIL %s" % msg)
        print("%d failure(s)" % len(failures))
        return 1
    print("OK %d checks passed" % 6)
    return 0


if __name__ == "__main__":
    sys.exit(main())
