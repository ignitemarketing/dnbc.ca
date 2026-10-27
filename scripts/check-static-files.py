#!/usr/bin/env python3
"""Focused checks for the static files served from the repository root.

Covers the files added for ignitemarketing/dnbc.ca#3 (404.html, robots.txt,
sitemap.xml, favicon.ico) and the removal of the missing navbar background
reference, plus the plain-HTML conversion: no .php files, every local
reference resolves, and every _redirects rule lands on a real page. Links
stay followed, and no page carries a copy of a script Cloudflare injects.
The site lives in public/, the directory deploy.yml publishes.
Runs on stdlib only: python3 scripts/check-static-files.py
"""
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
REQUIRED = ("404.html", "robots.txt", "sitemap.xml", "favicon.ico", "_redirects", "_headers")
SECURITY_HEADERS = ("Content-Security-Policy", "X-Frame-Options", "Permissions-Policy",
                    "Strict-Transport-Security")

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
        fail("404.html is not ASCII: %s" % exc)
        text = raw.decode("utf-8", "replace")
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


def html_pages():
    return sorted(f for f in os.listdir(ROOT) if f.endswith(".html"))


def check_no_php():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.endswith(".php"):
                fail("%s is a .php file; the site is plain HTML"
                     % os.path.relpath(os.path.join(dirpath, name), ROOT))


