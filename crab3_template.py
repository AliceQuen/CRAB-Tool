from WMCore.Configuration import Configuration
config = Configuration()

config.section_('General')
config.General.transferOutputs = True
#config.General.transferLogs = True
config.General.requestName = 'TaskTag'

config.section_('JobType')
config.JobType.psetName = 'runMultiLepPAT_dataRun3_miniAOD.py'
config.JobType.pluginName = 'Analysis' #or 'PrivateMC' for Monte Calo jobs
config.JobType.outputFiles = ['mymultilep.root']
config.JobType.allowUndistributedCMSSW = True

config.section_('Data')
config.Data.inputDataset = 'DataSet'
config.Data.inputDBS = 'global'
config.Data.unitsPerJob = 20
config.Data.splitting = 'LumiBased'
config.Data.outLFNDirBase = '/store/user/qinju/jpsiPsi2S/rootNtuple/' #LFN=Logical File Name
config.Data.outputDatasetTag = 'TaskTag'

config.section_('User')
config.section_('Site')
config.Site.storageSite = 'T3_CH_CERNBOX'
