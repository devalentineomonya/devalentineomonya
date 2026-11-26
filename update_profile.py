"""Render dark_mode.svg / light_mode.svg with live GitHub stats. Stdlib only.

    python update_profile.py             # fetch from GitHub (needs a token), then render
    python update_profile.py --offline   # render from stats.json
"""
import calendar
import hashlib
import html
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone

USER = "devalentineomonya"
JOINED = date(2023, 10, 7)  # GitHub account created_at: 2023-10-07T18:16:37Z
EAT = timezone(timedelta(hours=3))

INFO = [
    ("OS", "EndeavourOS, Windows"),
    ("Uptime", None),  # filled in from JOINED
    ("Host", "Kirinyaga University, CSK"),
    ("Kernel", "Freelance Full-Stack Engineer"),
    ("WM", "Hyprland"),
    ("Shell", "zsh + tmux"),
    ("IDE", "Neovim, Claude Code, Zed"),
    None,
    ("Languages.Programming", "TypeScript, Go, Python, PHP"),
    ("Languages.Real", "English, Swahili"),
    ("Stack", "Next.js, NestJS, Docker, Linux VPS"),
    ("Hobbies", "Content creation (Valentine In Tech)"),
]
CONTACT = [
    ("Web", "devalentine.com"),
    ("Email", "contact@devalentine.com"),
    ("LinkedIn", "in/devalentineomonya"),
    ("X", "@devalentine_"),
]

# ---------------------------------------------------------------- uptime

def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def uptime(start, today):
    months = (today.year - start.year) * 12 + today.month - start.month
    if add_months(start, months) > today:
        months -= 1
    days = (today - add_months(start, months)).days
    parts = zip((months // 12, months % 12, days), ("year", "month", "day"))
    return ", ".join(f"{n} {w}{'' if n == 1 else 's'}" for n, w in parts)

# ---------------------------------------------------------------- GitHub

def graphql(query, variables=None):
    token = os.environ.get("ACCESS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set ACCESS_TOKEN or GITHUB_TOKEN, or run with --offline")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"Bearer {token}"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.load(r)
            if resp.get("errors"):
                # never echo the details: Actions logs are public, repo names may be private
                raise RuntimeError("GraphQL error: " + str(resp["errors"][0].get("type", "unknown")))
            return resp["data"]
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def own_repos():
    repos, cursor = [], None
    while True:
        page = graphql("""
        query($login: String!, $cursor: String) { user(login: $login) {
          repositories(first: 100, after: $cursor, ownerAffiliations: OWNER) {
            totalCount pageInfo { hasNextPage endCursor }
            nodes { id name isFork stargazerCount defaultBranchRef { target { oid } } }
        } } }""", {"login": USER, "cursor": cursor})["user"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return repos
        cursor = page["pageInfo"]["endCursor"]


def repo_lines(name, user_id):
    add = rem = 0
    cursor = None
    while True:
        ref = graphql("""
        query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
          repository(owner: $owner, name: $name) { defaultBranchRef { target { ... on Commit {
            history(first: 100, author: {id: $id}, after: $cursor) {
              pageInfo { hasNextPage endCursor }
              nodes { additions deletions parents { totalCount } }
        } } } } } }""", {"owner": USER, "name": name, "id": user_id, "cursor": cursor})
        history = ref["repository"]["defaultBranchRef"]["target"]["history"]
        for c in history["nodes"]:
            if c["parents"]["totalCount"] < 2:  # merges would count lines twice
                add += c["additions"]
                rem += c["deletions"]
        if not history["pageInfo"]["hasNextPage"]:
            return add, rem
        cursor = history["pageInfo"]["endCursor"]


def fetch(old):
    years = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z")'
        " { contributionCalendar { totalContributions } }"
        for y in range(JOINED.year, datetime.now(timezone.utc).year + 1)
    )
    user = graphql(f"""query {{ user(login: "{USER}") {{
      id followers {{ totalCount }}
      repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {{ totalCount }}
      {years} }} }}""")["user"]
    repos = own_repos()
    stats = {
        "repos": len(repos),
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "followers": user["followers"]["totalCount"],
        "contributions": sum(
            v["contributionCalendar"]["totalContributions"]
            for k, v in user.items() if k.startswith("y")
        ),
    }

    # lines of code, cached per repo until its default branch moves
    cache, new_cache, failed = old.get("cache", {}), {}, 0
    for r in repos:
        if r["isFork"] or not r["defaultBranchRef"]:
            continue
        key = hashlib.sha256(r["id"].encode()).hexdigest()[:16]
        head = hashlib.sha256(r["defaultBranchRef"]["target"]["oid"].encode()).hexdigest()[:16]
        hit = cache.get(key)
        if not hit or hit[0] != head:
            try:
                hit = [head, *repo_lines(r["name"], user["id"])]
            except Exception as e:
                failed += 1
                print(f"lines of code: one repository failed ({type(e).__name__})")
        if hit:
            new_cache[key] = hit
    add = sum(v[1] for v in new_cache.values())
    rem = sum(v[2] for v in new_cache.values())
    if failed and old.get("loc_add") is not None:
        add, rem = old["loc_add"], old["loc_del"]  # don't publish a partial total
    stats.update(loc_add=add, loc_del=rem, cache=new_cache)
    return stats

# ---------------------------------------------------------------- render

FS, CW, LH = 13, 7.8, 19.5      # info text
AFS, ACW, ALH = 7, 4.2, 7.62    # ascii art
W = 58                          # info column, in characters
ART_X, INFO_X = 18, 18 + 96 * ACW + 22
WIDTH, HEIGHT = int(INFO_X + W * CW + 22), 545

PALETTES = {
    "dark": {"bg": "#0d1117", "border": "#30363d", "h": "#5fd0d6", "k": "#ff9e5e",
             "v": "#c9d1d9", "d": "#484f58", "g": "#3fb950", "r": "#f85149"},
    "light": {"bg": "#ffffff", "border": "#d0d7de", "h": "#0b6e79", "k": "#b0470d",
              "v": "#24292f", "d": "#afb8c1", "g": "#1a7f37", "r": "#cf222e"},
}


def colour(kind, level, rgb, mode):
    """Teal hoodie, amber street lights, in a handful of shades."""
    step = min(int(level * 5), 4)
    warm = kind == "b" or rgb[0] > rgb[2] * 1.15
    shades = {
        ("dark", False): ["#2b5566", "#37738a", "#4f98ab", "#86c3cd", "#d5eef0"],
        ("dark", True): ["#7a2e17", "#b0461c", "#e06a25", "#ffa24c", "#ffe0b8"],
        ("light", False): ["#7fa9b6", "#4f8798", "#2d6c80", "#175166", "#0a384a"],
        ("light", True): ["#e3a585", "#d27a4b", "#bd5a24", "#9c3f10", "#702a08"],
    }
    return shades[(mode, warm)][step]


def text(x, y, s, fill, cw, size=None):
    size = f' font-size="{size}px"' if size else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}"{size} textLength="{len(s) * cw:.1f}" '
            f'lengthAdjust="spacingAndGlyphs" xml:space="preserve">{html.escape(s)}</text>')


