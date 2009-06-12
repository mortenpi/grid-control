import os, copy, string, re, sys, tarfile
from xml.dom import minidom
from grid_control import ConfigError, Module, WMS, utils
from provider_base import DataProvider
from splitter_base import DataSplitter
from DashboardAPI import DashboardAPI
from time import time, localtime, strftime

class CMSSW(Module):
	def __init__(self, config, init, resync):
		Module.__init__(self, config, init, resync)

		# SCRAM info
		scramProject = config.get('CMSSW', 'scram project', '').split()
		if len(scramProject):
			self.projectArea = config.getPath('CMSSW', 'project area', '')
			if len(self.projectArea):
				raise ConfigError('Cannot specify both SCRAM project and project area')
			if len(scramProject) != 2:
				raise ConfigError('SCRAM project needs exactly 2 arguments: PROJECT VERSION')
		else:
			self.projectArea = config.getPath('CMSSW', 'project area')
		self.scramArch = config.get('CMSSW', 'scram arch')
		self.scramVersion = config.get('CMSSW', 'scram version', 'scramv1')

		self.configFile = config.getPath('CMSSW', 'config file')

		self.dataset = config.get('CMSSW', 'dataset', '').strip()
		if self.dataset == '':
			self.dataset = None
			self.eventsPerJob = config.getInt('CMSSW', 'events per job', 0)
		else:
			self.eventsPerJob = config.getInt('CMSSW', 'events per job')
			configFileContent = open(self.configFile, 'r').read()
			for tag in ["__FILE_NAMES__", "__MAX_EVENTS__", "__SKIP_EVENTS__"]:
				if configFileContent.find(tag) == -1:
					print open(utils.atRoot('share', 'fail.txt'), 'r').read()
					print "Config file must use __FILE_NAMES__, __MAX_EVENTS__ and __SKIP_EVENTS__ to work properly with datasets!"
					break

		self.gzipOut = config.getBool('CMSSW', 'gzip output', True)
		self.useReqs = config.getBool('CMSSW', 'use requirements', True)
		self.seRuntime = config.getBool('CMSSW', 'se runtime', False)

		if self.seRuntime and len(self.projectArea):
			self.seInputFiles.append(self.taskID + ".tar.gz"),

		if len(self.projectArea):
			self.pattern = config.get('CMSSW', 'area files', '-.* -config lib module */data *.xml *.sql *.cf[if] *.py').split()

			if os.path.exists(self.projectArea):
				print "Project area found in: %s" % self.projectArea
			else:
				raise ConfigError("Specified config area '%s' does not exist!" % self.projectArea)

			# try to open it
			try:
				fp = open(os.path.join(self.projectArea, '.SCRAM', 'Environment'), 'r')
				self.scramEnv = utils.DictFormat().parse(fp, lowerCaseKey = False)
			except:
				raise ConfigError("Project area file .SCRAM/Environment cannot be parsed!")

			for key in ['SCRAM_PROJECTNAME', 'SCRAM_PROJECTVERSION']:
				if not self.scramEnv.has_key(key):
					raise ConfigError("Installed program in project area can't be recognized.")

			try:
				fp = open(os.path.join(self.projectArea, '.SCRAM', self.scramArch, 'Environment'), 'r')
				self.scramEnv.update(utils.DictFormat().parse(fp, lowerCaseKey = False))
			except:
				print "Project area file .SCRAM/%s/Environment cannot be parsed!" % self.scramArch
		else:
			self.scramEnv = {
				'SCRAM_PROJECTNAME': scramProject[0],
				'SCRAM_PROJECTVERSION': scramProject[1]
			}
		if self.scramEnv['SCRAM_PROJECTNAME'] != 'CMSSW':
			raise ConfigError("Project area not a valid CMSSW project area.")

		if not os.path.exists(self.configFile):
			raise ConfigError("Config file '%s' not found." % self.configFile)

		self.datasplitter = None
		if init:
			self._initTask(config)
		elif self.dataset != None:
			self.datasplitter = DataSplitter.loadState(self.workDir)
			if resync:
				old = DataProvider.loadState(self.workDir)
				new = DataProvider.create(config)
				self.datasplitter.resyncMapping(self.workDir, old.getBlocks(), new.getBlocks())
				#TODO: new.saveState(self.workDir)


	def _initTask(self, config):
		if len(self.projectArea):
			utils.genTarball(os.path.join(self.workDir, 'runtime.tar.gz'), self.projectArea, self.pattern)

			if self.seRuntime:
				print 'Copy CMSSW runtime to SE',
				sys.stdout.flush()
				source = 'file:///' + os.path.join(self.workDir, 'runtime.tar.gz')
				target = os.path.join(self.sePath, self.taskID + '.tar.gz')
				if utils.se_copy(source, target, config.getBool('CMSSW', 'se runtime force', True)):
					print 'finished'
				else:
					print 'failed'
					raise RuntimeError("Unable to copy runtime!")

		# find and split datasets
		if self.dataset != None:
			self.dataprovider = DataProvider.create(config)
			self.dataprovider.saveState(self.workDir)
			if utils.verbosity() > 0:
				self.dataprovider.printDataset()

			splitter = config.get('CMSSW', 'dataset splitter', 'DefaultSplitter')
			self.datasplitter = DataSplitter.open(splitter, { "eventsPerJob": self.eventsPerJob })
			self.datasplitter.splitDataset(self.dataprovider.getBlocks())
			self.datasplitter.saveState(self.workDir)
			if utils.verbosity() > 1:
				self.datasplitter.printAllJobInfo()


	# Called on job submission
	def onJobSubmit(self, job, id):
		Module.onJobSubmit(self, job, id)

		if self.dashboard:
			dbsinfo = {}
			if self.datasplitter:
				dbsinfo = self.datasplitter.getSplitInfo(id)

			dashboard = DashboardAPI(self.taskID, "%s_%s" % (id, job.id))
			dashboard.publish(
				taskId=self.taskID, jobId="%s_%s" % (id, job.id), sid="%s_%s" % (id, job.id),
				application=self.scramEnv['SCRAM_PROJECTVERSION'], exe="cmsRun",
				nevtJob=dbsinfo.get(DataSplitter.NEvents, self.eventsPerJob),
				tool="grid-control", GridName=self.username,
				scheduler="gLite", taskType="analysis", vo=self.config.get('grid', 'vo', ''),
				datasetFull=dbsinfo.get('DatasetPath', ''), user=os.environ['LOGNAME']
			)
		return None


	# Called on job status update
	def onJobUpdate(self, job, id, data):
		Module.onJobUpdate(self, job, id, data)

		if self.dashboard:
			dashboard = DashboardAPI(self.taskID, "%s_%s" % (id, job.id))
			dashboard.publish(
				taskId=self.taskID, jobId="%s_%s" % (id, job.id), sid="%s_%s" % (id, job.id),
				StatusValue=data.get('status', 'pending').upper(),
				StatusValueReason=data.get('reason', data.get('status', 'pending')).upper(),
				StatusEnterTime=data.get('timestamp', strftime("%Y-%m-%d_%H:%M:%S", localtime())),
				StatusDestination=data.get('dest', "")
			)
		return None


	# Get environment variables for gc_config.sh
	def getTaskConfig(self):
		data = Module.getTaskConfig(self)
		data['CMSSW_CONFIG'] = os.path.basename(self.configFile)
		data['CMSSW_RELEASE_BASE_OLD'] = self.scramEnv.get('RELEASETOP', None)
		data['SCRAM_VERSION'] = self.scramVersion
		data['SCRAM_ARCH'] = self.scramArch
		data['SCRAM_PROJECTVERSION'] = self.scramEnv['SCRAM_PROJECTVERSION']
		data['GZIP_OUT'] = ('no', 'yes')[self.gzipOut]
		data['SE_RUNTIME'] = ('no', 'yes')[self.seRuntime]
		data['HAS_RUNTIME'] = ('no', 'yes')[len(self.projectArea) != 0]
		return data


	# Get job dependent environment variables
	def getJobConfig(self, job):
		data = Module.getJobConfig(self, job)
		if not self.datasplitter:
			return data

		dbsinfo = self.datasplitter.getSplitInfo(job)
		data['DATASETID'] = dbsinfo.get(DataSplitter.DatasetID, None)
		data['DATASETPATH'] = dbsinfo.get(DataSplitter.Dataset, None)
		data['DATASETNICK'] = dbsinfo.get(DataSplitter.Nickname, None)
		return data


	# Get job requirements
	def getRequirements(self, job):
		reqs = Module.getRequirements(self, job)
		if self.useReqs:
			reqs.append((WMS.MEMBER, 'VO-cms-%s' % self.scramEnv['SCRAM_PROJECTVERSION']))
			reqs.append((WMS.MEMBER, 'VO-cms-%s' % self.scramArch))
		if self.datasplitter != None:
			reqs.append((WMS.STORAGE, self.datasplitter.getSitesForJob(job)))
		return reqs


	# Get files for input sandbox
	def getInFiles(self):
		files = Module.getInFiles(self)
		if len(self.projectArea) and not self.seRuntime:
			files.append('runtime.tar.gz')
		files.append(utils.atRoot('share', 'run.cmssw.sh')),
		files.append(self.configFile)

		if self.dashboard:
			for file in ('DashboardAPI.py', 'Logger.py', 'ProcInfo.py', 'apmon.py', 'report.py'):
				files.append(utils.atRoot('python/DashboardAPI', file))
		return files


	# Get files for output sandbox
	def getOutFiles(self):
		files = Module.getOutFiles(self)
		cfgFile = os.path.basename(self.configFile)
		files.append('CMSRUN-' + cfgFile.replace('.cfg', '.xml.gz').replace('.py', '.xml.gz'))
		if self.gzipOut:
			files.append('cmssw_out.txt.gz')
		return files


	def getCommand(self):
		return './run.cmssw.sh "$@"'


	def getJobArguments(self, job):
		if self.datasplitter == None:
			return str(self.eventsPerJob)

		print "Job number: %d" % job
		datafiles = self.datasplitter.getSplitInfo(job)
		DataSplitter.printInfoForJob(datafiles)
		return "%d %d %s" % (
			datafiles[DataSplitter.NEvents],
			datafiles[DataSplitter.Skipped],
			str.join(' ', datafiles[DataSplitter.FileList])
		)


	def getMaxJobs(self):
		if self.datasplitter == None:
			raise ConfigError('Must specifiy number of jobs or dataset!')
		return self.datasplitter.getNumberOfJobs()
