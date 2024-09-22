# CRAB-Tool
This is a tool set to facilitate CERN CRAB works.
## Usage
For any usage, you need to **set up CRAB** first. That is
~~~bash
cmsenv
voms-proxy-init -voms cms --valid 172:00
~~~
and then set your GRID password
### Register Data List and Submit
To Submit the jobs, first you need to configurate crab with **crab3_template.py** and configurate CMSSW with your own **__cfg.py** (for details refer to CMSSW TWiki). 

**Attension:** you'd better not put _cfg.py in CRAB-Tool directory cause it's for CMSSW not crab.

Lines to be specified in **crab3_template.py** are
~~~python
config.JobType.psetName = '' #CMSSW config file
config.JobType.outputFiles = [''] # output file name
config.Data.outLFNDirBase = '' #output destination, must in format '/store/user/<username>/...'
config.Site.storageSite = ''  #physical store server knot, T3_CH_CERNBOX means cernbox
~~~

Then configuarte and execute **registerData.sh**. Mean part to notice is the variable **dataList** and **Tag Format** part. Variable **dataList** use a **dataList.txt** to specifys data set and tag format decides tag of output directories. A example of the two parts are included.

After that, configurate and execute **submit.sh**. Only thing to care is variable **dryRun**. By executing **submit.sh**, **all .py files** except for **crab3_template.py** and **_cfg.py** will be used for CRAB config and submitted to CRAB server.
### Check Job Status and Resubmit
To check job status, execute **status.sh**. This genarates a formated report file **report.out**, with number of failed running jobs and error codes. Then you can use any text proccesor to check status.

*Example* 
~~~bash
source status.sh
cat report.out # check details
grep '8001' report.out # check jobs exit with 8001
~~~

After getting **report.out**, you can resubmit jobs executing **resubmit.sh**. Before it, please first configurate **Configuration** part in **resubmit.sh**.

**Attention:** resubmit must be done with a proper **report.out** file.

## Maintainers
[@Alice Quen](https://github.com/AliceQuen) - Project Lead
## TODOS
1. submit.sh needs partial submit function
2. registerData.sh needs a more convenient way to set tag format, or at least a full instruction for it