class TagCollector(HTMLParser):
    """Every start tag with its attributes, however they are quoted or spaced."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, attrs, self.get_starttag_text()))

    handle_startendtag = handle_starttag


def page_tags(rel):
    collector = TagCollector()
    collector.feed(read(rel).decode("iso-8859-1"))
    collector.close()
    return collector.tags


def check_local_refs():
    for rel in html_pages():
        refs = [value for _, attrs, _ in page_tags(rel) for name, value in attrs
                if name in ("src", "href", "action", "background") and value]
        for ref in refs:
            if re.match(r"^(?:[a-z][a-z0-9+.-]*:|#)", ref, re.I):
                continue
            url_path = ref.split("#")[0].split("?")[0]
            if not url_path.startswith("/"):
                url_path = "/" + url_path
            if url_path.endswith(".php"):
                fail("%s links to %r; link the .html page by its clean path" % (rel, ref))
            elif resolve(url_path) is None:
                fail("%s references %r, which does not exist in this tree" % (rel, ref))


def check_redirects():
    if not os.path.isfile(path("_redirects")):
        return
    for n, line in enumerate(read("_redirects").decode("utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3 or parts[2] != "301":
            fail("_redirects line %d is not 'source target 301': %r" % (n, line))
            continue
        source, target = parts[0], parts[1]
        if resolve(source) is not None:
            fail("_redirects line %d redirects %s, which is a real file" % (n, source))
        if resolve(target) is None:
            fail("_redirects line %d targets %s, which does not exist" % (n, target))


def check_links_followed():
    for rel in html_pages():
        for tag, attrs, raw in page_tags(rel):
            if tag != "a":
                continue
            values = " ".join(value or "" for name, value in attrs if name == "rel")
            if set(values.lower().split()) & {"nofollow", "sponsored", "ugc"}:
                fail("%s has a link that is not followed: %s" % (rel, raw))


def check_no_injected_scripts():
    # Cloudflare injects its analytics beacon and email decoder itself; a
    # copy saved into the source double-loads or points at a dead endpoint.
    pattern = re.compile(r"cloudflareinsights\.com|/cdn-cgi/|__cf_email__")
    for rel in html_pages():
        if pattern.search(read(rel).decode("iso-8859-1")):
            fail("%s carries a copy of a Cloudflare-injected script or email span" % rel)


def check_onpage():
    """Charset, language, viewport, unique title and description, canonical URL."""
    sitemap_locs = set(re.findall(r"<loc>([^<]*)</loc>", read("sitemap.xml").decode("utf-8")))
    titles = {}
    for rel in html_pages():
        tags = page_tags(rel)

        def metas(**want):
            return [attrs for tag, attrs, _ in tags if tag == "meta"
                    and all(dict(attrs).get(k) == v for k, v in want.items())]

        def meta_content(name):
            found = metas(name=name)
            return dict(found[0]).get("content", "").strip() if found else ""

        html_tag = [dict(attrs) for tag, attrs, _ in tags if tag == "html"]
        if not html_tag or not html_tag[0].get("lang"):
            fail("%s has no <html lang>" % rel)
        if not metas(charset="utf-8"):
            fail('%s does not declare <meta charset="utf-8">' % rel)
        if metas(**{"http-equiv": "Content-Type"}):
            fail("%s still carries a Content-Type http-equiv meta" % rel)
        if "width=device-width" not in meta_content("viewport"):
            fail("%s has no responsive viewport meta" % rel)
        if any(tag == "table" and dict(attrs).get("width") == "750" for tag, attrs, _ in tags):
            fail('%s has a fixed <table width="750">; use class="page"' % rel)
        title = " ".join("".join(
            re.findall(r"<title>(.*?)</title>", read(rel).decode("iso-8859-1"), re.S)).split())
        if not title:
            fail("%s has no <title>" % rel)
        titles.setdefault(title, []).append(rel)
        canonical = [dict(attrs).get("href") for tag, attrs, _ in tags
                     if tag == "link" and dict(attrs).get("rel") == "canonical"]
        if rel == "404.html":
            continue
        if not meta_content("description"):
            fail("%s has no meta description" % rel)
        if len(canonical) != 1:
            fail("%s must carry exactly one rel=canonical link, found %d" % (rel, len(canonical)))
        elif canonical[0] not in sitemap_locs:
            fail("%s canonical %r is not a sitemap.xml URL" % (rel, canonical[0]))
    for title, rels in titles.items():
        if len(rels) > 1:
            fail("%s share the title %r" % (", ".join(rels), title))


def check_headers():
    if not os.path.isfile(path("_headers")):
        return
    lines = [l.rstrip() for l in read("_headers").decode("utf-8").splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    if not lines or lines[0] != "/*":
        fail("_headers must start with a '/*' rule, found %r" % (lines[:1],))
        return
    values = {}
    for line in lines[1:]:
        if not line.startswith((" ", "\t")) or ":" not in line:
            fail("_headers line %r is not an indented 'Name: value' header" % line)
            continue
        name, value = line.strip().split(":", 1)
        values[name.strip()] = value.strip()
    for name in SECURITY_HEADERS:
        if not values.get(name):
            fail("_headers does not set %s" % name)
    csp = values.get("Content-Security-Policy", "")
    for directive in ("default-src", "frame-ancestors", "base-uri", "form-action"):
        if not re.search(r"(?:^|;)\s*%s " % directive, csp):
            fail("Content-Security-Policy has no %s directive" % directive)
    script_src = re.search(r"(?:^|;)\s*script-src ([^;]*)", csp)
    if script_src and "'unsafe-inline'" in script_src.group(1):
        fail("Content-Security-Policy allows inline scripts")
    # The policy forbids inline scripts and event handlers, so the pages must
    # not carry any, or the browser would silently drop them.
    for rel in html_pages():
        for tag, attrs, raw in page_tags(rel):
            # JSON-LD is data, not script: the policy does not apply to it.
            if tag == "script" and not any(n == "src" or (n == "type" and v == "application/ld+json")
                                           for n, v in attrs):
                fail("%s has an inline <script>, which the Content-Security-Policy blocks" % rel)
            for name, _ in attrs:
                if name.startswith("on"):
                    fail("%s has the event handler %s, which the Content-Security-Policy blocks"
                         % (rel, name))


def check_emails_unscrambled():
    # Cloudflare's edge email obfuscation turns a bare address outside a link
    # into <a href="/cdn-cgi/l/email-protection">, which crawlers report as a
    # 404. Every address sits inside <!--email_off--> ... <!--/email_off-->.
    for rel in html_pages():
        text = read(rel).decode("iso-8859-1")
        text = re.sub(r"<!--email_off-->.*?<!--/email_off-->", "", text, flags=re.S)
        for addr in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
            fail("%s shows %s outside <!--email_off-->" % (rel, addr))


def main():
    check_required()
    check_robots()
    check_sitemap()
    check_favicon()
    check_404()
    check_no_missing_images()
    check_no_php()
    check_local_refs()
    check_redirects()
    check_onpage()
    check_links_followed()
    check_no_injected_scripts()
    check_emails_unscrambled()
    check_headers()
    if failures:
        for msg in failures:
            print("FAIL %s" % msg)
        print("%d failure(s)" % len(failures))
        return 1
    print("OK %d checks passed" % sum(
        1 for name, fn in globals().items() if name.startswith("check_") and callable(fn)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
