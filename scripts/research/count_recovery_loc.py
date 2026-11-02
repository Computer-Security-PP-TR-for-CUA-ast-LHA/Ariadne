"""Reproducible Python physical/SLOC counts, never a dependency-size reuse ratio."""
import ast
import io
import json
from pathlib import Path
import subprocess
import tokenize


def count(source):
    docs, code = set(), set()
    for node in ast.walk(ast.parse(source)):
        body = getattr(node, 'body', None)
        if (isinstance(body,list) and body and isinstance(body[0],ast.Expr)
            and isinstance(body[0].value,ast.Constant) and isinstance(body[0].value.value,str)):
            docs.update(range(body[0].lineno,body[0].end_lineno+1))
    ignored = {tokenize.COMMENT,tokenize.NL,tokenize.NEWLINE,tokenize.INDENT,tokenize.DEDENT,tokenize.ENDMARKER}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in ignored:
            code.update(range(token.start[0],token.end[0]+1))
    return {'physical':len(source.splitlines()),'code':len(code-docs)}


def main():
    root=Path(__file__).resolve().parents[2]
    prefix='src/cua_guard/recovery/'
    base='2d2d346'
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',base,prefix],cwd=root,text=True).splitlines()
    old={name:count(subprocess.check_output(['git','show',base+':'+name],cwd=root,encoding='utf-8'))
         for name in names if name.endswith('.py') and not name.endswith('/demo.py')}
    current={p.relative_to(root).as_posix():count(p.read_text(encoding='utf-8'))
             for p in (root/prefix).glob('*.py') if p.name!='demo.py'}
    print(json.dumps({'baseline_commit':base,'baseline_runtime':old,'current_runtime':current,
                     'totals':{label:{k:sum(v[k] for v in rows.values()) for k in ('physical','code')}
                               for label,rows in [('baseline',old),('current',current)]},
                     'note':'Adapters count as our code. External package code is not added to a reuse-percentage denominator.'},indent=2))


if __name__=='__main__':
    main()
