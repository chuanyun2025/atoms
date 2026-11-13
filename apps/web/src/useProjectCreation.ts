import {useEffect,useRef,useState} from "react";
import {useQueryClient} from "@tanstack/react-query";
import {useNavigate} from "react-router-dom";
import {api,key,type Capabilities,type Project,type ProjectKind} from "./api";

type CreationRequest = {
  kind: ProjectKind;
  prompt: string;
  draftKey: string;
  title?: string;
  slideTemplateId?: string;
  video?: {dataUrl:string;duration:number;audio:boolean};
};

export function useProjectCreation(capabilities?: Capabilities) {
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const submission = useRef(false);
  const mounted = useRef(false);
  const navigate = useNavigate();
  const client = useQueryClient();

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function create({kind,prompt,draftKey,title,slideTemplateId,video}: CreationRequest) {
    const request = prompt.trim();
    if (!request || submission.current || capabilities?.read_only) return;
    submission.current = true;
    setBusy(true);
    setError("");

    try {
      if(kind==="video"&&!video){
        sessionStorage.setItem("atoms:studio-draft:video",request);
        if(mounted.current)navigate("/video");
        return;
      }
      const status = capabilities || await api<Capabilities>("/capabilities");
      if(kind==="video"&&!status.video_configured) throw new Error("视频服务尚未连接，请联系管理员");
      const createKey = ["atoms:create-key",kind,slideTemplateId].filter(Boolean).join(":");
      const clientKey = sessionStorage.getItem(createKey) || key();
      sessionStorage.setItem(createKey,clientKey);
      const project = await api<Project>("/projects","POST",{
        client_key:clientKey,
        title:title || request.slice(0,35),
        kind,
        ...(slideTemplateId ? {slide_template_id:slideTemplateId} : {}),
      });

      const videoInput=video?.dataUrl?await api<{id:string}>("/projects/"+project.id+"/media/images","POST",{data_url:video.dataUrl}):undefined;
      sessionStorage.removeItem(createKey);
      const projectDraftKey = "atoms:draft:"+project.id;
      sessionStorage.setItem(projectDraftKey,request);
      void client.invalidateQueries({queryKey:["projects"]});

      if ((kind==="video"?status.video_configured:status.model_configured) && status.worker_available && !status.read_only) {
        const pending = {id:key(),body:{prompt:request,expected_revision:project.revision,base_version_id:project.current_version_id,
          ...(video?{video:{image_asset_id:videoInput?.id,duration:video.duration,audio:video.audio}}:{})}};
        const pendingKey = "atoms:pending:"+project.id;
        sessionStorage.setItem(pendingKey,JSON.stringify(pending));
        try {
          await api("/projects/"+project.id+"/runs","POST",pending.body,{"Idempotency-Key":pending.id});
          sessionStorage.removeItem(pendingKey);
          sessionStorage.removeItem(projectDraftKey);
        } catch (err) {
          sessionStorage.setItem("atoms:startup-error:"+project.id,(err as Error).message);
        }
      }

      if (sessionStorage.getItem(draftKey)?.trim()===request) sessionStorage.removeItem(draftKey);
      if (mounted.current) navigate("/projects/"+project.id);
    } catch (err) {
      if (mounted.current) setError((err as Error).message);
    } finally {
      submission.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return {create,busy,error};
}
