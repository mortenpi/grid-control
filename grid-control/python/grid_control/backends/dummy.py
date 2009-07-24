from __future__ import generators
import sys, os, time, copy, popen2, tempfile, cStringIO, random
from grid_control import ConfigError, Job, utils
from wms import WMS

class DummyWMS(WMS):
	def __init__(self, config, opts, module):
		WMS.__init__(self, config, opts, module, 'grid')
		self.mapNum2ID = {}

	def submitJob(self, jobNum):
		print "EVENT [SUBMIT]: ", jobNum
		self.mapNum2ID[jobNum] = random.randint(0, 10000000)
		return (jobNum, self.mapNum2ID[jobNum], {})


	def checkJobs(self, ids):
		print "EVENT [CHECK]: ", ids
		return map(lambda wmsId, jobNum: (jobNum, wmsId, Job.QUEUED, {}), ids.items())


	def getJobsOutput(self, ids):
		print "EVENT [OUTPUT]: ", ids
		return []


	def cancelJobs(self, ids):
		print "EVENT [CANCEL]: ", ids
		return True
