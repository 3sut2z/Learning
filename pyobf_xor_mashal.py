import argparse
import os
import base64
import marshal
import random
import secrets
import textwrap

# -------- Helpers --------
def xor_bytes(data: bytes, key: bytes) -> bytes:
    # repeat key
    out = bytearray(len(data))
    klen = len(key)
    for i, b in enumerate(data):
        out[i] = b ^ key[i % klen]
    return bytes(out)

def make_random_ident(n=10):
    import string
    return '_' + ''.join(random.choice(string.ascii_lowercase) for _ in range(n))

# -------- Mode: marshal_xor --------
def build_marshal_xor_wrapper(source: str, key_len=16):
    # compile to code object then marshal
    code_obj = compile(source, '<obf>', 'exec')
    marshalled = marshal.dumps(code_obj)  # bytes
    key = secrets.token_bytes(key_len)
    xored = xor_bytes(marshalled, key)
    b64_payload = base64.b64encode(xored).decode('ascii')
    b64_key = base64.b64encode(key).decode('ascii')

    loader_name = make_random_ident(8)
    wrapper = f"""# Obfuscated by pyobf_xor_marshal (marshal_xor mode)
import base64, marshal
def {loader_name}():
    _k = base64.b64decode({repr(b64_key)})
    _p = base64.b64decode({repr(b64_payload)})
    # xor back
    _d = bytearray(len(_p))
    for i, b in enumerate(_p):
        _d[i] = b ^ _k[i % len(_k)]
    _code = marshal.loads(bytes(_d))
    exec(_code, {{}})
{loader_name}()
"""
    return wrapper

