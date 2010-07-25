from grid_control import AbstractObject, AbstractError

class LocalWMSApi(AbstractObject):
	def __init__(self, config, localWMS):
		self.wms = localWMS

	def getQueues(self):
		return None

	def getNodes(self):
		return None

	def getArguments(self, jobNum, sandbox):
		raise AbstractError

	def getSubmitArguments(self, jobNum, sandbox, stdout, stderr):
		raise AbstractError

	def parseSubmitOutput(self, data):
		raise AbstractError

	def unknownID(self):
		raise AbstractError

	def parseStatus(self, status):
		raise AbstractError

	def getCheckArgument(self, wmsIds):
		raise AbstractError

	def parseJobState(self, state):
		return self._statusMap[state]

	def getCancelArgument(self, wmsIds):
		return str.join(" ", wmsIds)

	def checkReq(self, reqs, req, test = lambda x: x > 0):
		if req in reqs:
			return test(reqs[req])
		return False

LocalWMSApi.dynamicLoaderPath()
