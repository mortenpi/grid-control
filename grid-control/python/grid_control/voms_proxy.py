import os, time, popen2
from grid_control import InstallationError, Proxy

class VomsProxy(Proxy):
	def __init__(self):
		Proxy.__init__(self)
		self._infoExec = self._find('voms-proxy-info')
		self._info = None


	# Look for a program in the PATH environment variable
	def _find(self,program):
		try:
			path = os.environ['PATH'].split(':')
		except:
			# Hmm, something really wrong
			path = ['/bin', '/usr/bin', '/usr/local/bin']

		for dir in path:
			fname = os.path.join(dir, program)
			if os.path.exists(fname):
				return fname
		raise InstallationError("voms-proxy-info not found")


	# Call voms-proxy-info and returns results
	def _getInfo(self):
		proc = popen2.Popen3(self._infoExec, True)
		lines = proc.fromchild.readlines()
		retCode = proc.wait()

		if retCode != 0:
			raise InstallationError("voms-proxy-info failed")

		data = {}
		for line in lines:
			try:
				# split at first occurence of ':'
				# and strip spaces around
				key, value = map(lambda x: x.strip(), 
				                 line.split(':', 1))
			except:
				# in case no ':' was found
				continue

			data[key.lower()] = value

		return data


	# return possibly cached information
	def getInfo(self, recheck = False):
		if self._info == None or recheck:
			self._info = self._getInfo()
			self._info['time'] = time.time()
		return self._info


	def timeleft(self, critical = None):
		if critical == None:
			critical = self._critical

		info = self.getInfo()
		# time elapsed since last call to voms-proxy-info
		delta = time.time() - info['time']

		while True:
			# split ##:##:## into [##, ##, ##] and convert to integers
			timeleft = map(int, info['timeleft'].split(':'))
			# multiply from left with 60 and add right component
			# result is in seconds
			timeleft = reduce(lambda x, y: x * 60 + y, timeleft)

			# subtract time since last call to voms-proxy-info
			timeleft -= delta
			if timeleft < 0:
				timeleft = 0

			# recheck proxy if critical timeleft reached
			# at most once per minute
			if timeleft < critical and delta > 60:
				info = self.getInfo(True)
				continue

			break # leave while loop

		return timeleft
