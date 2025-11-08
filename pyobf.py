"""
pyobf.py - simple python obfuscator

Usage:
    python pyobf.py input.py output.py --mode simple
    python pyobf.py input.py output_obf.py --mode ast_rename

Modes:
 - simple: compress+base64 the whole source and produce wrapper that decodes & executes
 - ast_rename: AST-based renaming of local names + string literal encoding (base64+zlib).
"""

import sys
import ast
import argparse
import base64
import zlib
import random
import string
from typing import Dict, Set

# ---------- Utilities ----------
def rand_ident(n=8):
    return '_' + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(n))

def compress_b64(s: bytes) -> str:
    return base64.b64encode(zlib.compress(s)).decode('ascii')

def decompress_b64_expr(b64var_name):
    # expression to decode and decompress a base64 string at runtime
    return f"__import__('zlib').decompress(__import__('base64').b64decode({b64var_name}))"

# ---------- Simple mode ----------
def make_simple_wrapper(source: str) -> str:
    compressed = compress_b64(source.encode('utf-8'))
    wrapper = f"""# Obfuscated by pyobf (simple mode)
import base64, zlib, types, sys
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
