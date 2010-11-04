import sys, os, tempfile, shutil, time, random, glob
from grid_control import AbstractObject, ConfigError, Job, utils
from wms import WMS
from broker import Broker
from local_api import LocalWMSApi

class LocalWMS(WMS):
	def __init__(self, config, module, monitor):
		WMS.__init__(self, config, module, monitor, 'local')

		wmsapi = config.get('local', 'wms', self._guessWMS())
		if wmsapi != self._guessWMS():
			utils.vprint("Default batch system on this host is: %s" % self._guessWMS(), -1, once = True)
		self.api = LocalWMSApi.open(wmsapi, config, self)
		utils.vprint("Using batch system: %s" % self.api.__class__.__name__, -1)
		self.addAttr = {}
		if config.parser.has_section(wmsapi):
			self.addAttr = dict(map(lambda item: (item, config.get(wmsapi, item)), config.parser.options(wmsapi)))

		broker = config.get('local', 'broker', 'DummyBroker', volatile=True)
		self.broker = Broker.open(broker, config, self.api.getQueues(), self.api.getNodes())

		self.sandPath = config.getPath('local', 'sandbox path', os.path.join(config.workDir, 'sandbox'))
		self.sandCache = []
		self.scratchPath = config.getPath('local', 'scratch path', '', volatile=True)
		self._nameFile = config.getPath('local', 'name source', '', volatile=True)
		self._source = None
		if self._nameFile != '':
			tmp = map(str.strip, open(self._nameFile, 'r').readlines())
			self._source = filter(lambda x: not (x.startswith('#') or x == ''), tmp)


	def _guessWMS(self):
		wmsCmdList = [ ('PBS', 'pbs-config'), ('SGE', 'qsub'), ('LSF', 'bsub'), ('SLURM', 'job_slurm'), ('PBS', 'sh') ]
		for wms, cmd in wmsCmdList:
			try:
				utils.resolveInstallPath(cmd)
				return wms
			except:
				pass


	def getSandboxFiles(self):
		files = WMS.getSandboxFiles(self)
		if self.proxy.getAuthFile():
			files.append(utils.VirtualFile('_proxy.dat', open(self.proxy.getAuthFile(), 'r').read()))
		return files


	# Wait 5 seconds between cycles and 0 seconds between steps
	def getTimings(self):
		return (20, 5)


	def getJobName(self, jobNum):
		if self._source:
			return self._source[jobNum % len(self._source)]
		return self.module.taskID[:10] + "." + str(jobNum) #.rjust(4, "0")[:4]


	def getRequirements(self, jobNum):
		return self.broker.matchQueue(WMS.getRequirements(self, jobNum))


	# Submit job and yield (jobNum, WMS ID, other data)
	def submitJob(self, jobNum):
		# TODO: fancy job name function
		activity = utils.ActivityLog('submitting jobs')

		try:
			if not os.path.exists(self.sandPath):
				os.mkdir(self.sandPath)
			sandbox = tempfile.mkdtemp("", "%s.%04d." % (self.module.taskID, jobNum), self.sandPath)
			for file in self.sandboxIn:
				shutil.copy(file, sandbox)
		except OSError:
			raise RuntimeError("Sandbox path '%s' is not accessible." % self.sandPath)
		except IOError:
			raise RuntimeError("Sandbox '%s' could not be prepared." % sandbox)

		cfgPath = os.path.join(sandbox, '_jobconfig.sh')
		self.writeJobConfig(jobNum, cfgPath, {'GC_SANDBOX': sandbox, 'GC_SCRATCH': self.scratchPath})

		stdout = utils.shellEscape(os.path.join(sandbox, 'gc.stdout'))
		stderr = utils.shellEscape(os.path.join(sandbox, 'gc.stderr'))
		proc = utils.LoggedProcess(self.api.submitExec, "%s %s %s" % (
			self.api.getSubmitArguments(jobNum, sandbox, stdout, stderr, self.addAttr),
			utils.shellEscape(utils.pathGC('share', 'local.sh')),
			self.api.getJobArguments(jobNum, sandbox)))
		retCode = proc.wait()
		wmsIdText = proc.getOutput().strip().strip("\n")
		try:
			wmsId = self.api.parseSubmitOutput(wmsIdText)
		except:
			wmsId = None

		del activity

		if retCode != 0:
			utils.eprint("WARNING: %s failed:" % self.api.submitExec)
		elif wmsId == None:
			utils.eprint("WARNING: %s did not yield job id:\n%s" % (self.api.submitExec, wmsIdText))
		if (wmsId == '') or (wmsId == None):
			wmsId = None
			sys.stderr.write(proc.getError())
		else:
			wmsId = "%s.%s" % (wmsId, self.api.__class__.__name__)
			open(os.path.join(sandbox, wmsId), "w")
		return (jobNum, wmsId, {'sandbox': sandbox})


	# Check status of jobs and yield (wmsID, status, other data)
	def checkJobs(self, ids):
		if not len(ids):
			raise StopIteration

		shortWMSIds = map(lambda (wmsId, jobNum): wmsId.split(".")[0], ids)
		activity = utils.ActivityLog("checking job status")
		proc = utils.LoggedProcess(self.api.statusExec, self.api.getCheckArgument(shortWMSIds))

		tmp = {}
		for data in self.api.parseStatus(proc.iter()):
			# (job number, status, extra info)
			wmsId = "%s.%s" % (data['id'], self.api.__class__.__name__)
			tmp[wmsId] = (wmsId, self.api.parseJobState(data['status']), data)

		for wmsId, jobNum in ids:
			if wmsId not in tmp:
				yield (jobNum, wmsId, Job.DONE, {})
			else:
				yield tuple([jobNum] + list(tmp[wmsId]))

		retCode = proc.wait()
		del activity

		if retCode != 0:
			for line in proc.getError().splitlines():
				if not self.api.unknownID() in line:
					sys.stderr.write(line)


	def getSandbox(self, wmsId):
		# Speed up function by caching result of listdir
		def searchSandbox(source):
			for jobdir in source:
				path = os.path.join(self.sandPath, jobdir)
				if os.path.exists(os.path.join(path, wmsId)):
					return path
		result = searchSandbox(self.sandCache)
		if result:
			return result
		oldCache = self.sandCache[:]
		self.sandCache = filter(lambda x: os.path.isdir(os.path.join(self.sandPath, x)), os.listdir(self.sandPath))
		return searchSandbox(filter(lambda x: x not in oldCache, self.sandCache))


	def getJobsOutput(self, ids):
		if not len(ids):
			raise StopIteration

		activity = utils.ActivityLog("retrieving job outputs")
		for wmsId, jobNum in ids:
			path = self.getSandbox(wmsId)
			if path == None:
				yield (jobNum, None)
				continue

			# Cleanup sandbox
			outFiles = []
			for pat in self.sandboxOut:
				outFiles += glob.glob(os.path.join(path, pat))
			for file in os.listdir(path):
				if os.path.join(path, file) in outFiles:
					continue
				try:
					os.unlink(os.path.join(path, file))
				except:
					pass
			yield (jobNum, path)
		del activity


	def cancelJobs(self, ids):
		if not len(ids):
			raise StopIteration

		activity = utils.ActivityLog("cancelling jobs")
		shortWMSIds = map(lambda (wmsId, jobNum): wmsId.split(".")[0], ids)
		proc = utils.LoggedProcess(self.api.cancelExec, self.api.getCancelArgument(shortWMSIds))
		if proc.wait() != 0:
			for line in proc.getError().splitlines():
				if not self.api.unknownID() in line:
					sys.stderr.write(line)
		del activity

		activity = utils.ActivityLog("waiting for jobs to finish")
		time.sleep(5)
		for wmsId, jobNum in ids:
			path = self.getSandbox(wmsId)
			if path == None:
				utils.eprint("Sandbox for job %d with wmsId '%s' could not be found" % (jobNum, wmsId))
				continue
			try:
				shutil.rmtree(path)
			except:
				raise RuntimeError("Sandbox for job %d with wmsId '%s' could not be deleted" % (jobNum, wmsId))
			yield (wmsId, jobNum)
		del activity
