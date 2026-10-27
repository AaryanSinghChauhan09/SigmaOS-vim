"""Neovim distribution engine for SigmaOS-nvim / SigmaOS-vim
(inspired by aether.nvim, lumon.nvim, pixel.nvim, xed, lazyvim).

Principles: manifest is the single source of truth for plugins, plan/execute
separation (git clone argv and health facts are built pure -- self_test never
runs git or nvim), fail-fast on duplicate or malformed plugin specs, generate
config deterministically.
"""
import argparse, json, os, re, shlex, subprocess, sys

ENGINE = {
    "name": "sigma-nvim",
    "summary": "Neovim distribution: plugins, health, install plan, config",
    "language": "python",
    "verbs": ["plugins", "health", "install-plan", "config-gen"],
    "principles": ["Separation of Concerns", "Defensive Programming",
                   "Fail-Fast", "DRY", "KISS", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-nvim plugins --manifest plugins.json
folke/lazy.nvim        dir=lazy/folke--lazy.nvim     ref=main
$ sigma-nvim install-plan --manifest plugins.json --packpath ~/.local/share/nvim/lazy
$ sigma-nvim health --manifest plugins.json --facts facts.json
$ sigma-nvim config-gen --manifest plugins.json --distro aether.nvim
"""

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_NVIM_VER_RE = re.compile(r"\bv?(\d+)\.(\d+)(?:\.(\d+))?")
_SPEC_KEYS = {"repo", "branch", "tag", "pin", "build"}


class NvimError(ValueError):
    pass


def plugin_dir(repo):
    """lazy.nvim-style directory: owner--name."""
    return repo.replace("/", "--")


def parse_manifest(text):
    """Parse the distribution manifest; fail fast on anything ambiguous."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise NvimError(f"manifest is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise NvimError("manifest must be a JSON object")
    distro = data.get("distro")
    if not isinstance(distro, str) or not _NAME_RE.match(distro):
        raise NvimError(f"bad distro name: {distro!r}")
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        raise NvimError('manifest needs a non-empty "plugins" list')
    lua = data.get("lua")
    if lua is not None and not isinstance(lua, str):
        raise NvimError(f"bad lua field: {lua!r}")
    out, seen = [], set()
    for i, row in enumerate(plugins):
        if not isinstance(row, dict):
            raise NvimError(f"plugin #{i} is not an object")
        unknown = set(row) - _SPEC_KEYS
        if unknown:
            raise NvimError(f"plugin #{i}: unknown field(s) {sorted(unknown)}")
        repo = row.get("repo")
        if not isinstance(repo, str) or not _REPO_RE.match(repo):
            raise NvimError(f"plugin #{i}: bad repo {repo!r} (want owner/name)")
        if repo in seen:
            raise NvimError(f"duplicate plugin: {repo}")
        seen.add(repo)
        branch, tag = row.get("branch"), row.get("tag")
        if branch and tag:
            raise NvimError(f"{repo}: branch and tag are mutually exclusive")
        for ref in (branch, tag):
            if ref is not None and (not isinstance(ref, str)
                                    or not _NAME_RE.match(ref)):
                raise NvimError(f"{repo}: bad ref {ref!r}")
        for flag in ("pin", "build"):
            if flag in row and not isinstance(row[flag], bool):
                raise NvimError(f"{repo}: {flag} must be a boolean")
        out.append({"repo": repo, "branch": branch, "tag": tag,
                    "pin": bool(row.get("pin", False)),
                    "build": bool(row.get("build", False))})
    return {"distro": distro, "lua": lua, "plugins": out}


def install_plan(manifest, packpath="~/.local/share/nvim/lazy"):
    """Pure argv plan: one `git clone` per plugin, deterministic order."""
    if not packpath:
        raise NvimError("empty packpath")
    steps = []
    for p in manifest["plugins"]:
        ref = p["branch"] or p["tag"]
        argv = ["git", "clone", "--depth", "1"]
        if ref:
            argv += ["--branch", ref]
        url = f"https://github.com/{p['repo']}.git"
        dest = f"{packpath}/{plugin_dir(p['repo'])}"
        steps.append({"repo": p["repo"], "dest": dest,
                      "argv": argv + [url, dest]})
    return {"packpath": packpath, "distro": manifest["distro"], "steps": steps}


def parse_version(text):
    """'NVIM v0.10.2' / 'NVIM v0.9.5' -> (0, 10, 2). Fail-fast on garbage."""
    if not isinstance(text, str) or not text.strip():
        raise NvimError("empty version output")
    m = _NVIM_VER_RE.search(text.strip())
    if not m:
        raise NvimError(f"cannot parse nvim version from {text!r}")
    return tuple(int(g or 0) for g in m.groups())


def health(manifest, facts):
    """PURE health check: facts are supplied by the caller (no subprocess).

    facts keys: nvim (version string), plugin_dirs (iterable of dir names),
    required (optional nvim version string overriding the manifest's).
    """
    if not isinstance(facts, dict):
        raise NvimError("facts must be a dict")
    checks = []
    raw = facts.get("nvim")
    required = facts.get("required") or _required_nvim(manifest)
    if isinstance(required, str):
        m = _NVIM_VER_RE.search(required)
        required = tuple(int(g or 0) for g in m.groups()[:2]) if m else None
    if raw is None:
        checks.append({"check": "nvim-binary", "ok": False,
                       "detail": "nvim not found on PATH"})
    else:
        have = parse_version(raw)
        if required is None:
            checks.append({"check": "nvim-binary", "ok": True,
                           "detail": f"have {'.'.join(map(str, have))}"})
        elif have[:len(required)] >= required:
            checks.append({"check": "nvim-binary", "ok": True,
                           "detail": f"have {'.'.join(map(str, have))} "
                                     f">= required {'.'.join(map(str, required))}"})
        else:
            checks.append({"check": "nvim-binary", "ok": False,
                           "detail": f"have {'.'.join(map(str, have))} "
                                     f"< required {'.'.join(map(str, required))}"})
    dirs = set(facts.get("plugin_dirs") or ())
    for p in manifest["plugins"]:
        d = plugin_dir(p["repo"])
        ok = d in dirs
        checks.append({"check": f"plugin:{p['repo']}", "ok": ok,
                       "detail": f"dir {d} {'found' if ok else 'MISSING'}"})
    return checks


def _required_nvim(manifest):
    """Manifest `lua` field like 'nvim-0.10' -> (0, 10), else None."""
    m = _NVIM_VER_RE.search(str(manifest.get("lua", "")))
    if not m:
        return None
    return tuple(int(g or 0) for g in m.groups()[:2])


def collect_facts(manifest, packpath="~/.local/share/nvim/lazy"):
    """THIN side-effecting layer: probe the real system. Never self-tested."""
    nvim = None
    try:
        out = subprocess.run(["nvim", "--version"], capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0:
            nvim = out.stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError):
        nvim = None
    try:
        dirs = os.listdir(os.path.expanduser(packpath))
    except OSError:
        dirs = []
    return {"nvim": nvim, "plugin_dirs": dirs}


def _lua_spec(p):
    parts = [f'"{p["repo"]}"']
    if p["branch"]:
        parts.append(f'branch = "{p["branch"]}"')
    if p["tag"]:
        parts.append(f'tag = "{p["tag"]}"')
    if p["pin"]:
        parts.append("pin = true")
    if p["build"]:
        parts.append('build = "make"')
    return "  { " + ", ".join(parts) + " },"


def config_gen(manifest, distro=None, leader=" "):
    """Generate a deterministic init.lua for the distribution."""
    name = distro or manifest["distro"]
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise NvimError(f"bad distro name: {name!r}")
    if not isinstance(leader, str) or len(leader) != 1 or "\n" in leader:
        raise NvimError(f"bad leader key: {leader!r}")
    lines = [
        f"-- generated by sigma-nvim for {name} -- do not edit",
        f'vim.g.mapleader = "{leader}"',
        "vim.opt.number = true",
        "vim.opt.relativenumber = true",
        'vim.opt.signcolumn = "yes"',
        "vim.opt.undofile = true",
        'vim.opt.swapfile = false',
        "",
        'require("lazy").setup({',
    ]
    lines += [_lua_spec(p) for p in manifest["plugins"]]
    lines += [
        "}, {",
        "  checker = { enabled = false },",
        "  change_detection = { enabled = false },",
        "})",
        "",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"], description=ENGINE["summary"])
    sub = p.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--manifest", required=True, help="path to plugins.json")
    pl = sub.add_parser("plugins", parents=[common], help="list plugin specs")
    hp = sub.add_parser("health", parents=[common], help="check a nvim install")
    hp.add_argument("--facts", default=None,
                    help="JSON facts file (otherwise probes the system)")
    hp.add_argument("--packpath", default="~/.local/share/nvim/lazy")
    ip = sub.add_parser("install-plan", parents=[common],
                        help="build git clone argv for every plugin")
    ip.add_argument("--packpath", default="~/.local/share/nvim/lazy")
    cg = sub.add_parser("config-gen", parents=[common], help="generate init.lua")
    cg.add_argument("--distro", default=None)
    cg.add_argument("--leader", default=" ")
    return p


def _load_manifest(path):
    with open(path, "r", encoding="utf-8") as fh:
        return parse_manifest(fh.read())


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = _load_manifest(args.manifest)
        if args.cmd == "plugins":
            for p in manifest["plugins"]:
                ref = p["branch"] or p["tag"] or "-"
                print(f"{p['repo']:<32} dir=lazy/{plugin_dir(p['repo'])}  "
                      f"ref={ref}")
        elif args.cmd == "install-plan":
            plan = install_plan(manifest, args.packpath)
            for step in plan["steps"]:
                print(shlex.join(step["argv"]))
        elif args.cmd == "config-gen":
            print(config_gen(manifest, args.distro, args.leader), end="")
        elif args.cmd == "health":
            if args.facts:
                with open(args.facts, "r", encoding="utf-8") as fh:
                    facts = json.load(fh)
            else:
                facts = collect_facts(manifest, args.packpath)
            failed = 0
            for c in health(manifest, facts):
                mark = "ok  " if c["ok"] else "FAIL"
                if not c["ok"]:
                    failed += 1
                print(f"[{mark}] {c['check']}: {c['detail']}")
            if failed:
                print(f"{failed} check(s) failed", file=sys.stderr)
                return 1
        return 0
    except (NvimError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    SAMPLE = """{
      "distro": "aether.nvim",
      "lua": "nvim-0.10",
      "plugins": [
        {"repo": "folke/lazy.nvim", "branch": "main", "pin": true},
        {"repo": "folke/tokyonight.nvim", "tag": "v4.0.0"},
        {"repo": "nvim-lua/plenary.nvim"},
        {"repo": "nvim-telescope/telescope.nvim", "branch": "master",
         "build": true}
      ]
    }"""
    m = parse_manifest(SAMPLE)
    assert m["distro"] == "aether.nvim"
    assert [p["repo"] for p in m["plugins"]] == [
        "folke/lazy.nvim", "folke/tokyonight.nvim", "nvim-lua/plenary.nvim",
        "nvim-telescope/telescope.nvim"]
    assert m["plugins"][0]["pin"] is True and m["plugins"][1]["tag"] == "v4.0.0"
    assert plugin_dir("folke/lazy.nvim") == "folke--lazy.nvim"

    # fail-fast manifest validation
    for bad in ("not json", "[]",
                '{"distro": "x", "plugins": []}',
                '{"distro": "x", "plugins": [{"repo": "nope"}]}',
                '{"distro": "x", "plugins": [{"repo": "a/b"}, {"repo": "a/b"}]}',
                '{"distro": "x", "plugins": [{"repo": "a/b", "branch": "m", "tag": "v1"}]}',
                '{"distro": "x", "plugins": [{"repo": "a/b", "pin": "yes"}]}',
                '{"distro": "x", "plugins": [{"repo": "a/b", "star": true}]}'):
        try:
            parse_manifest(bad)
        except NvimError:
            pass
        else:
            raise AssertionError(f"manifest should have been rejected: {bad}")

    # install plan (pure argv, deterministic)
    plan = install_plan(m, packpath="~/.local/share/nvim/lazy")
    assert [s["repo"] for s in plan["steps"]] == [p["repo"] for p in m["plugins"]]
    first = plan["steps"][0]["argv"]
    assert first == ["git", "clone", "--depth", "1", "--branch", "main",
                     "https://github.com/folke/lazy.nvim.git",
                     "~/.local/share/nvim/lazy/folke--lazy.nvim"], first
    no_ref = plan["steps"][2]["argv"]
    assert "--branch" not in no_ref and no_ref[-1].endswith("nvim-lua--plenary.nvim")
    assert install_plan(m) == install_plan(m)  # deterministic
    try:
        install_plan(m, packpath="")
    except NvimError:
        pass
    else:
        raise AssertionError("empty packpath not rejected")

    # version parsing
    assert parse_version("NVIM v0.10.2") == (0, 10, 2)
    assert parse_version("NVIM v0.9.5") == (0, 9, 5)
    assert parse_version("nvim 0.11.0-dev") == (0, 11, 0)
    for bad in ("", "no version here", None):
        try:
            parse_version(bad)
        except NvimError:
            pass
        else:
            raise AssertionError(f"version should have been rejected: {bad!r}")

    # health against injected facts (no subprocess, no real FS)
    facts = {"nvim": "NVIM v0.10.2",
             "plugin_dirs": ["folke--lazy.nvim", "folke--tokyonight.nvim",
                             "nvim-lua--plenary.nvim"]}
    checks = health(m, facts)
    by_name = {c["check"]: c for c in checks}
    assert by_name["nvim-binary"]["ok"] is True
    assert by_name["plugin:nvim-lua/plenary.nvim"]["ok"] is True
    assert by_name["plugin:nvim-telescope/telescope.nvim"]["ok"] is False
    assert "MISSING" in by_name["plugin:nvim-telescope/telescope.nvim"]["detail"]
    old = health(m, {"nvim": "NVIM v0.9.0", "plugin_dirs": []})
    assert old[0]["ok"] is False and "< required" in old[0]["detail"]
    missing = health(m, {"plugin_dirs": []})
    assert missing[0]["ok"] is False
    try:
        health(m, "facts.txt")
    except NvimError:
        pass
    else:
        raise AssertionError("bad facts not rejected")

    # config generation (deterministic text)
    lua = config_gen(m)
    assert lua.startswith("-- generated by sigma-nvim for aether.nvim")
    assert 'vim.g.mapleader = " "' in lua
    assert 'require("lazy").setup({' in lua
    assert '{ "folke/lazy.nvim", branch = "main", pin = true },' in lua
    assert '{ "folke/tokyonight.nvim", tag = "v4.0.0" },' in lua
    assert '{ "nvim-lua/plenary.nvim" },' in lua
    assert 'build = "make"' in lua
    assert lua == config_gen(m)  # deterministic
    assert config_gen(m, distro="pixel.nvim").startswith(
        "-- generated by sigma-nvim for pixel.nvim")
    for bad_call in ((config_gen, (m, "bad name!")),
                     (config_gen, (m, None, "gg"))):
        try:
            bad_call[0](*bad_call[1])
        except NvimError:
            pass
        else:
            raise AssertionError(f"should have rejected: {bad_call}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
