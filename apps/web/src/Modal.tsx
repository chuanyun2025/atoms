import {useEffect,useRef,type ReactNode} from "react";
import {createPortal} from "react-dom";
import {X} from "lucide-react";
export default function Modal({title,onClose,children,wide=false}:{title:string;onClose:()=>void;children:ReactNode;wide?:boolean}){
  const panel=useRef<HTMLElement>(null);
  const dismiss=useRef(onClose);
  dismiss.current=onClose;
  useEffect(()=>{
    const opener=document.activeElement;
    const overflow=document.body.style.overflow;
    document.body.style.overflow="hidden";
    panel.current?.querySelector("button")?.focus({preventScroll:true});
    function listener(event:KeyboardEvent) {
      if (event.key==="Escape" && !event.defaultPrevented) {
        event.preventDefault();
        dismiss.current();
      }
      if (event.key!=="Tab" || !panel.current) return;
      const targets=Array.from(panel.current.querySelectorAll<HTMLElement>(
        'button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]',
      )).filter(element=>element.getClientRects().length>0);
      if (!targets.length) {
        event.preventDefault();
        panel.current.focus();
        return;
      }
      const first=targets[0],last=targets[targets.length-1],active=document.activeElement;
      if (!panel.current.contains(active) || (event.shiftKey && active===first) || (!event.shiftKey && active===last)) {
        event.preventDefault();
        (event.shiftKey?last:first).focus();
      }
    }
    document.addEventListener("keydown",listener);
    return ()=>{
      document.removeEventListener("keydown",listener);
      document.body.style.overflow=overflow;
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({preventScroll:true});
    };
  },[]);
  return createPortal(<div className="modal-backdrop" onClick={onClose}>
    <section ref={panel} tabIndex={-1} className={"modal"+(wide?" modal-wide":"")} role="dialog" aria-modal="true" aria-label={title} onClick={event=>event.stopPropagation()}>
      <div className="modal-title"><h2>{title}</h2><button className="icon-button" aria-label="关闭" onClick={onClose}><X size={19}/></button></div>
      {children}
    </section>
  </div>,document.body);
}
