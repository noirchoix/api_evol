from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from schemas.models import ToolCapability


class ToolRegistry:
    def plan(self,root:Path,index:dict[str,Any]) -> list[ToolCapability]:
        files=set(index.get('files') or {}); languages=index.get('languages') or {}; tools=[]
        tools.append(ToolCapability(id='canonical_contract_diff',name='Canonical Contract Diff',capability='semantic API contract comparison',safety='static',detected=True,reason='Built-in deterministic analyzer.'))
        tools.append(ToolCapability(id='repository_structural_index',name='Repository Structural Index',capability='language-aware source, import, field and network-call indexing',safety='static',detected=True,reason='Built-in Python AST and JS/TS lexical structural analyzers.'))
        if languages.get('python'):
            tools.extend([
                self._cmd('ruff','Ruff','Python lint/static validation',['ruff','check','.'],root,reason='Python sources detected.'),
                self._cmd('pytest','Pytest','Python regression tests',['pytest','-q'],root,reason='Python sources detected.'),
                self._cmd('mypy','mypy','Python type checking',['mypy','.'],root,reason='Python sources detected.'),
                self._cmd('pyright','Pyright','Python type checking',['pyright'],root,reason='Python sources detected.'),
            ])
        package=self._package_json(root,files)
        if package:
            scripts=package.get('scripts') or {}
            for script,cap in [('check','frontend/static checks'),('test','JavaScript/TypeScript tests'),('build','production build')]:
                if script in scripts:
                    tools.append(ToolCapability(id=f'npm_{script}',name=f'npm {script}',capability=cap,command=['npm','run',script],safety='executes_project_code',detected=shutil.which('npm') is not None,reason=f'package.json defines script {script!r}.'))
        return tools

    def _cmd(self,id:str,name:str,capability:str,command:list[str],root:Path,reason:str) -> ToolCapability:
        detected=shutil.which(command[0]) is not None
        return ToolCapability(id=id,name=name,capability=capability,command=command,safety='executes_project_code',detected=detected,reason=reason if detected else f'{reason} Executable {command[0]!r} is not installed in the runtime.')

    def _package_json(self,root:Path,files:set[str]) -> dict[str,Any]|None:
        candidates=[f for f in files if f.endswith('package.json') and 'node_modules/' not in f]
        if not candidates: return None
        preferred=sorted(candidates,key=lambda x:(x.count('/'),len(x)))[0]
        try: return json.loads((root/preferred).read_text(encoding='utf-8'))
        except Exception: return None
