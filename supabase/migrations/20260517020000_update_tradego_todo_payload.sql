-- 把 product='tradego' 的所有 todo 模板 payload 更新为10个外贸跟单 checkpoint
UPDATE expert_todo_templates
SET payload = '[
  {"label":"客户开发","items":[{"label":"企业背景调查"},{"label":"需求初步确认"},{"label":"决策链梳理"}]},
  {"label":"询盘报价","items":[{"label":"整理询盘需求"},{"label":"成本核算"},{"label":"发送PI/报价单"}]},
  {"label":"样品确认","items":[{"label":"打样/制样"},{"label":"寄样（快递单号）"},{"label":"客户确样回复"}]},
  {"label":"订单签约","items":[{"label":"合同/PI签署"},{"label":"定金到账确认"},{"label":"排产计划确认"}]},
  {"label":"生产跟进","items":[{"label":"原料备料确认"},{"label":"生产进度节点"},{"label":"异常问题处理"}]},
  {"label":"质量检验","items":[{"label":"品控抽检"},{"label":"验货报告"},{"label":"客户确认放行"}]},
  {"label":"备货装运","items":[{"label":"包装/装箱确认"},{"label":"订舱/柜号"},{"label":"出货/提单号"}]},
  {"label":"单证制作","items":[{"label":"发票/装箱单"},{"label":"原产地证CO"},{"label":"寄单/快递号"}]},
  {"label":"清关收款","items":[{"label":"目的港清关放行"},{"label":"尾款催收"},{"label":"收款到账确认"}]},
  {"label":"售后跟进","items":[{"label":"到货确认"},{"label":"客户反馈收集"},{"label":"复购/转介绍"}]}
]'::jsonb
WHERE product = 'tradego';
