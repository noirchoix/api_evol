from __future__ import annotations

import difflib
import hashlib
import shutil
import zipfile
from pathlib import Path

from schemas.models import PatchApplyOutcome, PatchApplyResponse, PatchOperation


class PatchService:
    def __init__(self,artifact_root:Path):
        self.artifact_root=artifact_root; self.artifact_root.mkdir(parents=True,exist_ok=True)

    def apply(self,analysis_id:str,repo_root:Path,patches:list[PatchOperation],approved_ids:list[str]) -> PatchApplyResponse:
        approved=set(approved_ids); artifact_id='art_'+hashlib.sha1((analysis_id+'|'+','.join(sorted(approved))).encode()).hexdigest()[:14]
        work=self.artifact_root/artifact_id
        if work.exists(): shutil.rmtree(work)
        shutil.copytree(repo_root,work)
        outcomes=[]; diffs=[]; applied=0
        for patch in patches:
            if patch.id not in approved: continue
            if patch.kind not in {'replace_path','replace_field','replace_text'} or not patch.old_text or not patch.new_text:
                outcomes.append(PatchApplyOutcome(patch_id=patch.id,status='skipped',detail='Patch is manual-only or lacks a deterministic replacement.')); continue
            target=work/patch.file
            if not target.exists(): outcomes.append(PatchApplyOutcome(patch_id=patch.id,status='failed',detail='Target file does not exist.')); continue
            try: before=target.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                outcomes.append(PatchApplyOutcome(patch_id=patch.id,status='failed',detail='Target file is not UTF-8 text.')); continue
            lines=before.splitlines(keepends=True); idx=(patch.line or 1)-1
            if idx<0 or idx>=len(lines): outcomes.append(PatchApplyOutcome(patch_id=patch.id,status='failed',detail='Target line is outside the file.')); continue
            if lines[idx].count(patch.old_text)!=1:
                outcomes.append(PatchApplyOutcome(patch_id=patch.id,status='skipped',detail='Exact replacement is not unique on the evidence line; manual review required.')); continue
            lines[idx]=lines[idx].replace(patch.old_text,patch.new_text,1); after=''.join(lines); target.write_text(after,encoding='utf-8'); applied+=1
            outcomes.append(PatchApplyOutcome(patch_id=patch.id,status='applied',detail=f'Replaced {patch.old_text!r} with {patch.new_text!r} on evidence line {patch.line}.'))
            diffs.extend(difflib.unified_diff(before.splitlines(),after.splitlines(),fromfile='a/'+patch.file,tofile='b/'+patch.file,lineterm=''))
        zip_path=self.artifact_root/f'{artifact_id}.zip'
        with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
            for file in work.rglob('*'):
                if file.is_file(): z.write(file,file.relative_to(work))
            z.writestr('API_EVOLUTION_PATCH.diff','\n'.join(diffs)+'\n')
        return PatchApplyResponse(artifact_id=artifact_id,applied=applied,skipped=sum(o.status!='applied' for o in outcomes),outcomes=outcomes,unified_diff='\n'.join(diffs),download_path=f'/api/v1/artifacts/{artifact_id}.zip')
