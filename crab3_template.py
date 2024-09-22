from WMCore.Configuration import Configuration
config = Configuration()

config.section_('General')
config.General.transferOutputs = True
#config.General.transferLogs = True
config.General.requestName = 'TaskTag'

config.section_('JobType')
config.JobType.psetName = '' #CMSSW config file
config.JobType.pluginName = 'Analysis' #or 'PrivateMC' for Monte Calo jobs
config.JobType.outputFiles = [''] # output file name
config.JobType.allowUndistributedCMSSW = True

config.section_('Data')
config.Data.inputDataset = 'DataSet'
config.Data.inputDBS = 'global'
config.Data.unitsPerJob = 20
config.Data.splitting = 'LumiBased'
config.Data.outLFNDirBase = '' #output destination, must in format '/store/user/<username>/..'
config.Data.outputDatasetTag = 'TaskTag'

config.section_('User')
config.section_('Site')
config.Site.storageSite = '' #physical store server knot, T3_CH_CERNBOX means cernbox
