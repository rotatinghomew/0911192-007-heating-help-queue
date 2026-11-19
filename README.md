# 供热求助的等待风险与跨组支援

服务台交接簿及派工约束。住户、楼栋、联系人均为合成代号。
这里的记录全部为合成资料。日期按当地日历解释，未附时区的时间使用东八区。

## 交接资料

CSV 使用 UTF-8 和逗号分隔。值留空表示这条资料未给出该字段，不等于零。
`data/schema.json` 登记表头与跨表编号关系；`data/policy.json` 保存本期业务配置。

- `data/cold_waves.csv`：按各轮连续影响登记；跨轮检验时不混用同轮事件。 字段：`wave`, `begins`, `ends`, `level`。
- `data/intake.csv`：outage 是受理渠道的事由号，不保证跨来源唯一；access 说明进场条件。 字段：`ticket`, `home`, `outage`, `wave`, `at`, `known`, `district`, `kind`, `source`, `access`。
- `data/identity_notices.csv`：relation 取同次停供 same 或两次停供 split；同一对后到签认替换早先签认。 字段：`notice`, `left`, `right`, `relation`, `known`。
- `data/followups.csv`：known 是交接可见时间；同票可先转办、后回暖。 字段：`evidence`, `ticket`, `event`, `at`, `known`。
- `data/shift_staff.csv`：本地时间；skills 和 access 可以分号多值。 字段：`slot`, `worker`, `group`, `starts`, `ends`, `skills`, `access`。
- `data/assignments.csv`：已确认的派工按覆盖的实际时段占用。 字段：`assignment`, `slot`, `ticket`, `confirmed`, `starts`, `ends`。

## 资料校验

使用 Python 3.11.2 标准库，不需要安装扩展包。资料入口只核查交接格式，不计算业务结果。

```sh
python3 inspect_inputs.py
python3 -m unittest discover -s tests -v
```

## 交接回看与借调

`hotline` 包把排队压力、居民真实等待和班次调度连起来，不按结案口径出看板。

```sh
python3 -m hotline review --data data --at 2026-02-12T16:00
python3 -m hotline backtest --data data
```

子命令：`episodes`（等候人群）、`risk`（超承诺风险）、`plan`（下一班借调）、
`backtest`（寒潮轮回看）、`review`（完整回看，默认）。`--at` 为交接时点，
缺省取资料中最新的 known。

口径：

- 同一住户同一停供只算一条等候过程；同对票据以 known 最新的签认为准
  （same 合并、split 另起），早班错误合并在更正后重算等待起点与服务归属。
- restored、moved 是已确认终点；lost 是随访缺失，不算解除等待；
  forwarded 仅转办，住户仍在等。
- 等待时长按事件发生时间 at 计，是否可见按交接可见时间 known 计；
  单据导出时间不等于当班值长看到的时间。
- 风险按片区×服务类别做竞争风险估计（承诺内回暖 / 先出现其他离开原因 /
  到期仍在等分开），等候者按已等时长取条件概率；已结样本不足或去向缺失
  超过上限时输出「难定」，不用全市平均顶替本地承诺；寒潮轮回看采用整轮
  留出，拟合不用该轮。
- 借调只用本班空闲合格工位（skills、access 与需求匹配）：本组优先；抽调后
  原组每班至少保留一个本组在岗合资格工位；同一人员不得借往两处；上一班
  已确认的派工按覆盖时段占用工位，下一班不得重派；风险高不等于有可派
  岗位，无法落实的需求如实列为缺口。

`data/policy.json` 另有两项配置：`等待分档小时`（风险分档）、`拟合下限`
（每格最小已结样本、去向缺失占比上限）。
