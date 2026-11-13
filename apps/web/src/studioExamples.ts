import type {ProjectKind} from "./api";

export type PublishedGameId="jungle-assault"|"meadow-journey"|"neon-coast"|"warehouse-breakout";
export type PublishedExampleId=PublishedGameId|"jinheng-finance"|"independent-studio"|"shiguang-amber"|"shenzhen-travel"|"annual-review"|"customer-q2-review";
export type ExampleId="breakout"|"memory"|"snake"|"orbit"|"tidal"|PublishedExampleId;
export type StudioExample={
  id:ExampleId;
  kind:ProjectKind;
  category:"网站"|"幻灯片"|"街机"|"解谜"|"竞速"|"动作"|"射击";
  title:string;
  description:string;
  prompt:string;
  publishedExample?:PublishedExampleId;
};

export const studioExamples:StudioExample[]=[
  {id:"jinheng-finance",publishedExample:"jinheng-finance",kind:"web",category:"网站",title:"金衡财经 · 深色行情门户与资讯分析站",description:"查看示例指数走势，按栏目浏览、搜索和阅读财经资讯",prompt:"制作一个深色财经门户，使用深蓝底色与金色点缀。提供指数走势带、分栏资讯流、文章详情、栏目切换及即时搜索。行情和资讯使用明确标注的示例数据。"},
  {id:"independent-studio",publishedExample:"independent-studio",kind:"web",category:"网站",title:"独立站 · 深色编辑杂志风品牌单页",description:"以深色杂志版式呈现工作室服务、案例和方案",prompt:"为独立品牌设计工作室做一个杂志风单页网站。使用深墨底色、醒目标题与不对称网格，展示服务、可展开的案例、分档方案和联系入口。支持移动端菜单与章节导航。"},
  {id:"shiguang-amber",publishedExample:"shiguang-amber",kind:"web",category:"网站",title:"拾光集 · 琥珀暖光的日用选物店",description:"搜索和筛选日用好物，查看规格并体验购物车与演示结算",prompt:"制作一间琥珀暖色的日用选物店，展示精选商品和分类。支持搜索、商品详情、数量选择、购物车与模拟结算。商品和订单均为演示，购物车在本地保存。"},
  {id:"shenzhen-travel",publishedExample:"shenzhen-travel",kind:"slides",category:"幻灯片",title:"深圳旅游规划演示文稿",description:"深圳三日游规划，涵盖行程、预算与出行清单",prompt:"制作一份深圳三日旅游规划网页幻灯片，面向首次到访的休闲游客，包含行程总览、片区对比、逐日安排、预算、出行清单与备选方案。采用统一 16:9 画布，支持按钮和方向键翻页，未确认的价格与时刻标为待补充。"},
  {id:"annual-review",publishedExample:"annual-review",kind:"slides",category:"幻灯片",title:"年度个人工作汇报 · 网页幻灯片",description:"从年度成果到来年计划，八页完整工作汇报",prompt:"制作一份八页年度个人工作汇报网页幻灯片，包含封面、年度概览、关键成果、项目案例、工作流程、成长与不足、来年计划和结语。使用统一版式与可视化图表，支持按钮和方向键翻页，缺失的数据标为待补充。"},
  {id:"customer-q2-review",publishedExample:"customer-q2-review",kind:"slides",category:"幻灯片",title:"客户运营团队 Q2 复盘",description:"四页季度复盘，梳理核心指标、进展与下一步行动",prompt:"制作一份客户运营团队 Q2 复盘网页幻灯片，按季度业务复盘结构整理为四页，包含季度概览、核心指标、进展与挑战、下一步行动。用图表突出结论，未提供的数字标为待补充，支持按钮与键盘翻页。"},
  {id:"jungle-assault",publishedExample:"jungle-assault",kind:"game",category:"动作",title:"丛林突击：魂斗罗",description:"穿越丛林战线，跳跃闪避并击退敌人",prompt:"制作一款魂斗罗风格的横版动作射击游戏，以丛林战线为背景。支持移动、跳跃、瞄准和射击，提供不同敌人、关卡推进、生命与得分，以及暂停和重开。美术、场景和角色请设计成自己的风格。"},
  {id:"meadow-journey",publishedExample:"meadow-journey",kind:"game",category:"动作",title:"草原跳跃：三关奇旅",description:"跳过草原上的障碍，收集奖励并逐关冒险",prompt:"制作一款草原主题的横版平台跳跃游戏，设计三个各有变化的关卡。玩家移动、跳跃、收集奖励、躲避敌人与陷阱，到达终点后进入下一关。提供生命、得分、暂停和重新开始，支持键盘和触屏。"},
  {id:"neon-coast",publishedExample:"neon-coast",kind:"game",category:"竞速",title:"霓虹赤湾 · 海岸环线竞速",description:"在海岸赛道上竞速，绕开障碍并冲刺终点",prompt:"制作一款海岸环线主题的 3D 赛车游戏，采用低位跟车视角。沿赛道驾驶、转向、刹车和氮气加速，避开障碍、收集补给并通过检查点，完成后显示成绩和最佳记录，支持暂停与重赛。"},
  {id:"warehouse-breakout",publishedExample:"warehouse-breakout",kind:"game",category:"射击",title:"仓库突围：冷光行动",description:"进入工业仓库，用掩体与精准射击完成突围",prompt:"制作一款工业仓库场景的 3D 第一人称射击游戏。使用 WASD 移动、鼠标转视角、左键射击和 R 换弹，敌人会移动和还击，掩体能阻挡子弹。提供生命、弹药、击杀反馈、胜负结算、暂停与重开。"},
  {id:"orbit",kind:"game",category:"解谜",title:"轨道信使",description:"规划三段航区的路线，接通信标再撤离",prompt:"设计一款科幻路线解谜游戏。玩家驾驶轨道信使在三张不同地图移动，普通路面每步扣电，磁暴加倍耗电，补给只可用一次。收齐信标才开出口，逐关解锁并统计步数。加上状态 HUD、键盘和触屏方向操作、暂停、失败及重开。"},
  {id:"tidal",kind:"game",category:"竞速",title:"潮汐穿梭",description:"穿过三个航段，在浮石中找回航标",prompt:"设计一款实时飞行闯关游戏。玩家在三段速度递增的海上航线中左右操控飞行器，避开浮石、收集信标，保住护盾并达到最低信标数后回港。使用蓝紫色夜航场景、清晰 HUD、键盘和触屏、暂停恢复及本地最佳记录。"},
  {id:"breakout",kind:"game",category:"街机",title:"星光打砖块",description:"接住小球，清除彩色砖块",prompt:"制作一款浅色星光打砖块游戏。玩家用挡板反弹小球、打掉彩色砖块。提供三次机会、得分、暂停、胜负和重开，支持鼠标、键盘和触屏。"},
  {id:"memory",kind:"game",category:"解谜",title:"星象翻牌",description:"翻开卡片，找出对应的星象",prompt:"制作一款星象翻牌游戏，包含太阳、月亮、行星和星星图案。每次翻开两张，匹配后保留，显示步数和完成状态，可以重新洗牌，适配触屏。"},
  {id:"snake",kind:"game",category:"街机",title:"霓虹贪吃蛇",description:"在蓝色网格中收集能量",prompt:"制作霓虹贪吃蛇浏览器游戏。显示分数，蛇吃到能量点后增长，撞墙或撞到自己结束。提供暂停、重开、方向键和触屏方向按钮。"},
];

export function coverUrl(id:ExampleId) {
  return "/examples/"+id+(id==="orbit"||id==="tidal"||studioExamples.some(example=>example.id===id&&example.publishedExample)?".png":".webp");
}
