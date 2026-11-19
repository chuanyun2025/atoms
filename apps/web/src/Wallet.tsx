import {useEffect,useState,type FormEvent} from "react";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {Coins,Copy,Gift,KeyRound,LoaderCircle,ShieldAlert} from "lucide-react";
import {api,date,type Project,type PublicGuardrails} from "./api";
import Modal from "./Modal";

export type Wallet={visitor_id:string;balance:string;held:string;available:string;spent:string;available_units:number;welcome_credits:number;credits_per_yuan:number;pricing:{input_per_million:number;output_per_million:number};guardrails?:PublicGuardrails};
type Ledger={id:string;kind:string;amount:string;input_tokens:number;output_tokens:number;created_at:number};
type Pending={id:string;status:string;reserved:string;created_at:number;error_code:string|null};
type Transactions={items:Ledger[];pending:Pending[];next_before:number|null};

const walletOpenListeners=new Set<()=>void>();
export function openWalletDialog(){
  const first=walletOpenListeners.values().next().value;
  if(first)first();
}

export function useWallet(live=false){
  const client=useQueryClient();
  return useQuery({
    queryKey:["wallet"],
    queryFn:()=>api<Wallet>("/wallet"),
    refetchInterval:()=>{
      if(live)return 5000;
      const projects=client.getQueryData<{items:Project[]}>(["projects"]);
      return projects?.items.some(project=>project.active_run_id)?5000:false;
    },
  });
}
const short=(value:string)=>value.includes(".")?value.replace(/\.?0+$/,""):value;
const passcodeLabels:Record<string,string>={active:"生效中",exhausted:"额度已用完",expired:"已过期",revoked:"已吊销"};
const ledgerLabels:Record<string,string>={
  welcome:"新用户赠送",
  passcode_grant:"体验口令额度补充",
  release:"预授权已释放",
  consumption:"模型用量消费",
  media_consumption:"视频生成消费",
  balance_adjustment:"余额调整",
};

