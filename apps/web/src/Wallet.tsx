import {useState} from "react";
import {useQuery,useQueryClient} from "@tanstack/react-query";
import {Coins,Copy,Gift,LoaderCircle} from "lucide-react";
import {api,date,type Project} from "./api";
import Modal from "./Modal";

export type Wallet={visitor_id:string;balance:string;held:string;available:string;spent:string;available_units:number;welcome_credits:number;credits_per_yuan:number;pricing:{input_per_million:number;output_per_million:number}};
type Ledger={id:string;kind:string;amount:string;input_tokens:number;output_tokens:number;created_at:number};
type Pending={id:string;status:string;reserved:string;created_at:number;error_code:string|null};
type Transactions={items:Ledger[];pending:Pending[];next_before:number|null};
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
function WalletDialog({onClose}:{onClose:()=>void}){
  const {data:wallet,error}=useWallet(true),[before,setBefore]=useState<number|null>(null),[copied,setCopied]=useState(false);
  const {data:ledger,isLoading,error:ledgerError}=useQuery({queryKey:["credit-transactions",before],queryFn:()=>api<Transactions>("/wallet/transactions"+(before?"?before="+before:"")),refetchInterval:5000});
  return <Modal title="我的积分" onClose={onClose}>
    {error&&<div className="inline-error">{error.message}</div>}
    {wallet?<><div className="wallet-user"><span>匿名用户 ID</span><code data-testid="visitor-id">{wallet.visitor_id}</code><button aria-label="复制用户 ID" onClick={()=>{navigator.clipboard.writeText(wallet.visitor_id).then(()=>setCopied(true)).catch(()=>setCopied(false))}}>{copied?"已复制":<Copy size={14}/>}</button></div>
      <div className="wallet-totals"><div><small>可用积分</small><strong data-testid="wallet-available">{wallet.available}</strong></div><div><small>总余额</small><strong>{wallet.balance}</strong></div><div><small>累计消费</small><strong>{wallet.spent}</strong></div></div>
      <p className="wallet-held">预授权冻结：{wallet.held} 积分<span>调用完成后按实际用量结算，未使用的预授权自动释放。</span></p>
      <div className="wallet-gift"><Gift size={19}/><div><strong>新用户赠送 {wallet.welcome_credits} 积分</strong><span>{wallet.credits_per_yuan} 积分 = 1 元 · 500 积分相当于 50 元使用额度</span></div></div>
      <div className="wallet-pricing"><span>输入 1,000,000 token <strong>{wallet.pricing.input_per_million} 积分</strong></span><span>输出 1,000,000 token <strong>{wallet.pricing.output_per_million} 积分</strong></span></div>
      <p className="wallet-explanation">生成、修改和自动修复按接口返回的真实用量结算，校验失败但已产生的用量也会计费。视频按供应商实际费用折算平台积分，不额外加价。当前无需登录，无充值或支付功能。</p></>:<div className="wallet-loading"><LoaderCircle className="spin" size={18}/>正在读取积分</div>}
    <h3 className="wallet-ledger-title">积分明细</h3>
    {ledger?.pending.map(call=><div className="wallet-pending" key={call.id}><span>{call.status==="uncertain"?"待核对用量":"生成中 · 预授权"}<small>{date(call.created_at)}</small></span><strong>冻结 {call.reserved} 积分</strong>{call.status==="uncertain"&&<p>供应商未返回可确认的用量，维护者核对后结算或释放。调用 ID：<code>{call.id}</code></p>}</div>)}
    {isLoading&&<p className="muted">加载明细…</p>}{ledgerError&&<p className="inline-error">{ledgerError.message}</p>}
    <div className="wallet-ledger">{ledger?.items.map(item=><div className="wallet-entry" key={item.id}><div><strong>{item.kind==="welcome"?"新用户赠送":item.kind==="release"?"预授权已释放":item.kind==="media_consumption"?"视频生成消费":"模型用量消费"}</strong><small>{date(item.created_at)}</small>{item.kind==="consumption"&&<span>输入 {item.input_tokens.toLocaleString()} · 输出 {item.output_tokens.toLocaleString()} token</span>}</div><b className={item.kind==="welcome"?"positive":""}>{item.kind==="welcome"?"+":""}{item.amount}</b></div>)}</div>
    <div className="wallet-pagination">{before&&<button onClick={()=>setBefore(null)}>回到最新</button>}{ledger?.next_before&&<button onClick={()=>setBefore(ledger.next_before)}>更早记录</button>}</div>
    <p className="wallet-explanation">同一浏览器沿用该 ID。清除 Cookie 或换浏览器将成为另一位匿名用户，原项目和余额无法自动找回。</p>
  </Modal>
}
export default function WalletButton({compact=false}:{compact?:boolean}){
  const {data,error}=useWallet(),[open,setOpen]=useState(false);
  return <><button className={"wallet-button "+(compact?"compact":"")} aria-label="积分余额" onClick={()=>setOpen(true)} title={data?"可用 "+data.available+" 积分 · 总余额 "+data.balance:"查看积分"}><Coins size={16}/><span data-testid="credit-balance">{data?short(data.available):error?"重试":"…"}</span><small>积分</small></button>{open&&<WalletDialog onClose={()=>setOpen(false)}/>}</>
}
