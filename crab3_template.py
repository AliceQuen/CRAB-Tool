from WMCore.Configuration import Configuration

config = Configuration()

config.section_("General")
config.General.transferOutputs = True
config.General.requestName = "__REQUEST_NAME__"

config.section_("JobType")
config.JobType.psetName = "../ConfFile_cfg.py"
config.JobType.pluginName = "Analysis"
config.JobType.outputFiles = ["__OUTPUT_FILE__"]
config.JobType.pyCfgParams = [
    "runOnMC=False",
    "era=__ERA__",
    "outputFile=__OUTPUT_FILE__",
    "analysisMode=__ANALYSIS_MODE__",
    "numThreads=4",
    "numStreams=4",
]
config.JobType.allowUndistributedCMSSW = True
# Allow 4-thread. Memory request is 8GB.
config.JobType.numCores = 4
config.JobType.maxMemoryMB = 4000

config.section_("Data")
config.Data.inputDataset = "__DATASET__"
config.Data.inputDBS = "global"
config.Data.unitsPerJob = __UNITS_PER_JOB__
config.Data.splitting = "LumiBased"
config.Data.lumiMask = "__LUMI_MASK__"
config.Data.outLFNDirBase = "__OUTLFN__"
config.Data.outputDatasetTag = "__OUTPUT_TAG__"

config.section_("User")
config.section_("Site")
config.Site.storageSite = "__STORAGE_SITE__"
