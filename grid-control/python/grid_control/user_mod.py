import os.path, random, time
from grid_control import DataMod

class UserMod(DataMod):
	def __init__(self, config):
		DataMod.__init__(self, config)
		self._executable = config.getPath('UserMod', 'executable')
		self._arguments = config.get('UserMod', 'arguments', '')


	def getCommand(self):
		cmd = os.path.basename(self._executable)
		return 'chmod u+x %s; ./%s $@ > job.stdout 2> job.stderr' % (cmd, cmd)


	def getJobArguments(self, jobNum):
		return DataMod.getJobArguments(self, jobNum) + " " + self._arguments


	def getInFiles(self):
		return DataMod.getInFiles(self) + [ self._executable ]


	def getOutFiles(self):
		return DataMod.getOutFiles(self) + [ 'job.stdout', 'job.stderr' ]
