const API_BASE=(import.meta.env.VITE_API_BASE_URL??'http://localhost:8000/api/v1').replace(/\/$/,'');
const ORIGIN=API_BASE.replace(/\/api\/v1$/,'');
export type Contract={contract_id:string;source_name:string;sha256:string;title:string;version:string;openapi_version:string;operation_count:number;warnings:string[]};
export type Repository={repository_id:string;filename:string;sha256:string;file_count:number;languages:Record<string,number>;network_call_count:number;import_edge_count:number;warnings:string[]};
export type Change={id:string;severity:string;category:string;operation_key:string;summary:string;old:any;new:any;confidence:string;migration_hint:string};
export type Impact={change_id:string;file:string;line:number;symbol:string;match_type:string;confidence:string;evidence:string};
export type ImpactedFile={file:string;direct_impacts:number;propagated_distance:number;reasons:string[]};
export type Patch={id:string;file:string;line:number|null;kind:string;old_text:string;new_text:string;confidence:string;reason:string;change_ids:string[];requires_human_approval:boolean};
export type Tool={id:string;name:string;capability:string;command:string[];safety:string;detected:boolean;reason:string};
export type Validation={tool_id:string;status:string;command:string[];exit_code:number|null;duration_ms:number;stdout:string;stderr:string;evidence:string};
export type Assurance={analysis_id:string;created_at:string;old_contract:Contract;new_contract:Contract;repository:Repository;changes:Change[];breaking_change_count:number;usage_impacts:Impact[];impacted_files:ImpactedFile[];patch_plan:Patch[];tool_plan:Tool[];validation:Validation[];release_gate:string;release_gate_reasons:string[];evidence_summary:string[];limitations:string[];metadata:Record<string,unknown>};
export type PatchResult={artifact_id:string;applied:number;skipped:number;outcomes:{patch_id:string;status:string;detail:string}[];unified_diff:string;download_path:string};
export type GitHubPR={pull_number:number;pull_url:string;branch_name:string;base_branch:string;commit_sha:string;artifact_id:string;applied_patch_ids:string[]};
async function json<T>(path:string,init?:RequestInit):Promise<T>{const res=await fetch(`${API_BASE}${path}`,init);const text=await res.text();const body=text?JSON.parse(text):null;if(!res.ok)throw new Error(body?.detail??`HTTP ${res.status}`);return body as T}
async function upload<T>(path:string,file:File):Promise<T>{const form=new FormData();form.append('file',file);return json<T>(path,{method:'POST',body:form})}
export const api={
 uploadContract:(file:File)=>upload<Contract>('/contracts/upload',file),
 uploadRepository:(file:File)=>upload<Repository>('/repositories/upload',file),
 analyze:(oldId:string,newId:string,repoId:string,allow:boolean)=>json<Assurance>('/assurance',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({old_contract_id:oldId,new_contract_id:newId,repository_id:repoId,allow_trusted_execution:allow,propagate_import_impacts:true})}),
 apply:(analysisId:string,ids:string[])=>json<PatchResult>(`/analyses/${analysisId}/patches/apply`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({approved_patch_ids:ids,human_approved:true})}),
 publishGitHubPR:(analysisId:string,input:{owner:string;repo:string;base_branch:string;branch_name:string;title:string;body:string;approved_patch_ids:string[]})=>json<GitHubPR>(`/analyses/${analysisId}/github/pr`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...input,human_approved:true})}),
 artifactUrl:(path:string)=>`${ORIGIN}${path}`
};
