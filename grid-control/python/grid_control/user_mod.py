import os.path, random, time
from grid_control import Module

class UserMod(Module):
	def __init__(self, config):
		Module.__init__(self, config)
		self._executable = config.getPath('UserMod', 'executable')
		self._arguments = config.get('UserMod', 'arguments', '')


	def getCommand(self):
		cmd = os.path.basename(self._executable)
		return 'chmod u+x %s; ./%s $@' % (cmd, cmd)


	def getJobArguments(self, jobNum):
		return self._arguments


	def getInFiles(self):
		return Module.getInFiles(self) + [ self._executable ]
