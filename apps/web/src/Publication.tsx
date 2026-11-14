import {useEffect,useMemo,useState} from "react";
import {useParams} from "react-router-dom";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {ExternalLink,Globe2,Link2,LoaderCircle} from "lucide-react";
import {api,ApiError} from "./api";
import Modal from "./Modal";
import Preview from "./Preview";
import "./publication.css";

type Publication={path:string;published:boolean;version_id:string;version_number:number;previous_version_number:number|null;revision:number};
type PublicationResult={publication:Publication|null};
type Action="publish"|"rollback"|"unpublish";
type PublicTicket={title:string;url:string;instance_id:string;channel_nonce:string;read_only:boolean};
const ignoreSaved=()=>{};

export function PublishButton({pid,versionId,versionNumber,readOnly}:{pid:string;versionId:string;versionNumber?:number;readOnly?:boolean}){
  const [open,setOpen]=useState(false);
  return <>
    <button type="button" className="publish-button" onClick={()=>setOpen(true)}><Globe2 size={15}/>发布</button>
    {open&&<PublishDialog pid={pid} versionId={versionId} versionNumber={versionNumber} readOnly={readOnly} onClose={()=>setOpen(false)}/>}
  </>;
}

function PublishDialog({pid,versionId,versionNumber,readOnly,onClose}:{pid:string;versionId:string;versionNumber?:number;readOnly?:boolean;onClose:()=>void}){
  const client=useQueryClient();
  const queryKey=["publication",pid];
  const endpoint="/projects/"+pid+"/publication";
  const {data,isPending,isError,refetch}=useQuery({queryKey,queryFn:()=>api<PublicationResult>(endpoint)});
  const [pending,setPending]=useState<Action>();
  const [confirm,setConfirm]=useState<"rollback"|"unpublish">();
  const [notice,setNotice]=useState("");
  const [error,setError]=useState("");
  const publication=data?.publication;
  const live=!!publication?.published;
  const link=publication?new URL(publication.path,location.origin).href:"";
  const sameVersion=live&&publication.version_id===versionId;
  async function change(action:Action){
    setPending(action);setError("");setNotice("");
    try{
      const result=await api<PublicationResult>(endpoint,"PUT",{
        action,expected_revision:publication?.revision??0,...(action==="publish"?{version_id:versionId}:{}),
      });
      client.setQueryData(queryKey,result);
      setConfirm(undefined);
      setNotice(action==="unpublish"?"已下架":action==="rollback"?"已切换发布版本":"发布成功");
    }catch(e){
      setError((e as Error).message);
      if(e instanceof ApiError&&e.status===409)await refetch();
    }finally{setPending(undefined)}
  }
  async function copy(){
    try{await navigator.clipboard.writeText(link);setNotice("链接已复制")}
    catch{setNotice("可选中地址并手动复制")}
  }
  return <Modal title="发布作品" onClose={()=>{if(!pending)onClose()}}>
    {isPending?<p role="status">正在读取发布状态…</p>:isError?<div className="publish-error" role="alert">无法读取发布状态。 <button type="button" onClick={()=>void refetch()}>重试</button></div>:<>
      <p className="publish-state">{live?"已发布 v"+publication.version_number:publication?"已下架":"尚未发布"}</p>
      {live&&<div className="publish-link">
        <input aria-label="公开链接" readOnly value={link} onFocus={event=>event.currentTarget.select()}/>
        <button type="button" onClick={()=>void copy()}><Link2 size={15}/>复制链接</button>
        <a href={publication.path} target="_blank" rel="noopener noreferrer"><ExternalLink size={15}/>打开作品</a>
      </div>}
      {!sameVersion&&<p>将发布 v{versionNumber??"当前版本"}。有链接的人都可以打开作品。</p>}
      {!sameVersion&&<p className="muted">作品里的文字和示例数据会公开。工作台对话和存档留在项目内。</p>}
      {readOnly&&<p className="muted">维护期间暂停发布操作。</p>}
      {confirm&&<p>{confirm==="rollback"?"将公开链接切换到 v"+publication?.previous_version_number+"？":"下架后，访客打开链接会看到下架提示。"}</p>}
      {error&&<p className="publish-error" role="alert">{error}</p>}
      {notice&&<p className="publish-notice" role="status">{notice}</p>}
      <div className="publish-actions">
        {confirm?<><button type="button" className="plain-button" disabled={!!pending} onClick={()=>setConfirm(undefined)}>取消</button>
          <button type="button" className="create-button" disabled={!!pending||readOnly} onClick={()=>void change(confirm)}>{confirm==="rollback"?"确认回滚":"确认下架"}</button></>:
          <>
            {live&&<button type="button" className="plain-button" disabled={!!pending||readOnly} onClick={()=>setConfirm("unpublish")}>下架</button>}
            {live&&publication.previous_version_number&&<button type="button" className="plain-button" disabled={!!pending||readOnly} onClick={()=>setConfirm("rollback")}>回滚到 v{publication.previous_version_number}</button>}
            {!sameVersion&&<button type="button" className="create-button" disabled={!!pending||readOnly||!versionNumber} onClick={()=>void change("publish")}>
              {pending==="publish"?<LoaderCircle className="spin" size={15}/>:live?"更新发布到 v"+versionNumber:"发布 v"+versionNumber}
            </button>}
          </>}
      </div>
    </>}
  </Modal>;
}

export default function PublishedPage(){
  const {slug=""}=useParams();
  const {data,error,isPending,refetch}=useQuery({
    queryKey:["public-ticket",slug],
    queryFn:async({signal}):Promise<PublicTicket>=>{
      const response=await fetch("/api/v1/publications/"+encodeURIComponent(slug),{credentials:"omit",cache:"no-store",signal});
      if(!response.ok)throw new ApiError(response.status===410?"这个作品已下架":response.status===404?"找不到这个作品":"暂时无法打开作品",response.status,"publication_unavailable");
      return response.json();
    },
    retry:false,refetchOnWindowFocus:false,
  });
  const publication=useMemo(()=>data?{slug,ticket:data}:undefined,[slug,data]);
  useEffect(()=>{
    if(!data)return;
    const title=document.title;
    document.title=data.title;
    return ()=>{document.title=title};
  },[data]);
  if(isPending)return <main className="publication-message" role="status"><LoaderCircle className="spin" size={22}/>正在打开作品</main>;
  if(error)return <main className="publication-message"><Globe2 size={28}/><h1>{error.message}</h1>
    {(!(error instanceof ApiError)||error.status>=500)&&<button type="button" className="publish-button" onClick={()=>void refetch()}>重试</button>}
  </main>;
  return <main className="publication-page" aria-label={data?.title}>
    {publication&&<Preview publication={publication} reload={0} phone={false} onSaved={ignoreSaved}/>}
  </main>;
}
