from __future__ import generators
import sys, os, popen2, tempfile, shutil, time
from grid_control import ConfigError, Job, utils
from wms import WMS

class LocalWMS(WMS):
	def __init__(self, config, module, init):
		WMS.__init__(self, config, module, 'local', init)

		self.sandPath = config.getPath('local', 'sandbox path', os.path.join(self.workDir, 'sandbox'))
		self._nameFile = config.getPath('local', 'name source', '')
		self._source = None
		if self._nameFile != '':
			tmp = map(str.strip, open(self._nameFile, 'r').readlines())
			self._source = filter(lambda x: not (x.startswith('#') or x == ''), tmp)


	def guessWMS():
		wmsCmdList = [ ('PBS', 'pbs-config'), ('SGE', 'qsub'), ('LSF', 'bsub'), ('SLURM', 'job_slurm'), ('PBS', 'sh') ]
		for wms, cmd in wmsCmdList:
			try:
				utils.searchPathFind(cmd)
				print "Default batch system on this host is: %s" % wms
				return wms
			except:
				pass
	guessWMS = staticmethod(guessWMS)


	def getJobName(self, taskId, jobId):
		if self._source:
			return self._source[jobId % len(self._source)]
		return taskId[:10] + "." + str(jobId) #.rjust(4, "0")[:4]

	def getArguments(self, jobNum, sandbox):
		raise AbstractError

	def getSubmitArguments(self, jobNum, sandbox):
		raise AbstractError

	def parseSubmitOutput(self, data):
		raise AbstractError

	def unknownID(self):
		raise AbstracError


	def submitJob(self, jobNum, jobObj):
		# TODO: fancy job name function
		activity = utils.ActivityLog('submitting jobs')

		try:
			if not os.path.exists(self.sandPath):
				os.mkdir(self.sandPath)
			sandbox = tempfile.mkdtemp("", "%s.%04d." % (self.module.taskID, jobNum), self.sandPath)
			for file in self.sandboxIn:
				shutil.copy(file, sandbox)
			jobObj.set('sandbox', sandbox)
		except OSError:
			raise RuntimeError("Sandbox path '%s' is not accessible." % self.sandPath)
		except IOError:
			raise RuntimeError("Sandbox '%s' could not be prepared." % sandbox)

		env_vars = {
			'ARGS': utils.shellEscape("%d %s" % (jobNum, self.module.getJobArguments(jobNum))),
			'SANDBOX': sandbox
		}
		env_vars.update(self.module.getJobConfig(jobNum))

		jcfg = open(os.path.join(sandbox, 'jobconfig.sh'), 'w')
		jcfg.writelines(utils.DictFormat().format(env_vars))
		proc = popen2.Popen3("%s %s %s %s" % (self.submitExec,
			self.getSubmitArguments(jobNum, sandbox),
			utils.shellEscape(utils.atRoot('share', 'local.sh')),
			self.getArguments(jobNum, sandbox)), True)

		wmsIdText = proc.fromchild.read().strip().strip("\n")
		try:
			wmsId = self.parseSubmitOutput(wmsIdText)
		except:
			wmsId = None
		retCode = proc.wait()

		del activity

		if retCode != 0:
			print >> sys.stderr, "WARNING: %s failed:" % self.submitExec
		elif wmsId == None:
			print >> sys.stderr, "WARNING: %s did not yield job id:" % self.submitExec
			print >> sys.stderr,  wmsIdText

		if (wmsId == '') or (wmsId == None):
			sys.stderr.write(proc.childerr.read())
		else:
			open(os.path.join(sandbox, wmsId), "w")
		return wmsId


	def parseStatus(self, status):
		raise RuntimeError('parseStatus is abstract')


	def getCheckArgument(self, wmsIds):
		raise RuntimeError('getCheckArgument is abstract')


	def checkJobs(self, wmsIds):
		if not len(wmsIds):
			return []

		shortWMSIds = map(lambda x: x.split(".")[0], wmsIds)
		activity = utils.ActivityLog("checking job status")
		proc = popen2.Popen3("%s %s" % (self.statusExec, self.getCheckArgument(shortWMSIds)), True)

		tmp = {}
		jobstatusinfo = proc.fromchild.read()
		for data in self.parseStatus(jobstatusinfo):
			# (job number, status, extra info)
			tmp[data['id']] = (data['id'], self._statusMap[data['status']], data)

		result = []
		for wmsId in wmsIds:
			if not tmp.has_key(wmsId):
				result.append((wmsId, Job.DONE, {}))
			else:
				result.append(tmp[wmsId])

		retCode = proc.wait()
		del activity

		if retCode != 0:
			for line in proc.childerr.readlines():
				if not self.unknownID() in line:
					sys.stderr.write(line)

		return result


	def getSandbox(self, wmsId):
		for jobdir in os.listdir(self.sandPath):
			path = os.path.join(self.sandPath, jobdir)
			if os.path.isdir(path):
				if wmsId in os.listdir(path):
					return path
		return None


	def getJobsOutput(self, wmsIds):
		if not len(wmsIds):
			return []

		result = []
		activity = utils.ActivityLog("retrieving job outputs")

		for wmsId in wmsIds:
			path = self.getSandbox(wmsId)
			if path == None:
				raise RuntimeError("Sandbox for wmsId '%s' could not be found" % wmsId)

			# Cleanup sandbox
			for file in os.listdir(path):
				if file in self.sandboxOut:
					continue
				if file == wmsId:
					continue
				try:
					os.unlink(os.path.join(path, file))
				except:
					pass
			result.append(path)

		del activity
		return result


	def getCancelArgument(self, wmsIds):
		return str.join(" ", wmsIds)


	def cancelJobs(self, wmsIds):
		if not len(wmsIds):
			return True

		activity = utils.ActivityLog("cancelling jobs")

		shortWMSIds = map(lambda x: x.split(".")[0], wmsIds)
		proc = popen2.Popen3("%s %s" % (self.cancelExec, self.getCancelArgument(shortWMSIds)), True)
		retCode = proc.wait()

		if retCode != 0:
			for line in proc.childerr.readlines():
				if not self.unknownID() in line:
					sys.stderr.write(line)

		del activity
		activity = utils.ActivityLog("waiting for jobs to finish")
		# Wait for jobs to finish
		time.sleep(5)
		for wmsId in wmsIds:
			path = self.getSandbox(wmsId)
			if path == None:
				print RuntimeError("Sandbox for wmsId '%s' could not be found" % wmsId)
				continue
			try:
				shutil.rmtree(path)
			except:
				raise RuntimeError("Sandbox for wmsId '%s' could not be deleted" % wmsId)

		del activity
		return True
