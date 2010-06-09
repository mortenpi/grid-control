import os, threading
from grid_control import AbstractObject, Job

class Monitoring(AbstractObject):
	# Read configuration options and init vars
	def __init__(self, config, module):
		self.config = config
		self.module = module

	def getEnv(self, wms):
		return {}

	def getFiles(self):
		return []

	def onJobSubmit(self, wms, jobObj, jobNum):
		pass

	def onJobUpdate(self, wms, jobObj, jobNum, data):
		pass

	def onJobOutput(self, wms, jobObj, jobNum, retCode):
		pass

	def onTaskFinish(self, nJobs):
		pass

Monitoring.dynamicLoaderPath()
Monitoring.moduleMap["scripts"] = "ScriptMonitoring"

class ScriptMonitoring(Monitoring):
	def __init__(self, config, module):
		Monitoring.__init__(self, config, module)
		self.evtSubmit = config.get('events', 'on submit', '', volatile=True)
		self.evtStatus = config.get('events', 'on status', '', volatile=True)
		self.evtOutput = config.get('events', 'on output', '', volatile=True)
		self.evtFinish = config.get('events', 'on finish', '', volatile=True)

	# Get both task and job config / state dicts
	def setEventEnviron(self, jobObj, jobNum):
		tmp = {}
		tmp.update(self.module.getTaskConfig())
		tmp.update(self.module.getJobConfig(jobNum))
		tmp.update(self.module.getSubmitInfo(jobNum))
		tmp.update(jobObj.getAll())
		tmp.update({'WORKDIR': self.config.workDir})
		for key, value in tmp.iteritems():
			os.environ["GC_%s" % key] = str(value)

	# Called on job submission
	def onJobSubmit(self, wms, jobObj, jobNum):
		if self.evtSubmit != '':
			self.setEventEnviron(jobObj, jobNum)
			params = "%s %d %s" % (self.evtSubmit, jobNum, jobObj.wmsId)
			threading.Thread(target = os.system, args = (params,)).start()

	# Called on job status update
	def onJobUpdate(self, wms, jobObj, jobNum, data):
		if self.evtStatus != '':
			self.setEventEnviron(jobObj, jobNum)
			params = "%s %d %s %s" % (self.evtStatus, jobNum, jobObj.wmsId, Job.states[jobObj.state])
			threading.Thread(target = os.system, args = (params,)).start()

	# Called on job status update
	def onJobOutput(self, wms, jobObj, jobNum, retCode):
		if self.evtOutput != '':
			self.setEventEnviron(jobObj, jobNum)
			params = "%s %d %s %d" % (self.evtOutput, jobNum, jobObj.wmsId, retCode)
			threading.Thread(target = os.system, args = (params,)).start()

	# Called at the end of the task
	def onTaskFinish(self, nJobs):
		if self.evtFinish != '':
			params = "%s %d" % (self.evtFinish, nJobs)
			threading.Thread(target = os.system, args = (params,)).start()


class MonitoringMultiplexer(Monitoring):
	def __init__(self, config, module, submodules):
		Monitoring.__init__(self, config, module)
		submodules = map(str.strip, submodules.split(","))
		self.submodules = map(lambda x: Monitoring.open(x, config, module), submodules)

	def onJobSubmit(self, wms, jobObj, jobNum):
		for submodule in self.submodules:
			submodule.onJobSubmit(wms, jobObj, jobNum)

	def onJobUpdate(self, wms, jobObj, jobNum, data):
		for submodule in self.submodules:
			submodule.onJobUpdate(wms, jobObj, jobNum, data)

	def onJobOutput(self, wms, jobObj, jobNum, retCode):
		for submodule in self.submodules:
			submodule.onJobOutput(wms, jobObj, jobNum, retCode)

	def onTaskFinish(self, nJobs):
		for submodule in self.submodules:
			submodule.onTaskFinish(nJobs)
