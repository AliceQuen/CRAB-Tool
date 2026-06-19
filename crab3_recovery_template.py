from __future__ import annotations

from WMCore.Configuration import Configuration

config = Configuration()

# The builder preserves literal config fields from the original task even when
# they are not restated here. Edit the direct config assignments below, or add
# new config.<Section>.<field> assignments, when you need recovery-specific
# changes in the rendered configs.

config.section_("General")
config.General.requestName = __REQUEST_NAME__

config.section_("JobType")
config.JobType.pyCfgParams = __DEFAULT_RECOVERY_PYCFG_PARAMS__
config.JobType.numCores = 1
config.JobType.maxMemoryMB = 2000

config.section_("Data")
config.Data.unitsPerJob = 80
config.Data.splitting = __DEFAULT_RECOVERY_SPLITTING__
config.Data.publication = __DEFAULT_RECOVERY_PUBLICATION__
config.Data.lumiMask = __RECOVERY_LUMI_MASK__
config.Data.outputDatasetTag = __DEFAULT_RECOVERY_OUTPUT_DATASET_TAG__
config.Data.ignoreLocality = True
config.Site.whitelist = ["T1_*", "T2_*"]

config.section_("User")
config.section_("Site")
config.Site.storageSite = __DEFAULT_RECOVERY_STORAGE_SITE__
