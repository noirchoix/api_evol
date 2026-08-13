from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from core.config import settings


LANGUAGE_BY_SUFFIX={
    '.py':'python','.pyi':'python','.js':'javascript','.jsx':'javascript','.mjs':'javascript','.cjs':'javascript',
    '.ts':'typescript','.tsx':'typescript','.mts':'typescript','.cts':'typescript','.svelte':'svelte',
    '.json':'json','.yaml':'yaml','.yml':'yaml','.toml':'toml','.md':'markdown','.html':'html','.css':'css',
}
ANALYZED_LANGUAGES={'python','javascript','typescript','svelte'}
HTTP_METHODS={'get','post','put','patch','delete','head','options'}
SKIP_PARTS={'.git','node_modules','.svelte-kit','dist','build','.next','coverage','vendor','__pycache__','.venv','venv'}


class RepositoryError(ValueError):
    pass


def dotted(node:ast.AST) -> str:
    if isinstance(node,ast.Name): return node.id
    if isinstance(node,ast.Attribute): return f'{dotted(node.value)}.{node.attr}'.strip('.')
    return ''


def literal_string(node:ast.AST) -> tuple[str,bool]:
    if isinstance(node,ast.Constant) and isinstance(node.value,str): return node.value,True
    if isinstance(node,ast.JoinedStr):
        parts=[]
        for v in node.values:
            if isinstance(v,ast.Constant) and isinstance(v.value,str): parts.append(v.value)
            else: parts.append('{}')
        return ''.join(parts),False
    return '',False


class PythonVisitor(ast.NodeVisitor):
    def __init__(self,path:str):
        self.path=path; self.symbol_stack=[]; self.network=[]; self.imports=[]; self.fields=[]; self.strings=[]; self.symbols=[]

    @property
    def symbol(self) -> str: return '.'.join(self.symbol_stack)

    def visit_FunctionDef(self,node:ast.FunctionDef):
        self.symbols.append({'name':node.name,'line':node.lineno,'kind':'function'}); self.symbol_stack.append(node.name); self.generic_visit(node); self.symbol_stack.pop()
    visit_AsyncFunctionDef=visit_FunctionDef

    def visit_ClassDef(self,node:ast.ClassDef):
        self.symbols.append({'name':node.name,'line':node.lineno,'kind':'class'}); self.symbol_stack.append(node.name); self.generic_visit(node); self.symbol_stack.pop()

    def visit_Import(self,node:ast.Import):
        for alias in node.names: self.imports.append({'module':alias.name,'line':node.lineno,'relative':False})
        self.generic_visit(node)

    def visit_ImportFrom(self,node:ast.ImportFrom):
        mod='.'*node.level+(node.module or '')
        self.imports.append({'module':mod,'line':node.lineno,'relative':node.level>0}); self.generic_visit(node)

    def visit_Constant(self,node:ast.Constant):
        if isinstance(node.value,str) and len(node.value)<=4000: self.strings.append({'value':node.value,'line':getattr(node,'lineno',1)})
        self.generic_visit(node)

    def visit_Attribute(self,node:ast.Attribute):
        if isinstance(node.ctx,ast.Load): self.fields.append({'name':node.attr,'line':getattr(node,'lineno',1),'form':'.'+node.attr,'symbol':self.symbol})
        self.generic_visit(node)

    def visit_Subscript(self,node:ast.Subscript):
        sl=node.slice
        if isinstance(sl,ast.Constant) and isinstance(sl.value,str): self.fields.append({'name':sl.value,'line':getattr(node,'lineno',1),'form':f"['{sl.value}']",'symbol':self.symbol})
        self.generic_visit(node)

    def visit_Call(self,node:ast.Call):
        name=dotted(node.func); method=''; client=''
        if isinstance(node.func,ast.Attribute) and node.func.attr.lower() in HTTP_METHODS:
            method=node.func.attr.upper(); client=dotted(node.func.value)
        elif name.endswith('.request') or name=='request':
            client=name.rsplit('.',1)[0] if '.' in name else name
            for kw in node.keywords:
                if kw.arg=='method':
                    val,literal=literal_string(kw.value); method=val.upper() if val else ''
        if (method or name.endswith('.request')) and node.args:
            target,literal=literal_string(node.args[0])
            if target:
                self.network.append({'file':self.path,'line':getattr(node,'lineno',1),'client':client or name,'method':method,'target':target,'literal':literal,'enclosing_symbol':self.symbol})
        self.generic_visit(node)


@dataclass
class JSToken:
    kind:str
    value:str
    line:int


