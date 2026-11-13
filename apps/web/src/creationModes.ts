import {Clapperboard,Gamepad2,Globe,Presentation} from "lucide-react";
import type {ProjectKind} from "./api";

export const modes = {
  web: {
    label: "网站", nav: "首页", path: "/", icon: Globe, output: "可交互网站",
    title: "你想创建什么网站？",
    description: "从一个想法开始，创建网站、页面和日常工具。",
    placeholder: "描述你想做的网站，它面向谁，需要哪些功能？",
    examples: [],
  },
  game: {
    label: "游戏", nav: "游戏", path: "/games", icon: Gamepad2, output: "浏览器游戏",
    title: "你想创建什么游戏？",
    description: "先玩一局，再把你的玩法做出来。",
    placeholder: "描述你的游戏玩法、画风和胜负条件…",
    examples: [],
  },
  slides: {
    label: "幻灯片", nav: "幻灯片", path: "/slides", icon: Presentation, output: "网页幻灯片",
    title: "你想讲一个怎样的故事？",
    description: "按页组织内容，生成可翻页的网页演示。",
    placeholder: "描述演示主题、听众、页数和视觉风格…",
    examples: [],
  },
  video: {
    label: "视频", nav: "视频", path: "/video", icon: Clapperboard, output: "AI 视频",
    title: "你的下一支短片，拍什么？",
    description: "输入文字或上传首帧图片，描述动作与镜头，生成可播放、下载的视频。",
    placeholder: "描述主题、时长、镜头顺序和你想要的画面风格…",
    examples: [
      { title: "新品发布预告", description: "从悬念到产品亮相", prompt: "做一支 15 秒耳机新品预告的网页分镜样片。用图形动画表现开场悬念、产品亮相和卖点，加入可播放、暂停、拖动的时间轴。" },
      { title: "城市旅行开场", description: "用动态构图串联三个镜头", prompt: "制作一段 18 秒城市旅行片头的动态分镜样片，分为清晨、白天和蓝调时刻。用网页绘图和排版呈现画面。" },
      { title: "品牌动态图形", description: "为标志设计入场和片尾", prompt: "制作 10 秒品牌标志动态分镜，使用极简几何图形和三段运动节奏，提供暂停和重新播放。" },
    ],
  },
} satisfies Record<ProjectKind, {label:string;nav:string;path:string;icon:typeof Globe;output:string;title:string;description:string;placeholder:string;examples:{title:string;description:string;prompt:string}[]}>;

export const creationKinds = ["web", "game", "slides", "video"] as const;

export function inferProjectKind(prompt:string):ProjectKind {
  const opening=prompt.normalize("NFKC").split(/[\r\n。！？!?；;]/,1)[0];
  // Match the requested deliverable in the opening. Specific formats can also
  // be the subject matter of a site, such as a game portfolio or a video portal.
  if (/网站|站点|官网|落地页|着陆页|网页(?!\s*(?:小游戏|游戏|幻灯片|演示|分镜|短片|视频|截图))|\b(?:web\s*app|website|landing page|dashboard|portfolio)\b/i.test(opening)) return "web";
  const formats=[
    ["slides",/幻灯片|演示文稿|网页演示|\b(?:pptx?|powerpoint|slides?|slide deck)\b/i],
    ["game",/小游戏|网页游戏|浏览器游戏|贪吃蛇|打砖块|扫雷|俄罗斯方块|\b(?:breakout|minesweeper|tetris)\b/i],
    ["video",/分镜|短片|宣传片|片头|\b(?:storyboard|trailer)\b/i],
  ] as const;
  const matches=formats.flatMap(([kind,pattern])=>{
    const index=opening.search(pattern);
    return index<0?[]:[{kind,index}];
  });
  const explicit=matches.sort((a,b)=>a.index-b.index)[0]?.kind;
  if (explicit) return explicit;
  const generic=opening.match(/游戏|视频|\b(?:game|video)\b/i)?.[0];
  if (!generic) return "web";
  return /游戏|game/i.test(generic)?"game":"video";
}