def art_svg(art, mode):
    top = (HEIGHT - len(art) * ALH) / 2 + AFS
    out = []
    for y, row in enumerate(art):
        run, start, fill = "", 0, None
        for x, (ch, kind, level, rgb) in enumerate(row + [[" ", "s", 0, [0, 0, 0]]]):
            c = None if ch == " " else colour(kind, level, rgb, mode)
            if c != fill:
                if fill:
                    out.append(text(ART_X + start * ACW, top + y * ALH, run, fill, ACW, AFS))
                run, start, fill = "", x, c
            run += ch
    return out


def kv(key, val, width=W):
    dots = "." * max(width - len(key) - len(val) - 3, 1)
    return [(f"{key}:", "k"), (f" {dots} ", "d"), (val, "v")]


def rule(title, prefix="─ "):
    label = f"{prefix}{title} "
    return [(label, "h"), ("─" * (W - len(label)), "d")]


def info_lines(s, today):
    num = lambda k: "—" if s.get(k) is None else f"{s[k]:,}"
    pair = lambda a, b, c, d: kv(a, b, 31) + [(" | ", "d")] + kv(c, d, W - 34)
    lines = [rule(f"{USER}@github", "")]
    for item in INFO:
        if item is None:
            lines.append([])
            continue
        key, val = item
        lines.append(kv(key, val or uptime(JOINED, today)))
    lines += [[], rule("Contact")] + [kv(*c) for c in CONTACT]
    lines += [
        [], rule("GitHub Stats"),
        pair("Repos", f"{num('repos')} {{Contributed: {num('contributed')}}}", "Stars", num("stars")),
        pair("Contributions", num("contributions"), "Followers", num("followers")),
    ]
    if s.get("loc_add") is None:
        lines.append(kv("Lines of Code", "counting on first run"))
    else:
        lines.append([
            ("Lines of Code: ", "k"), (f"{s['loc_add'] - s['loc_del']:,}", "v"), (" ( ", "d"),
            (f"{s['loc_add']:,}++", "g"), (", ", "d"), (f"{s['loc_del']:,}--", "r"), (" )", "d"),
        ])
    return lines


def render(mode, art, stats, today):
    p = PALETTES[mode]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="Consolas, Menlo, \'DejaVu Sans Mono\', monospace" '
        f'font-size="{FS}px">',
        f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{HEIGHT - 1}" rx="10" '
        f'fill="{p["bg"]}" stroke="{p["border"]}"/>',
    ]
    out += art_svg(art, mode)
    lines = info_lines(stats, today)
    top = (HEIGHT - len(lines) * LH) / 2 + FS
    for i, segs in enumerate(lines):
        col = 0
        for s, c in segs:
            out.append(text(INFO_X + col * CW, top + i * LH, s, p[c], CW))
            col += len(s)
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    with open("ascii_art.json") as f:
        art = json.load(f)
    try:
        with open("stats.json") as f:
            stats = json.load(f)
    except FileNotFoundError:
        stats = {}
    if "--offline" not in sys.argv:
        stats = fetch(stats)
        with open("stats.json", "w") as f:
            json.dump(stats, f, indent=1, sort_keys=True)
    today = datetime.now(EAT).date()
    for mode in PALETTES:
        with open(f"{mode}_mode.svg", "w", encoding="utf-8") as f:
            f.write(render(mode, art, stats, today))
    print("wrote dark_mode.svg, light_mode.svg")
