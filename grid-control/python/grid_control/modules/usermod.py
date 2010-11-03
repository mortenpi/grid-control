import os.path
from grid_control import QM, datasets
from grid_control.datasets import DataMod

class UserMod(DataMod):
	def __init__(self, config):
		DataMod.__init__(self, config)
		self._sendexec = config.getBool(self.__class__.__name__, 'send executable', True)
		if self._sendexec:
			self._executable = config.getPath(self.__class__.__name__, 'executable')
		else:
			self._executable = config.get(self.__class__.__name__, 'executable')
		self._arguments = config.get(self.__class__.__name__, 'arguments', '')


	def getCommand(self):
		if self._sendexec:
			cmd = os.path.basename(self._executable)
			return 'chmod u+x %s; ./%s $@ > job.stdout 2> job.stderr' % (cmd, cmd)
		return '%s $@ > job.stdout 2> job.stderr' % self._executable


	def getJobArguments(self, jobNum):
		return DataMod.getJobArguments(self, jobNum) + ' ' + self._arguments


	def getInFiles(self):
		return DataMod.getInFiles(self) + QM(self._sendexec, [self._executable], [])


	def getOutFiles(self):
		tmp = map(lambda s: s + QM(self.gzipOut, '.gz', ''), ['job.stdout', 'job.stderr'])
		return DataMod.getOutFiles(self) + tmp
