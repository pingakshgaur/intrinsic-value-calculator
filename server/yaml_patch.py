"""
Change scalar values in agent_settings.yaml without losing its comments.

PyYAML can read the file but would throw every comment away on write, and the
comments are the documentation. This patcher edits the text in place:

    set_value(text, "formula.growth.max", 0.22)

It follows block mappings by indentation and handles a final key that is
either its own line (`max: 0.20   # note`) or a member of a flow mapping on
its parent's line (`bull: {growth_shift: 0.020, rate_shift: -0.010}`).
Lists and new keys are out of scope - those are edited in the raw editor.
"""

import re

KEY = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_ .\-]+?):(?P<rest>.*)$")


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        r = repr(float(v)) if isinstance(v, float) else str(v)
        return r[:-2] if r.endswith(".0") and isinstance(v, int) else r
    s = str(v)
    if s == "" or re.search(r"[:#{}\[\],&*!|>'\"%@`]", s) or s.strip() != s:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _split_comment(rest):
    """' 0.20   # note' -> (' 0.20', '   # note'); ignores # inside quotes."""
    q = None
    for i, ch in enumerate(rest):
        if ch in "\"'":
            q = None if q == ch else (ch if q is None else q)
        elif ch == "#" and q is None and (i == 0 or rest[i - 1].isspace()):
            j = i
            while j > 0 and rest[j - 1].isspace():
                j -= 1
            return rest[:j], rest[j:]
    return rest.rstrip(), rest[len(rest.rstrip()):]


def set_value(text, dotted, value):
    parts = dotted.split(".")
    lines = text.split("\n")
    i, depth, parent_indent = 0, 0, -1
    flow_line = None
    while depth < len(parts):
        want = parts[depth]
        found = None
        while i < len(lines):
            line = lines[i]
            if not line.strip() or line.lstrip().startswith("#"):
                i += 1
                continue
            m = KEY.match(line)
            ind = len(line) - len(line.lstrip())
            if ind <= parent_indent:
                break  # left the parent block without finding the key
            if m and m.group("key").strip() == want and ind > parent_indent:
                found = (i, m, ind)
                break
            i += 1
        if found is None:
            # final key inside a flow mapping on the parent's line?
            if depth == len(parts) - 1 and depth > 0 and flow_line is not None:
                return _set_in_flow(lines, flow_line, want, value)
            raise KeyError(f"'{dotted}' not found (stopped at '{want}')")
        i, m, ind = found
        rest_val, comment = _split_comment(m.group("rest"))
        if depth == len(parts) - 1:
            if rest_val.strip().startswith(("{", "[")) or rest_val.strip() == "":
                raise KeyError(f"'{dotted}' is a section, not a single value")
            lines[i] = f"{m.group('indent')}{m.group('key')}: {_fmt(value)}{comment}"
            return "\n".join(lines)
        flow_line = i if rest_val.strip().startswith("{") else None
        if flow_line is not None and depth == len(parts) - 2:
            return _set_in_flow(lines, flow_line, parts[-1], value)
        parent_indent = ind
        depth += 1
        i += 1
    raise KeyError(dotted)


def _set_in_flow(lines, idx, key, value):
    line = lines[idx]
    pat = re.compile(r"(?P<pre>[{,]\s*)" + re.escape(key) + r"(?P<sep>\s*:\s*)(?P<val>[^,}]*?)(?P<post>\s*[,}])")
    if not pat.search(line):
        raise KeyError(f"'{key}' not in the inline mapping on line {idx + 1}")
    lines[idx] = pat.sub(lambda m: f"{m.group('pre')}{key}{m.group('sep')}{_fmt(value)}{m.group('post')}", line, count=1)
    return "\n".join(lines)
