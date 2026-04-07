# CRAB-Tool
A toolset for simplifying and automating CERN CRAB job management, supporting automatic data registration, job submission, status checking, and resubmission of failed jobs.

## Prerequisites
Before using this tool, you need to set up the CRAB environment first:
CRAB-Tool will not work properly if the environment is not set up.
~~~bash
cmsenv
voms-proxy-init -voms cms --valid 172:00
~~~
Then set your GRID password.

## Quick Start
### 1. Create a New Project
Use `init.sh` to create a new project:
~~~bash
source init.sh <project_name>
cd Projects/<project_name>
~~~
This will create the necessary files in the `Projects/<project_name>` directory.

### 2. Configure the Project
Copy `config_template.json` to `config.json` and fill in the configuration information:

| Configuration | Description | Example |
|--------|------|------|
| `task_name` | Task name | |
| `home_dir` | Absolute path to project working directory | `/afs/cern.ch/user/<u>/<username>/MyAnalysis` |
| `analysor_prefix` | Analysis code path prefix | `UserCode` |
| `analysor` | Absolute path to analysis code directory | `/afs/cern.ch/user/<u>/<username>/MyAnalysis` |
| `CMSSW_config` | CMSSW configuration template filename | `ntuplize_cfg.py` |
| `outdir` | CRAB output directory (must start with `/store/user/<username>`) | `/store/user/<u>/<username>/MyResult` |
| `output` | Output filename | `mtntuple.root` |
| `storage` | Storage sites | `T3_CH_CERNBOX,T2_CN_BEIJING` |
| `year_config` | Configuration list by year | See below |
| `HLT_config` | HLT trigger configuration | See below |

**year_config Example:**
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

**HLT_config Example:**
~~~json
"HLT_config": [
  {
    "hlt": "HLT_IsoMu24",
    "filter": "hltIsoMu24WildCard",
    "years": ["2016", "2017", "2018"]
  }
]
~~~
> Note: Your CMSSW configuration template needs to contain placeholders `GLOBAL_TAG`, `HLT` and `FILTER`, the tool will automatically replace these placeholders.

### 3. Auto Register Data and Generate Configurations
Run `registerData.py` to automatically query datasets from DAS and generate CRAB configuration files:
~~~bash
python registerData.py
~~~

**This script automatically completes the following:**
1. Query datasets from DAS matching your DAS query pattern
2. Automatically generate task names based on naming rules
3. Interactively allows you to modify the automatically generated naming rules
4. Create CMSSW releases for different years and compile your analysis code
5. Generate corresponding CRAB configuration files for each dataset
6. Create `joblist.o` file to record all job information

**Naming Rules Description:**
- DAS queries like `/SingleMuon/Run2018*/RAW/*` will be split into multiple layers
- The tool automatically extracts the wildcard part for building the task name
- For example: `/SingleMuon/Run2018A/RAW` → `SingleMuon_2018A_RAW`
- After generation, you can interactively check and modify naming rules to avoid duplicates

### 4. Submit Jobs
Use `manageData.py` to submit jobs, supports conditional selective submission:

**Submit all unsubmitted jobs:**
~~~bash
python manageData.py submit
~~~

**Selective submission by conditions:**
~~~bash
python manageData.py submit --year 2018
python manageData.py submit --year 2016,2017,2018
python manageData.py submit --era A,B --dataset SingleMuon
python manageData.py submit --name my_task_name
~~~

Multiple conditions can be combined (intersection):
~~~bash
python manageData.py submit --year 2018 --era A --dataset SingleMuon
~~~

### 5. Check Job Status
Check the status of all submitted jobs:
~~~bash
python manageData.py status
~~~

Also supports checking by conditions:
~~~bash
python manageData.py status --year 2018
~~~

The script automatically queries the status of each job and updates the `joblist.o` file, displaying the current status and error information for each job.

### 6. Resubmit Failed Jobs
Resubmit failed jobs containing specific error codes:

**Resubmit all error jobs:**
~~~bash
python manageData.py resubmit
~~~

**Only resubmit jobs with specific error codes:**
~~~bash
python manageData.py resubmit --error 8001,5000
~~~

You can also combine with other conditions:
~~~bash
python manageData.py resubmit --year 2018 --error 8001
~~~

### 7. Kill and Reset Jobs
Kill submitted jobs and reset their status to unsubmitted:

**Kill and reset specified jobs:**
~~~bash
python manageData.py kill --name my_task_name
~~~

Also supports selection by conditions:
~~~bash
python manageData.py kill --year 2018
python manageData.py kill --year 2018 --era A
~~~

This operation will:
1. Kill the CRAB job using `crab kill`
2. Delete the local `crab_taskname` directory
3. Update the job status to `unsubmitted` for easy resubmission

### 8. View Detailed Error Information
You can use the `--verbose` option to see detailed error information when checking status:

**View detailed error information for a single job:**
~~~bash
python manageData.py status --name my_task_name --verbose
~~~

> Note: `--verbose` can only be used with `--name`, and only one job can be specified.

## File Description
- `init.sh` - Project initialization script
- `registerData.py` - Data registration and configuration generation script
- `manageData.py` - Job management script (submit/status/resubmit/kill)
- `crab3_template.py` - CRAB configuration template
- `config_template.json` - Project configuration template
- `joblist.o` - Job list and status file (auto-generated)
- `naming.json` - Naming rules configuration (auto-generated)

## joblist.o Format
Each line in `joblist.o` has the format:
```
<dataset_path>,<task_name>,<status>
```
Status examples:
- `unsubmitted` - Not submitted
- `SUBMITTED` - Submitted
- `COMPLETED` - Completed
- `FAILED:error8001:error5000:` - Contains errors (error codes)

## Usage Example
Complete workflow example:
```bash
# 1. Create project
source init.sh MyAnalysis
cd Projects/MyAnalysis

# 2. Edit configuration file
vim config.json

# 3. Register data and generate configurations
python registerData.py

# 4. Submit all 2018 data
python manageData.py submit --year 2018

# 5. Check status
python manageData.py status --year 2018

# 6. View detailed error information for a single job
python manageData.py status --name my_task_name --verbose

# 7. Resubmit jobs with error code 8001
python manageData.py resubmit --year 2018 --error 8001

# 8. If you need to reset the job (kill and reset to unsubmitted)
python manageData.py kill --name my_task_name
```

## Notes
1. It is recommended not to put CMSSW configuration files (`*_cfg.py`) in the CRAB-Tool directory, they belong to the CMSSW environment
2. `config.Data.outLFNDirBase` must start with `/store/user/<username>/`
3. If using CMSSW7, set architecture to `cmssw7`, the tool will automatically use the singularity container
4. After each operation, `joblist.o` is automatically updated with status, no manual modification needed

## Maintainer
[@Alice Quen](https://github.com/AliceQuen) - Project Lead

## TODO
1. Add more filtering condition support
2. Support batch output of status reports to file
