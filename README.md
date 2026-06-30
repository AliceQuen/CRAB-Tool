# CRAB-Tool
这是一个用于简化和自动化 CERN CRAB 作业管理的工具集，支持自动注册数据、提交作业、检查状态和重提失败作业。

## 前置要求
使用此工具前，你需要先设置好 CRAB 环境：
如果不设置环境，CRAB-Tool将不能正常工作。
~~~bash
cmsenv
voms-proxy-init -voms cms --valid 172:00
~~~
然后设置你的 GRID 密码。

## 快速开始
### 1. 创建新项目
使用 `init.sh` 创建一个新项目：
~~~bash
source init.sh <project_name>
cd Projects/<project_name>
~~~
这会在 `Projects/<project_name>` 目录下创建必要的文件。

### 2. 配置项目
复制 `config_template.json` 为 `config.json` 并填写配置信息：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `task_name` | 任务名称 | |
| `home_dir` | 项目工作目录绝对路径 | `/afs/cern.ch/user/<u>/<uesername>/MyAnalysis` |
| `analysor_prefix` | 分析代码路径前缀 | `UserCode` |
| `analysor` | 分析代码目录绝对路径 | `/afs/cern.ch/user/<u>/<uesername>/MyAnalysis` |
| `CMSSW_config` | CMSSW 配置模板文件名 | `ntuplize_cfg.py` |
| `outdir` | CRAB 输出目录（必须以 `/store/user/<username>` 开头） | `/store/user/<u>/<uesername>/MyResult` |
| `output` | 输出文件名 | `mtntuple.root` |
| `storage` | 存储站点 | `T3_CH_CERNBOX,T2_CN_BEIJING` |
| `year_config` | 按年份的配置列表 | 见下文 |
| `HLT_config` | HLT 触发器配置 | 见下文 |

**year_config 配置示例：**
~~~json
"year_config": [
  {
    "year": 2018,
    "lumimask": "/path/to/Cert_314472-325175_13TeV_17SeptEarlyReReco2018ABC_PromptEraD_Collisions18_JSON.txt",
    "das_query": "/SingleMuon/Run2018*/RAW/*",
    "CMSSW": {
      "release": "CMSSW_10_2_22",
      "architecture": "slc7_amd64_gcc700"
    },
    "global_tags": [
      {
        "tag": "102X_dataRun2_v12",
        "era": ["A", "B", "C", "D"]
      }
    ]
  }
]
~~~

**HLT_config 配置示例：**
~~~json
"HLT_config": [
  {
    "hlt": "HLT_IsoMu24",
    "filter": "hltIsoMu24WildCard",
    "years": ["2016", "2017", "2018"]
  }
]
~~~
> 注意：你的 CMSSW 配置模板中需要包含占位符 `GLOBAL_TAG`、`HLT` 和 `FILTER`，工具会自动替换这些占位符。

### 3. 自动注册数据并生成配置
运行 `registerData.py` 自动从 DAS 查询数据集并生成 CRAB 配置文件：
~~~bash
python registerData.py
~~~

**这个脚本会自动完成以下工作：**
1. 从 DAS 查询匹配你的 DAS 查询模式的数据集
2. 根据命名规则自动生成任务名称
3. 交互式允许你修改自动生成的命名规则
4. 创建不同年份的 CMSSW 发行版并编译你的分析代码
5. 为每个数据集生成对应的 CRAB 配置文件
6. 创建 `joblist.o` 文件，记录所有作业信息

**命名规则说明：**
- DAS 查询如 `/SingleMuon/Run2018*/RAW/*` 会被拆分为多层
- 工具自动提取通配符部分用于构建任务名称
- 例如：`/SingleMuon/Run2018A/RAW` → `SingleMuon_2018A_RAW`
- 生成后你可以交互式检查和修改命名规则，避免重复

### 4. 提交作业
使用 `manageData.py` 提交作业，支持按条件选择性提交：

**提交所有未提交的作业：**
~~~bash
python manageData.py submit
~~~

