import catalog from "../../../shared/slide-templates.json";

export type SlideTemplate = (typeof catalog)[number];
export type TemplateSlide = SlideTemplate["slides"][number];

export const slideTemplates: readonly SlideTemplate[] = catalog;

export function templatePrompt(template: SlideTemplate) {
  const {topic,audience,content} = template.fields;
  return `请把「${template.name}」模板改成我的网页幻灯片。

主题：${topic}
听众：${audience}
内容：${content}`;
}
