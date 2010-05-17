
import FWCore.ParameterSet.Config as cms
from IOMC.RandomEngine.RandomServiceHelper import RandomNumberServiceHelper

def customise_for_gc(process):
	try:
		maxevents = __MAX_EVENTS__
		process.maxEvents = cms.untracked.PSet(
			input = cms.untracked.int32(max(-1, maxevents))
		)
	except:
		pass

	# Dataset related setup
	try:
		tmp = __SKIP_EVENTS__
		process.source = cms.Source("PoolSource",
			skipEvents = cms.untracked.uint32(__SKIP_EVENTS__),
			fileNames = cms.untracked.vstring(__FILE_NAMES__)
		)
		try:
			secondary = __FILE_NAMES2__
			process.source.secondaryFileNames = cms.untracked.vstring(secondary)
		except:
			pass
		try:
			lumirange = [__LUMI_RANGE__]
			process.source.lumisToProcess = cms.untracked.VLuminosityBlockRange(lumirange)
		except:
			pass
	except:
		pass

	if hasattr(process, "RandomNumberGeneratorService"):
		randSvc = RandomNumberServiceHelper(process.RandomNumberGeneratorService)
		randSvc.populate()

	process.AdaptorConfig = cms.Service("AdaptorConfig",
		enable = cms.untracked.bool(True),
		stats = cms.untracked.bool(True),
	)

	# Generator related setup
	try:
		if hasattr(process, "generator"):
			process.source.firstLuminosityBlock = cms.untracked.uint32(1+__MY_JOBID__)
			print "Generator random seed:", process.RandomNumberGeneratorService.generator.initialSeed
	except:
		pass

	return (process)

process = customise_for_gc(process)

# grid-control: https://ekptrac.physik.uni-karlsruhe.de/trac/grid-control