class JSLexer:
    def tokenize(self,text:str) -> list[JSToken]:
        out=[]; i=0; line=1; n=len(text)
        while i<n:
            c=text[i]
            if c in ' \t\r': i+=1; continue
            if c=='\n': line+=1; i+=1; continue
            if c=='/' and i+1<n and text[i+1]=='/':
                i+=2
                while i<n and text[i]!='\n': i+=1
                continue
            if c=='/' and i+1<n and text[i+1]=='*':
                i+=2
                while i+1<n and not (text[i]=='*' and text[i+1]=='/'):
                    if text[i]=='\n': line+=1
                    i+=1
                i=min(n,i+2); continue
            if c in {'"',"'"}:
                quote=c; start_line=line; i+=1; chars=[]
                while i<n:
                    ch=text[i]
                    if ch=='\\' and i+1<n:
                        chars.append(text[i+1]); i+=2; continue
                    if ch==quote: i+=1; break
                    if ch=='\n': line+=1
                    chars.append(ch); i+=1
                out.append(JSToken('string',''.join(chars),start_line)); continue
            if c=='`':
                start_line=line; i+=1; chars=[]
                while i<n:
                    ch=text[i]
                    if ch=='\\' and i+1<n: chars.append(text[i+1]); i+=2; continue
                    if ch=='`': i+=1; break
                    if ch=='\n': line+=1
                    if ch=='$' and i+1<n and text[i+1]=='{':
                        chars.append('{}'); i+=2; depth=1
                        while i<n and depth:
                            if text[i]=='{': depth+=1
                            elif text[i]=='}': depth-=1
                            if text[i]=='\n': line+=1
                            i+=1
                        continue
                    chars.append(ch); i+=1
                out.append(JSToken('template',''.join(chars),start_line)); continue
            if c.isalpha() or c in '_$':
                start=i; start_line=line; i+=1
                while i<n and (text[i].isalnum() or text[i] in '_$'): i+=1
                out.append(JSToken('id',text[start:i],start_line)); continue
            if c.isdigit():
                start=i; start_line=line; i+=1
                while i<n and (text[i].isalnum() or text[i] in '._'): i+=1
                out.append(JSToken('number',text[start:i],start_line)); continue
            out.append(JSToken('punct',c,line)); i+=1
        return out


class JSAnalyzer:
    def __init__(self,path:str,text:str):
        self.path=path; self.tokens=JSLexer().tokenize(text)

    def analyze(self) -> dict[str,Any]:
        t=self.tokens; imports=[]; fields=[]; strings=[]; symbols=[]; network=[]
        for tok in t:
            if tok.kind in {'string','template'} and len(tok.value)<=4000: strings.append({'value':tok.value,'line':tok.line})
        for i,tok in enumerate(t):
            # imports / require
            if tok.kind=='id' and tok.value=='from' and i+1<len(t) and t[i+1].kind=='string': imports.append({'module':t[i+1].value,'line':tok.line,'relative':t[i+1].value.startswith('.')})
            if tok.kind=='id' and tok.value=='require' and i+2<len(t) and t[i+1].value=='(' and t[i+2].kind=='string': imports.append({'module':t[i+2].value,'line':tok.line,'relative':t[i+2].value.startswith('.')})
            # functions / classes
            if tok.kind=='id' and tok.value in {'function','class'} and i+1<len(t) and t[i+1].kind=='id': symbols.append({'name':t[i+1].value,'line':tok.line,'kind':tok.value})
            # dot fields
            if tok.value=='.' and i+1<len(t) and t[i+1].kind=='id': fields.append({'name':t[i+1].value,'line':t[i+1].line,'form':'.'+t[i+1].value})
            if tok.value=='[' and i+2<len(t) and t[i+1].kind=='string' and t[i+2].value==']': fields.append({'name':t[i+1].value,'line':t[i+1].line,'form':f"['{t[i+1].value}']"})

            # fetch("/path", {method:"POST"})
            if tok.kind=='id' and tok.value=='fetch' and i+2<len(t) and t[i+1].value=='(' and t[i+2].kind in {'string','template'}:
                method='GET'
                for j in range(i+3,min(len(t),i+35)):
                    if t[j].kind=='id' and t[j].value=='method' and j+2<len(t) and t[j+1].value==':' and t[j+2].kind=='string': method=t[j+2].value.upper(); break
                network.append({'file':self.path,'line':tok.line,'client':'fetch','method':method,'target':t[i+2].value,'literal':t[i+2].kind=='string','enclosing_symbol':self._symbol_for(symbols,tok.line)})
            # axios.get("/path") or client.post(...)
            if tok.kind=='id' and i+4<len(t) and t[i+1].value=='.' and t[i+2].kind=='id' and t[i+2].value.lower() in HTTP_METHODS and t[i+3].value=='(' and t[i+4].kind in {'string','template'}:
                network.append({'file':self.path,'line':tok.line,'client':tok.value,'method':t[i+2].value.upper(),'target':t[i+4].value,'literal':t[i+4].kind=='string','enclosing_symbol':self._symbol_for(symbols,tok.line)})
        # add nearest symbol to fields
        for f in fields: f['symbol']=self._symbol_for(symbols,f['line'])
        return {'imports':imports,'fields':fields,'strings':strings,'symbols':symbols,'network':network}

    def _symbol_for(self,symbols:list[dict[str,Any]],line:int) -> str:
        candidates=[s for s in symbols if s['line']<=line]
        return max(candidates,key=lambda s:s['line'])['name'] if candidates else ''