**按条件选择性提交：**
~~~bash
python manageData.py submit --year 2018
python manageData.py submit --year 2016,2017,2018
python manageData.py submit --era A,B --dataset SingleMuon
python manageData.py submit --name my_task_name
~~~

多个条件可以组合使用（交集）：
~~~bash
python manageData.py submit --year 2018 --era A --dataset SingleMuon
~~~

### 5. 检查作业状态
检查所有已提交作业的状态：
~~~bash
python manageData.py status
~~~

同样支持按条件检查：
~~~bash
python manageData.py status --year 2018
~~~

脚本会自动查询每个作业的状态并更新 `joblist.o` 文件，显示每个作业的当前状态和错误信息。

### 6. 重提失败作业
对包含特定错误代码的失败作业进行重提：

**重提所有错误作业：**
~~~bash
python manageData.py resubmit
~~~

**只重提特定错误代码的作业：**
~~~bash
python manageData.py resubmit --error 8001,5000
~~~

同样可以结合其他条件：
~~~bash
python manageData.py resubmit --year 2018 --error 8001
~~~

### 7. 杀死并重置作业
杀死已提交的作业并将其状态重置为未提交：

**杀死并重置指定作业：**
~~~bash
python manageData.py kill --name my_task_name
~~~

同样支持按条件选择：
~~~bash
python manageData.py kill --year 2018
python manageData.py kill --year 2018 --era A
~~~

这个操作会：
1. 使用 `crab kill` 杀死 CRAB 作业
2. 删除本地的 `crab_taskname` 目录
3. 将作业状态更新为 `unsubmitted`，方便重新提交

### 8. 详细错误信息查看
在检查状态时可以使用 `--verbose` 选项查看详细的错误信息：

**查看单个作业的详细错误信息：**
~~~bash
python manageData.py status --name my_task_name --verbose
~~~

> 注意：`--verbose` 只能和 `--name` 一起使用，并且只能指定一个作业。

## 文件说明
- `init.sh` - 项目初始化脚本
- `registerData.py` - 数据注册和配置生成脚本
- `manageData.py` - 作业管理脚本（提交/状态/重提/杀死）
- `crab3_template.py` - CRAB 配置模板
- `config_template.json` - 项目配置模板
- `joblist.o` - 作业列表和状态文件（自动生成）
- `naming.json` - 命名规则配置（自动生成）

## joblist.o 格式
`joblist.o` 每行格式为：
```
<dataset_path>,<task_name>,<status>
```
状态示例：
- `unsubmitted` - 未提交
- `SUBMITTED` - 已提交
- `COMPLETED` - 完成
- `FAILED:error8001:error5000:` - 包含错误（错误代码）

## 使用示例
完整工作流示例：
```bash
# 1. 创建项目
source init.sh MyAnalysis
cd Projects/MyAnalysis

# 2. 编辑配置文件
vim config.json

# 3. 注册数据生成配置
python registerData.py

# 4. 提交所有 2018 年的数据
python manageData.py submit --year 2018

# 5. 检查状态
python manageData.py status --year 2018

# 6. 查看单个作业的详细错误信息
python manageData.py status --name my_task_name --verbose

# 7. 重提错误码 8001 的作业
python manageData.py resubmit --year 2018 --error 8001

# 8. 如果需要重置作业（杀死并重置为未提交）
python manageData.py kill --name my_task_name
```

## 注意事项
1. 建议不要将 CMSSW 配置文件（`*_cfg.py`）放在 CRAB-Tool 目录中，它们属于 CMSSW 环境
2. `config.Data.outLFNDirBase` 必须以 `/store/user/<username>/` 格式开头
3. 如果使用 CMSSW7 需要设置 architecture 为 `cmssw7`，工具会自动使用 singularity 容器
4. 每次操作后 `joblist.o` 都会自动更新状态，无需手动修改

## 维护者
[@Alice Quen](https://github.com/AliceQuen) - Project Lead

## 待办事项
1. 添加更多过滤条件支持
2. 支持批量输出状态报告到文件
3. 构建蒙特卡洛工作流
