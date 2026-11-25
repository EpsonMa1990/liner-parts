<script setup>
import { ArrowUpRight, Github, Globe, Handshake } from 'lucide-vue-next'
import Dialog from './Dialog.vue'
import { project } from './project'
defineEmits(['close'])
const features = [
  ['取件表制作', '从说明书识别零件编号，校对分类与数量，导出取件清单。', '/features/parts-list.html'],
  ['AI 上色', '在线稿上试配颜色，预览模型涂装的材质与整体效果。', '/features/line-coloring.html'],
  ['极致分色', '上传模型或部件照片，探索装甲、内构与细节的精细配色。', '/features/extreme-color.html'],
  ['AI 生图', '用文字与参考图探索涂装、改造和展示效果。', '/features/ai-image.html'],
  ['灵感画板', '组合素材、抠图与绘线，先在画板上推敲改造构图。', '/features/inspiration-board.html'],
  ['品牌漆色卡', '浏览品牌漆色，查询相近色，为实际涂装选色。', '/#paint-color-cards'],
  ['分享广场', '浏览模型作品与取件表，分享成果、点赞与收藏。', '/square'],
]
</script>

<template>
  <Dialog title="项目介绍与官网" class="project-dialog" @close="$emit('close')">
    <div class="project-intro">
      <span class="eyebrow">LINER PARTS · FREE & OPEN SOURCE</span>
      <h3>从整理零件，到完成你的模型。</h3>
      <p>Liner Parts 是胶佬 AI 应用平台的开源桌面取件工具，为高达与拼装模型玩家提供 PDF / 图片导入、框选识别、截图校对和 Excel 导出。任务保存在本机，识别使用你自己的模型接口。</p>
      <div class="project-actions">
        <a class="primary project-link" :href="project.website" target="_blank" rel="noopener noreferrer"><Globe :size="17" />访问 agamaship.com<ArrowUpRight :size="16" /></a>
        <a class="secondary project-link" :href="project.github" target="_blank" rel="noopener noreferrer"><Github :size="17" />GitHub 开源项目<ArrowUpRight :size="16" /></a>
      </div>
      <a class="project-repo" :href="project.github" target="_blank" rel="noopener noreferrer">github.com/EpsonMa1990/liner-parts</a>
    </div>
    <section class="project-platform" aria-labelledby="platform-heading">
      <div class="project-section-heading"><h3 id="platform-heading">官网还能帮你做什么？</h3><a :href="project.guide" target="_blank" rel="noopener noreferrer">功能教程 <ArrowUpRight :size="14" /></a></div>
      <div class="project-features">
        <a v-for="[name, description, path] in features" :key="name" :href="project.website + path" target="_blank" rel="noopener noreferrer"><strong>{{ name }}<ArrowUpRight :size="14" /></strong><span>{{ description }}</span></a>
      </div>
      <p class="project-note">公开教程无需登录；在线工作区需登录，AI 生成按官网当前规则计费。完成整个模型的取件表后，可在桌面版提交分享，审核通过奖励 5 张 AI 生成卡（需平台支持）。</p>
    </section>
    <section class="project-business" aria-labelledby="business-heading">
      <Handshake :size="23" aria-hidden="true" />
      <div><h3 id="business-heading">商用需求与品牌合作</h3><p>有定制工具、私有部署、功能集成或团队使用需求？欢迎通过官网联系站长洽谈。模型品牌、工具厂家及相关机构也可咨询品牌展示与推广合作。</p><a :href="project.contact" target="_blank" rel="noopener noreferrer">联系站长 · 洽谈需求 <ArrowUpRight :size="15" /></a></div>
    </section>
    <p class="project-license">本项目采用 MIT 开源协议，欢迎使用、修改和贡献代码。第三方组件遵循各自许可证，详情见项目 LICENSE 与 THIRD_PARTY_NOTICES。问题反馈与改进建议欢迎提交到 GitHub。</p>
  </Dialog>
</template>

<style scoped>
.project-dialog{width:min(840px,calc(100vw - 32px))}.project-intro{padding:6px 0 22px;border-bottom:1px solid var(--border)}.project-intro h3{font-size:24px;line-height:1.5;margin:10px 0;text-wrap:balance}.project-intro p,.project-business p{font-size:13px;line-height:1.85;color:var(--muted)}.project-actions{display:flex;gap:10px;flex-wrap:wrap;margin:19px 0 10px}.project-link{display:inline-flex;text-decoration:none;align-items:center;gap:8px;min-height:44px}.project-repo{font:12px var(--mono);overflow-wrap:anywhere}.project-dialog a{color:var(--accent)}.project-dialog a.primary{color:white}.project-dialog a:focus-visible{outline:3px solid #6eaa96;outline-offset:3px}.project-section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:22px 0 14px}.project-section-heading h3,.project-business h3{font-size:16px}.project-section-heading>a,.project-business a{display:inline-flex;gap:5px;align-items:center;font-size:12px;min-height:36px}.project-features{display:grid;grid-template-columns:1fr 1fr;column-gap:24px}.project-features>a{display:block;text-decoration:none;padding:13px 0;border-bottom:1px solid var(--border)}.project-features strong{display:flex;align-items:center;justify-content:space-between;font-size:13px;gap:8px}.project-features span{display:block;font-size:12px;line-height:1.7;margin-top:6px;color:var(--muted)}.project-features>a:hover strong{text-decoration:underline}.project-note,.project-license{font-size:12px;line-height:1.8;color:var(--muted);margin-top:15px}.project-business{display:flex;gap:13px;padding:18px;background:var(--accent-soft);border-radius:9px;margin-top:22px}.project-business>svg{color:var(--accent);flex-shrink:0;margin-top:2px}.project-business p{margin-top:8px}.project-business a{font-weight:600;margin-top:5px}.project-license{margin-bottom:2px}@media(max-width:600px){.project-intro h3{font-size:21px}.project-features{grid-template-columns:1fr}.project-business{padding:15px}.project-business>svg{display:none}.project-section-heading{gap:10px}}
</style>
