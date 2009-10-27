#!/usr/bin/env python
import sys, os, re, fcntl

# add python subdirectory from where exec was started to search path
root = os.path.dirname(os.path.abspath(os.path.normpath(os.path.join(sys.argv[0], '..'))))
sys.path.insert(0, os.path.join(root, 'python'))

from grid_control import *
utils.verbosity.setting = 0
utils.atRoot.root = root

class DummyStream(object):
	def __init__(self, stream):
		self.__stream = stream
		self.log = []
	def write(self, data):
		self.log.append(data)
		return True
	def __getattr__(self, name):
		return self.__stream.__getattribute__(name)


class Silencer(object):
	def __init__(self):
		self.saved = (sys.stdout, sys.stderr)
		sys.stdout = DummyStream(sys.stdout)
		sys.stderr = DummyStream(sys.stderr)
	def __del__(self):
		del sys.stdout
		del sys.stderr
		(sys.stdout, sys.stderr) = self.saved


class ConfigDummy(object):
	def __init__(self, cfg = {}):
		self.cfg = cfg
	def get(self, x,y,z,volatile=None):
		return self.cfg.get(x, {}).get(y, z)
	def getPath(self, x,y,z,volatile=None):
		return self.cfg.get(x, {}).get(y, z)
	def getBool(self, x,y,z,volatile=None):
		return self.cfg.get(x, {}).get(y, z)


class FileMutex:
	def __init__(self, lockfile):
		#log = utils.ActivityLog('Trying to aquire lock file %s...' % lockfile)
		self.lockfile = lockfile
		self.fd = open(self.lockfile, 'w')
		fcntl.flock(self.fd, fcntl.LOCK_EX)
		#del log

	def __del__(self):
		fcntl.flock(self.fd, fcntl.LOCK_UN)
		try:
			if os.path.exists(self.lockfile):
				os.unlink(self.lockfile)
		except:
			pass


def getJobs(workDir):
	idregex = re.compile(r'^job_([0-9]+)$')
	return map(lambda x: int(idregex.match(x).group(1)), os.listdir(os.path.join(workDir, 'output')))


def getWorkJobs(args):
	if len(args) == 2:
		(configFile, jobid) = args
		config = Config(configFile)
		workDir = config.getPath('global', 'workdir', config.workDirDefault)
		jobList = [ jobid ]
	elif len(args) == 1:
		configFile = args[0]
		config = Config(configFile)
		workDir = config.getPath('global', 'workdir', config.workDirDefault)
		jobList = getJobs(workDir)
	else:
		sys.stderr.write("Syntax: %s <config file> [<job id>]\n\n" % sys.argv[0])
		sys.exit(1)
	return (workDir, jobList)


def getJobInfo(workDir, jobNum, retCodeFilter = lambda x: True):
	jobInfoPath = os.path.join(workDir, 'output', 'job_%d' % jobNum, 'job.info')
	try:
		jobInfo = utils.DictFormat('=').parse(open(jobInfoPath))
		if retCodeFilter(jobInfo.get('exitcode', -1)):
			return jobInfo
	except:
		print "Unable to read job results from %s!" % jobInfoPath
	return None


def getFileInfo(workDir, jobNum, retCodeFilter = lambda x: True, rejected = None):
	jobInfo = getJobInfo(workDir, jobNum, retCodeFilter)
	if not jobInfo:
		return rejected

	files = filter(lambda x: x[0].startswith('file'), jobInfo.items())
	return map(lambda (x,y): tuple(y.strip('"').split('  ')), files)