function WalletDialog({onClose}:{onClose:()=>void}){
  const queryClient=useQueryClient();
  const {data:wallet,error}=useWallet(true),[before,setBefore]=useState<number|null>(null),[copied,setCopied]=useState(false);
  const [passcodeInput,setPasscodeInput]=useState(""),[passcodeBusy,setPasscodeBusy]=useState(false),[passcodeMsg,setPasscodeMsg]=useState(""),[passcodeErr,setPasscodeErr]=useState("");
  const {data:ledger,isLoading,error:ledgerError}=useQuery({queryKey:["credit-transactions",before],queryFn:()=>api<Transactions>("/wallet/transactions"+(before?"?before="+before:"")),refetchInterval:5000});
  const guardrails=wallet?.guardrails;
  const bound=guardrails?.passcode;

  async function submitPasscode(event:FormEvent){
    event.preventDefault();
    if(!passcodeInput.trim()||passcodeBusy)return;
    setPasscodeBusy(true);setPasscodeErr("");setPasscodeMsg("");
    try{
      const updated=await api<Wallet>("/wallet/passcode","POST",{code:passcodeInput.trim()});
      queryClient.setQueryData(["wallet"],updated);
      await queryClient.invalidateQueries({queryKey:["capabilities"]});
      await queryClient.invalidateQueries({queryKey:["credit-transactions"]});
      setPasscodeInput("");
      setPasscodeMsg("体验口令已激活："+(updated.guardrails?.passcode?.label||"专属通行证"));
    }catch(err){
      setPasscodeErr((err as Error).message);
    }finally{
      setPasscodeBusy(false);
    }
  }

  async function detachPasscode(){
    if(passcodeBusy)return;
    setPasscodeBusy(true);setPasscodeErr("");setPasscodeMsg("");
    try{
      const updated=await api<Wallet>("/wallet/passcode/detach","POST",{});
      queryClient.setQueryData(["wallet"],updated);
      await queryClient.invalidateQueries({queryKey:["capabilities"]});
      setPasscodeMsg("已解除当前体验口令绑定");
    }catch(err){
      setPasscodeErr((err as Error).message);
    }finally{
      setPasscodeBusy(false);
    }
  }

  return <Modal title="我的积分" onClose={onClose}>
    {error&&<div className="inline-error">{error.message}</div>}
    {wallet?<><div className="wallet-user"><span>匿名用户 ID</span><code data-testid="visitor-id">{wallet.visitor_id}</code><button aria-label="复制用户 ID" onClick={()=>{navigator.clipboard.writeText(wallet.visitor_id).then(()=>setCopied(true)).catch(()=>setCopied(false))}}>{copied?"已复制":<Copy size={14}/>}</button></div>
      <div className="wallet-totals"><div><small>可用积分</small><strong data-testid="wallet-available">{wallet.available}</strong></div><div><small>总余额</small><strong>{wallet.balance}</strong></div><div><small>累计消费</small><strong>{wallet.spent}</strong></div></div>
      <p className="wallet-held">预授权冻结：{wallet.held} 积分<span>调用完成后按实际用量结算，未使用的预授权自动释放。</span></p>
      {guardrails?.daily_budget_enabled&&<div className="wallet-gift" data-testid="public-budget-banner">
        <ShieldAlert size={19}/>
        <div>
          <strong>{guardrails.daily_budget_reached?"今日公共体验额度已达上限":"全站公共体验池剩余 "+short(guardrails.daily_remaining_credits)+" / "+short(guardrails.daily_budget_credits)+" 积分"}</strong>
          <span>预计重置：{guardrails.reset_label} · 浏览作品、修改已有源码和导出不受影响</span>
        </div>
      </div>}
      <div className="wallet-passcode-box">
        <div className="wallet-passcode-header"><KeyRound size={16}/><strong>体验口令 · 专属通行证</strong></div>
        {bound&&<div className="wallet-passcode-bound" data-testid="bound-passcode">
          <div>
            <strong>{bound.label}（{passcodeLabels[bound.status]??bound.status}）</strong>
            <span>专项剩余 {short(bound.remaining)} / {short(bound.budget)} 积分{bound.bypass_daily_budget?" · 豁免公共日限额":""}{bound.allow_video?" · 已解锁视频生成":""}</span>
          </div>
          <button type="button" className="plain-button" disabled={passcodeBusy} onClick={()=>void detachPasscode()}>解除绑定</button>
        </div>}
        <form className="wallet-passcode-form" onSubmit={submitPasscode}>
          <input aria-label="输入体验口令" placeholder="输入体验口令（如 ATOMS-XXXX-XXXX）解锁专属额度与视频" value={passcodeInput} maxLength={64} disabled={passcodeBusy} onChange={e=>setPasscodeInput(e.target.value)}/>
          <button type="submit" className="plain-button" disabled={!passcodeInput.trim()||passcodeBusy}>{passcodeBusy?"校验中…":"兑换口令"}</button>
        </form>
        {passcodeMsg&&<p className="positive" role="status">{passcodeMsg}</p>}
        {passcodeErr&&<p className="inline-error" role="alert">{passcodeErr}</p>}
      </div>
      <div className="wallet-gift"><Gift size={19}/><div><strong>新用户赠送 {wallet.welcome_credits} 积分</strong><span>{wallet.credits_per_yuan} 积分 = 1 元 · {wallet.welcome_credits} 积分相当于 {wallet.welcome_credits / wallet.credits_per_yuan} 元使用额度</span></div></div>
      <div className="wallet-pricing"><span>输入 1,000,000 token <strong>{wallet.pricing.input_per_million} 积分</strong></span><span>输出 1,000,000 token <strong>{wallet.pricing.output_per_million} 积分</strong></span></div>
      <p className="wallet-explanation">生成、修改和自动修复按每次模型调用的实际用量向上取整，校验失败但已产生的用量也会计费。视频生成成功后按条固定计费。当前无需登录，无充值或支付功能。</p></>:<div className="wallet-loading"><LoaderCircle className="spin" size={18}/>正在读取积分</div>}
    <h3 className="wallet-ledger-title">积分明细</h3>
    {ledger?.pending.map(call=><div className="wallet-pending" key={call.id}><span>{call.status==="uncertain"?"待核对用量":"生成中 · 预授权"}<small>{date(call.created_at)}</small></span><strong>冻结 {call.reserved} 积分</strong>{call.status==="uncertain"&&<p>供应商未返回可确认的用量，维护者核对后结算或释放。调用 ID：<code>{call.id}</code></p>}</div>)}
    {isLoading&&<p className="muted">加载明细…</p>}{ledgerError&&<p className="inline-error">{ledgerError.message}</p>}
    <div className="wallet-ledger">{ledger?.items.map(item=>{
      const added=Number(item.amount)>0;
      return <div className="wallet-entry" key={item.id}>
        <div><strong>{ledgerLabels[item.kind]??"积分流水"}</strong><small>{date(item.created_at)}</small>{item.kind==="consumption"&&<span>输入 {item.input_tokens.toLocaleString()} · 输出 {item.output_tokens.toLocaleString()} token</span>}</div>
        <b className={added?"positive":""}>{added?"+":""}{item.amount}</b>
      </div>;
    })}</div>
    <div className="wallet-pagination">{before&&<button onClick={()=>setBefore(null)}>回到最新</button>}{ledger?.next_before&&<button onClick={()=>setBefore(ledger.next_before)}>更早记录</button>}</div>
    <p className="wallet-explanation">同一浏览器沿用该 ID。清除 Cookie 或换浏览器将成为另一位匿名用户，原项目和余额无法自动找回。</p>
  </Modal>
}
export default function WalletButton({compact=false}:{compact?:boolean}){
  const {data,error}=useWallet(),[open,setOpen]=useState(false);
  useEffect(()=>{
    const opener=()=>setOpen(true);
    walletOpenListeners.add(opener);
    return()=>{walletOpenListeners.delete(opener)};
  },[]);
  return <><button className={"wallet-button "+(compact?"compact":"")} aria-label="积分余额" onClick={()=>setOpen(true)} title={data?"可用 "+data.available+" 积分 · 总余额 "+data.balance:"查看积分"}><Coins size={16}/><span data-testid="credit-balance">{data?short(data.available):error?"重试":"…"}</span><small>积分</small></button>{open&&<WalletDialog onClose={()=>setOpen(false)}/>}</>
}
