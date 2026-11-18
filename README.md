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
