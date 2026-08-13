from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from core.config import settings
from schemas.models import ToolCapability, ValidationResult


class ValidationService:
    def __init__(self,force_local_execution:bool=False):
        self.force_local_execution=force_local_execution

    def run(self,root:Path,tools:list[ToolCapability],allow_trusted_execution:bool) -> list[ValidationResult]:
        results=[]
        runner_enabled=self.force_local_execution or os.getenv('AEA_ALLOW_LOCAL_EXECUTION','0')=='1'
        for tool in tools:
            if tool.safety=='static':
                results.append(ValidationResult(tool_id=tool.id,status='passed',command=tool.command,evidence=tool.reason)); continue
            if not tool.detected:
                results.append(ValidationResult(tool_id=tool.id,status='unavailable',command=tool.command,evidence=tool.reason)); continue
            if not allow_trusted_execution:
                results.append(ValidationResult(tool_id=tool.id,status='skipped',command=tool.command,evidence='Skipped: repository execution was not explicitly authorized.')); continue
            if not runner_enabled:
                results.append(ValidationResult(tool_id=tool.id,status='skipped',command=tool.command,evidence='Skipped: local project execution is disabled by deployment policy. Set AEA_ALLOW_LOCAL_EXECUTION=1 only inside an isolated runner.')); continue
            results.append(self._exec(root,tool))
        return results

    def _exec(self,root:Path,tool:ToolCapability) -> ValidationResult:
        env={'PATH':os.environ.get('PATH',''),'HOME':os.environ.get('HOME','/tmp'),'CI':'1','NO_COLOR':'1','PYTHONUNBUFFERED':'1'}
        started=time.monotonic()
        try:
            proc=subprocess.run(tool.command,cwd=root,env=env,capture_output=True,text=True,timeout=settings.execution_timeout_seconds,shell=False)
            duration=int((time.monotonic()-started)*1000); status='passed' if proc.returncode==0 else 'failed'
            return ValidationResult(tool_id=tool.id,status=status,command=tool.command,exit_code=proc.returncode,duration_ms=duration,stdout=proc.stdout[-12000:],stderr=proc.stderr[-12000:],evidence=f'{tool.name} exited {proc.returncode} in {duration} ms.')
        except subprocess.TimeoutExpired as exc:
            duration=int((time.monotonic()-started)*1000)
            return ValidationResult(tool_id=tool.id,status='timeout',command=tool.command,duration_ms=duration,stdout=(exc.stdout or '')[-12000:] if isinstance(exc.stdout,str) else '',stderr=(exc.stderr or '')[-12000:] if isinstance(exc.stderr,str) else '',evidence=f'{tool.name} exceeded {settings.execution_timeout_seconds}s timeout.')
