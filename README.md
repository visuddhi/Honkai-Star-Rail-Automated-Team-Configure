# Honkai: Star Rail Abyss Recommender Prototype

这是一个可本地运行的第一版原型，目标是验证这条产品路线：

- 导入玩家盒子 JSON
- 选择终局模式样例场景
- 自动枚举双队
- 给出 Top 推荐、推荐原因与关键替补

当前版本是规则评分 + 组合搜索，不依赖外网和第三方 Python 包，方便先把体验跑通。

## 运行方式

优先直接运行：

```powershell
.\start.ps1
```

如果你想手动启动：

```powershell
& "C:\Users\hzqin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app.py
```

启动后打开浏览器访问：

`http://127.0.0.1:8000`

## 当前能力

- 提供三类终局模式的样例场景：
  - 混沌回忆
  - 虚构叙事
  - 末日幻影
- 支持上传或粘贴玩家盒子 JSON
- 内置一个示例盒子数据，方便立即试跑
- 约束包括：
  - 双队角色不能重复
  - 大多数模式要求足够生存能力
  - 纯刷分环境会偏向少生存、高对群
  - SP 经济过差的组合会被剪掉
- 输出内容包括：
  - Top 双队推荐
  - 每半场的打分与原因
  - 关键角色
  - 缺少关键角色时的替补建议
  - Top 结果的回合模拟摘要（普通随机 / 最差随机 / 最佳随机）

## 支持的输入格式

推荐使用这个简化格式：

```json
{
  "playerName": "Trailblazer",
  "characters": [
    {
      "name": "黄泉",
      "level": 80,
      "eidolon": 0,
      "traceScore": 0.88,
      "relicScore": 0.9,
      "signature": true
    }
  ]
}
```

也兼容一些常见别名字段，例如：

- `id`
- `characterId`
- `avatarName`
- `key`
- `roster`
- `avatars`

## 测试样本与指南

仓库内额外提供了联调用文件，方便现在作为 GitHub Repo 继续维护：

- `testdata/roster_test_sample.json`：可直接粘贴到页面里的盒子 JSON
- `testdata/recommend_request_sample.json`：可直接用于 `POST /api/recommend` 的请求体
- `testdata/JSON_GUIDE.md`：字段说明、场景 ID、测试方法和常见注意点
- `docs/ALGORITHM_GUIDE.md`：当前推荐、评分、模拟与搜索策略说明

## 回合模拟原型

当前版本在静态推荐之后，会对 Top 3 双队额外跑一层行动模拟原型：

- 每套结果抽样 24 次
- 同时展示 `普通随机`、`最差随机`、`最佳随机`
- 这三档本质上是分位数视角，不是绝对极限 RNG
- 当前模拟仍是原型：有行动轴、SP、能量、破韧、持续伤害和生存压力，但还不是完整官方战斗复刻
- 第二版原型已经引入场景专属波次脚本，配置文件在 `data/simulation_profiles.json`
- 当前这版已经额外补入：
  - 终结技插队窗口
  - 危险技能与蓄力动作
  - 召唤物进场与额外行动压力
  - 按血线触发的阶段转换
- `虚构叙事` 会按刷分目标模拟，并额外显示模拟积分
- 已补入几套高频体系的专属行为，例如：
  - 流萤 + 同谐主的超击破联动
  - 卡芙卡 + 黑天鹅的 DoT 引爆链
  - 姬子 + 黑塔的清杂追击链
  - 真理医生 / 托帕 / 罗宾一类追击体系增益
  - 黄泉在双虚无环境下的层数与爆发节奏

## 后续迭代建议

1. 接真实的 HSR-Scanner / Fribbels 导出结构。
2. 把角色库补全，并拆成独立数值配置文件。
3. 引入更细的上下半敌人特征，例如韧性条、召唤物、行动轴压力。
4. 在规则分外，叠加社区使用率和满星样本的学习排序器。
5. 允许用户保存自己的通关反馈，迭代个性化参数。
