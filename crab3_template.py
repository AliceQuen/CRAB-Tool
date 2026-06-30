from WMCore.Configuration import Configuration
config = Configuration()

config.section_('General')
config.General.transferOutputs = True
#config.General.transferLogs = True
config.General.requestName = 'TASK_TAG'

config.section_('JobType')
config.JobType.psetName = 'PSET' #CMSSW config file
config.JobType.pluginName = 'Analysis' #or 'PrivateMC' for Monte Calo jobs
config.JobType.outputFiles = ['OUTPUT'] # output file name
config.JobType.allowUndistributedCMSSW = True
config.JobType.numCores = 8

config.section_('Data')
config.Data.inputDataset = 'DATASET'
config.Data.inputDBS = 'global'
#config.Data.unitsPerJob = 20 #used at Lumibased
config.Data.splitting = 'Automatic'
config.Data.lumiMask = 'LUMI_MASK'
config.Data.outLFNDirBase = 'OUTDIR' #output destination, must in format '/store/user/<username>/..'
config.Data.outputDatasetTag = 'TASK_TAG'

config.section_('User')
config.section_('Site')
config.Site.storageSite = 'STORAGE' #physical store server knot, T3_CH_CERNBOX means cernbox