class RepositoryService:
    def __init__(self, repo_dir: Path | None = None):
        self.repo_dir = Path(repo_dir or settings.repo_dir)
        self.repo_dir.mkdir(parents=True, exist_ok=True)

    def extract_and_index(self,repo_id:str,filename:str,data:bytes) -> tuple[Path,dict[str,Any]]:
        if len(data)>settings.max_upload_bytes: raise RepositoryError('Repository ZIP exceeds configured upload limit.')
        sha=hashlib.sha256(data).hexdigest(); root=self.repo_dir/repo_id
        if root.exists(): shutil.rmtree(root)
        root.mkdir(parents=True,exist_ok=True)
        warnings=[]; files=[]
        try:
            archive=zipfile.ZipFile(BytesIO(data))
        except zipfile.BadZipFile as exc: raise RepositoryError('Repository upload must be a valid ZIP archive.') from exc
        with archive:
            for info in archive.infolist():
                if info.is_dir(): continue
                path=PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts:
                    warnings.append(f'Skipped unsafe path {info.filename}'); continue
                if any(p in SKIP_PARTS for p in path.parts): continue
                if info.file_size>settings.max_repo_file_bytes:
                    warnings.append(f'Skipped oversized file {info.filename}'); continue
                if len(files)>=settings.max_repo_files:
                    warnings.append(f'File index capped at {settings.max_repo_files} files.'); break
                target=root.joinpath(*path.parts); target.parent.mkdir(parents=True,exist_ok=True)
                raw=archive.read(info); target.write_bytes(raw); files.append(str(path))
        index=self._index(root,files,warnings); index['sha256']=sha; index['filename']=filename
        return root,index

    def _index(self,root:Path,files:list[str],warnings:list[str]) -> dict[str,Any]:
        file_index={}; network=[]; languages={}
        for rel in files:
            path=root/rel; lang=self._language(path); languages[lang]=languages.get(lang,0)+1
            meta={'path':rel,'language':lang,'size':path.stat().st_size,'imports':[],'fields':[],'strings':[],'symbols':[]}
            if lang in ANALYZED_LANGUAGES:
                try: text=path.read_text(encoding='utf-8')
                except UnicodeDecodeError:
                    warnings.append(f'Skipped non-UTF8 source file {rel}'); file_index[rel]=meta; continue
                try:
                    if lang=='python':
                        visitor=PythonVisitor(rel); visitor.visit(ast.parse(text,filename=rel)); parsed={'imports':visitor.imports,'fields':visitor.fields,'strings':visitor.strings,'symbols':visitor.symbols,'network':visitor.network}
                    else: parsed=JSAnalyzer(rel,text).analyze()
                    for key in ('imports','fields','strings','symbols'): meta[key]=parsed[key]
                    network.extend(parsed['network'])
                except (SyntaxError,ValueError) as exc: warnings.append(f'Could not structurally parse {rel}: {type(exc).__name__}: {exc}')
            file_index[rel]=meta
        edges=self._import_edges(file_index)
        return {'files':file_index,'network_calls':network,'import_edges':edges,'languages':languages,'warnings':warnings}

    def _language(self,path:Path) -> str:
        if path.name=='Dockerfile': return 'dockerfile'
        return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(),'other')

    def _import_edges(self,file_index:dict[str,dict[str,Any]]) -> list[dict[str,str]]:
        paths=set(file_index); edges=[]
        for source,meta in file_index.items():
            for imp in meta.get('imports') or []:
                target=self._resolve_import(source,imp['module'],paths,meta.get('language',''))
                if target: edges.append({'source':source,'target':target,'raw':imp['module']})
        unique={(e['source'],e['target'],e['raw']):e for e in edges}
        return list(unique.values())

    def _resolve_import(self,source:str,module:str,paths:set[str],language:str) -> str|None:
        if language=='python':
            mod=module.lstrip('.')
            candidates=[mod.replace('.','/')+'.py',mod.replace('.','/')+'/__init__.py']
            # source-root and repository-root candidates
            src_dir=PurePosixPath(source).parent
            if module.startswith('.'):
                dots=len(module)-len(module.lstrip('.')); base=src_dir
                for _ in range(max(0,dots-1)): base=base.parent
                rest=module[dots:].replace('.','/')
                candidates=[str(base/(rest+'.py')),str(base/rest/'__init__.py')]
            for c in candidates:
                if c in paths: return c
                suffix_matches=[p for p in paths if p.endswith('/'+c) or p==c]
                if len(suffix_matches)==1: return suffix_matches[0]
        elif module.startswith('.'):
            base=PurePosixPath(source).parent/module
            normalized=str(PurePosixPath(os.path.normpath(str(base))))
            candidates=[normalized+ext for ext in ('.ts','.tsx','.js','.jsx','.svelte','.mjs')]+[str(PurePosixPath(normalized)/('index'+ext)) for ext in ('.ts','.tsx','.js','.jsx')]
            for c in candidates:
                if c in paths: return c
        return None
