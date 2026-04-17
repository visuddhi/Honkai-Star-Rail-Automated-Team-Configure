# JSON 测试样本指南

这份指南对应当前仓库的真实实现，已经按现在的 Repo 结构核对过。

## 1. 现在的数据入口在哪

- 页面启动入口：`app.py`
- 静态页面：`web/`
- 角色库：`data/characters.json`
- 场景库：`data/scenarios.json`
- 内置示例盒子：`data/sample_roster.json`
- 新增测试样本：`testdata/roster_test_sample.json`
- 新增请求体样本：`testdata/recommend_request_sample.json`

当前代码按相对路径读取 `data/`，所以只要 `app.py`、`src/`、`data/` 还保持现在这层级关系，整个 Repo 搬位置后也能正常工作。

## 2. 你应该用哪个 JSON

- 如果你要在网页里直接粘贴角色盒子，使用 `testdata/roster_test_sample.json`
- 如果你要直接调接口 `POST /api/recommend`，使用 `testdata/recommend_request_sample.json`

## 3. 接口要求

请求地址：

```text
POST /api/recommend
```

请求体顶层字段：

```json
{
  "scenarioId": "moc_debuff_break",
  "roster": {}
}
```

说明：

- `scenarioId` 必填
- `roster` 必填
- `roster` 既可以是对象，也可以是一个 JSON 字符串
- 网页前端当前发送的是字符串；如果你自己写脚本联调，直接传对象也可以

## 4. 当前可用的场景 ID

- `moc_debuff_break`
- `moc_followup_split`
- `pure_fiction_aoe`
- `apocalyptic_shadow_break`

## 5. 盒子 JSON 支持哪些字段

角色列表容器支持这些名字之一：

- `characters`
- `roster`
- `avatars`
- `units`

单个角色的“名字/ID”字段支持这些名字之一：

- `id`
- `key`
- `name`
- `characterId`
- `characterName`
- `avatarName`
- `displayName`

只要其中一个字段能匹配到 `data/characters.json` 里的角色 ID、中文名或别名，就能识别。

例如这些都能识别：

- `Kafka`
- `卡芙卡`
- `kafka`
- `Ruan Mei`
- `阮梅`
- `阮·梅`

## 6. 角色练度字段怎么写

常用字段：

- `level`
- `eidolon`
- `e`
- `traceScore`
- `traces`
- `skills`
- `relicScore`
- `buildScore`
- `score`
- `signature`
- `lightConeTier`
- `lightConeScore`
- `weaponScore`
- `coneScore`
- `lightCone`
- `relics`
- `artifacts`
- `equipment`
- `ornaments`

数值归一化规则：

- 如果你传 `0.88`，按 0 到 1 处理
- 如果你传 `8.8`，按 0 到 10 处理，会转成 `0.88`
- 如果你传 `88`，按 0 到 100 处理，会转成 `0.88`

额外规则：

- `lightCone.signature: true` 或角色级别的 `signature: true` 会被视为高适配专武
- `owned: false` 的记录会被忽略
- 同一角色重复出现时，只会保留一份
- 识别失败的角色会出现在返回结果的 `meta.skipped`
- 如果提供详细遗器结构，当前版本会额外解析主词条 / 副词条 / 套装，并映射到速度、击破、追击、DoT、减益、辅助、生存等派生属性

遗器详细结构推荐长这样：

```json
{
  "id": "firefly",
  "relics": [
    {
      "setName": "Iron Cavalry",
      "mainStat": "Break Effect",
      "mainValue": "64.8%",
      "substats": [
        { "type": "Speed", "value": "9" },
        { "type": "Break Effect", "value": "24%" }
      ],
      "level": 15,
      "rarity": 5
    }
  ]
}
```

## 7. 最低测试要求

要生成有效双队，当前至少需要：

- 识别到 8 名角色
- 这 8 名角色能组成两队各 4 人
- 队伍满足当前场景的基础约束

如果少于 8 名可识别角色，后端会直接报错。

## 8. 推荐测试方法

### 方法 A：网页里直接测

1. 运行：

```powershell
.\start.ps1
```

2. 打开：

```text
http://127.0.0.1:8000
```

3. 把 `testdata/roster_test_sample.json` 的内容粘贴进页面输入框
4. 选择一个场景
5. 点击“生成推荐”

### 方法 B：直接打接口

```powershell
$body = Get-Content -Raw .\testdata\recommend_request_sample.json
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/api/recommend `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

## 9. 这份测试样本做了什么覆盖

`testdata/roster_test_sample.json` 故意混用了多种兼容写法，用来验证解析器没有被这次目录调整影响：

- 容器字段用的是 `avatars`
- 角色名字段混用了 `name`、`characterName`、`avatarName`、`id`、`key`、`characterId`、`displayName`
- 练度分数混用了 `0-1`、`0-10`、`0-100`
- 混用了 `eidolon` 和 `e`
- 混用了 `traceScore`、`traces`、`skills`
- 混用了 `signature` 和 `lightCone.signature`

如果这份样本能跑通，说明当前 JSON 兼容层基本正常。
