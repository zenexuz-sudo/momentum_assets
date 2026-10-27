"""A small reader for Valve's KeyValues text format (gameinfo.txt, .vdf files).

A block is a list of (key, value) pairs, where value is a string or another block.
Lists, not dicts, because keys repeat ("vpk" appears once per VPK) and order matters.
"""

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


def _tokens(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif c in "{}":
            yield c
            i += 1
        elif c == '"':
            i += 1
            out = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n and text[i + 1] in _ESCAPES:
                    out.append(_ESCAPES[text[i + 1]])
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            i += 1
            yield ("q", "".join(out))
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            yield ("u", text[start:i])


def parse(text):
    """Parse KeyValues text into a block. Conditionals like [$WIN32] are dropped."""
    stack = [[]]
    key = None
    for tok in _tokens(text):
        if tok == "{":
            child = []
            stack[-1].append((key if key is not None else "", child))
            stack.append(child)
            key = None
        elif tok == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        else:
            kind, s = tok
            if kind == "u" and s.startswith("[") and s.endswith("]"):
                continue
            if key is None:
                key = s
            else:
                stack[-1].append((key, s))
                key = None
    return stack[0]


def get(block, key):
    """First value for key (case-insensitive), or None."""
    for k, v in block:
        if k.lower() == key.lower():
            return v
    return None