# -------- Mode: chunk_shuffle --------
def build_chunk_shuffle_wrapper(source: str, chunks=30):
    # split into chunks of roughly equal size
    b = source.encode('utf-8')
    L = len(b)
    if chunks < 2:
        chunks = 2
    avg = max(1, L // chunks)
    parts = []
    i = 0
    while i < L:
        size = random.randint(max(1, avg//2), max(1, avg*2))
        part = b[i:i+size]
        parts.append(part)
        i += size
    # encode each part to base64 and assign random ids
    encoded = [base64.b64encode(p).decode('ascii') for p in parts]
    ids = list(range(len(encoded)))
    shuffled = ids[:]
    random.shuffle(shuffled)

    # build loader that reconstructs in correct order using mapping
    loader_name = make_random_ident(8)
    pieces_list_repr = "[\n" + ",\n".join(f"    {repr(s)}" for s in encoded) + "\n]"
    order_repr = repr(shuffled)
    wrapper = f"""# Obfuscated by pyobf_xor_marshal (chunk_shuffle mode)
import base64
def {loader_name}():
    _pieces = {pieces_list_repr}
    _order = {order_repr}   # shuffled indexes
    # rebuild original by placing each piece into correct slot
    _tmp = [None] * len(_pieces)
    for i, idx in enumerate(_order):
        _tmp[idx] = _pieces[i]
    # join and decode
    _b = b''.join(base64.b64decode(x) for x in _tmp)
    exec(compile(_b.decode('utf-8'), '<obf_chunk>', 'exec'), {{}})
{loader_name}()
"""
    return wrapper

# ---------- CLI ----------
def main():
    p = argparse.ArgumentParser(description="pyobf_xor_marshal - alternative python obfuscator")
    p.add_argument("input", help="input python file")
    p.add_argument("output", help="output obfuscated file")
    p.add_argument("--mode", choices=("marshal_xor","chunk_shuffle"), default="marshal_xor")
    p.add_argument("--keylen", type=int, default=16, help="key length for marshal_xor")
    p.add_argument("--chunks", type=int, default=30, help="approx number of chunks for chunk_shuffle")
    args = p.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        src = f.read()

    if args.mode == 'marshal_xor':
        out = build_marshal_xor_wrapper(src, key_len=args.keylen)
    else:
        out = build_chunk_shuffle_wrapper(src, chunks=args.chunks)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(out)

    print(f"Obfuscated ({args.mode}) -> {args.output}")

if __name__ == '__main__':
    main()import base64, zlib, types, sys
_payload = {repr(compressed)}
_data = zlib.decompress(base64.b64decode(_payload))
# execute the code in a fresh globals dict to avoid leaking into wrapper scope
_g = {{}}
exec(compile(_data.decode('utf-8'), '<obf>', 'exec'), _g)
"""
    return wrapper

# ---------- AST renamer + string encoding ----------
class Scope:
    def __init__(self, parent=None):
        self.parent = parent
        self.defined: Set[str] = set()
        self.renames: Dict[str, str] = {}

class Renamer(ast.NodeTransformer):
    def __init__(self):
        super().__init__()
        self.scope = Scope()
        # do not rename these builtins or keywords
        self.builtins = set(dir(__builtins__)) | {
            'True','False','None','__name__','__file__','__package__'
        }

    def push_scope(self):
        self.scope = Scope(parent=self.scope)

    def pop_scope(self):
        self.scope = self.scope.parent

    def _new_name(self, old):
        if old in self.scope.renames:
            return self.scope.renames[old]
        new = rand_ident(8)
        self.scope.renames[old] = new
        return new

    # collect definitions
    def visit_FunctionDef(self, node: ast.FunctionDef):
        # rename function name in current scope if safe
        if node.name not in self.builtins and not node.name.startswith('__'):
            self.scope.defined.add(node.name)
            new_name = self._new_name(node.name)
            node.name = new_name
        # push scope for function body
        self.push_scope()
        # rename args
        for arg in node.args.args:
            if arg.arg not in self.builtins:
                self.scope.defined.add(arg.arg)
                arg.arg = self._new_name(arg.arg)
        # process body
        self.generic_visit(node)
        self.pop_scope()
        return node

    def visit_ClassDef(self, node: ast.ClassDef):
        if node.name not in self.builtins and not node.name.startswith('__'):
            self.scope.defined.add(node.name)
            node.name = self._new_name(node.name)
        self.push_scope()
        self.generic_visit(node)
        self.pop_scope()
        return node

    def visit_Assign(self, node: ast.Assign):
        # collect assigned names as definitions in current scope if simple Names
        for t in node.targets:
            if isinstance(t, ast.Name):
                n = t.id
                if n not in self.builtins and not n.startswith('__'):
                    self.scope.defined.add(n)
                    t.id = self._new_name(n)
        self.generic_visit(node)
        return node

    def visit_Name(self, node: ast.Name):
        # replace names using known renames walking up scopes
        # ignore attribute names (handled in Attribute)
        if isinstance(node.ctx, (ast.Store, ast.Param)):
            # already handled elsewhere
            return node
        n = node.id
        # find rename in current or parent scopes
        s = self.scope
        while s:
            if n in s.renames:
                node.id = s.renames[n]
                return node
            s = s.parent
        # otherwise leave as is
        return node

    def visit_Attribute(self, node: ast.Attribute):
        # don't rename attribute.attr (could break external API). Keep attribute names.
        # But still visit value part
        node.value = self.visit(node.value)
        return node

    def visit_arg(self, node: ast.arg):
        # called for function arguments if not handled earlier
        n = node.arg
        if n not in self.builtins and not n.startswith('__'):
            node.arg = self._new_name(n)
        return node

class StringEncoder(ast.NodeTransformer):
    """
    Replace string literal nodes with expressions that decode base64+zlib at runtime.
    For very short strings we keep them as-is (to avoid overhead).
    """
    def __init__(self, threshold=6):
        self.threshold = threshold
        super().__init__()

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str) and len(node.value) >= self.threshold:
            s = node.value.encode('utf-8')
            b64 = base64.b64encode(zlib.compress(s)).decode('ascii')
            # create ast for: __import__('zlib').decompress(__import__('base64').b64decode("...")).decode('utf-8')
            new_expr = ast.parse(f"(__import__('zlib').decompress(__import__('base64').b64decode({repr(b64)})).decode('utf-8'))").body[0].value
            return ast.copy_location(new_expr, node)
        return node

def make_ast_renamed_wrapper(source: str) -> str:
    tree = ast.parse(source)
    ren = Renamer()
    tree = ren.visit(tree)
    enc = StringEncoder(threshold=6)
    tree = enc.visit(tree)
    ast.fix_missing_locations(tree)
    try:
        new_src = ast.unparse(tree)
    except AttributeError:
        raise RuntimeError("ast.unparse not available. Use Python 3.9+ or install astor and modify code.")
    # To make it a bit more obfuscated, compress the transformed source and embed in wrapper:
    compressed = compress_b64(new_src.encode('utf-8'))
    wrapper = f"""# Obfuscated by pyobf (ast_rename mode)
import base64, zlib, sys
_payload = {repr(compressed)}
_data = zlib.decompress(base64.b64decode(_payload)).decode('utf-8')
# Execute in isolated globals
_g = {{}}
exec(compile(_data, '<obf_ast>', 'exec'), _g)
"""
    return wrapper

# ---------- CLI ----------
def main():
    p = argparse.ArgumentParser(description="pyobf - small Python obfuscator")
    p.add_argument("input", help="input python file")
    p.add_argument("output", help="output obfuscated file")
    p.add_argument("--mode", choices=("simple","ast_rename"), default="simple", help="obfuscation mode")
    args = p.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        src = f.read()

    if args.mode == 'simple':
        out = make_simple_wrapper(src)
    else:
        out = make_ast_renamed_wrapper(src)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(out)

    print(f"Obfuscated ({args.mode}) written to {args.output}")

if __name__ == '__main__':
    main()
