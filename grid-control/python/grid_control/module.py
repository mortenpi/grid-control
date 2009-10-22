# Generic base class for job modules
# instantiates named class instead (default is UserMod)

import os, random, threading
from grid_control import ConfigError, AbstractError, AbstractObject, utils, WMS, Job
from time import time, localtime, strftime

class Module(AbstractObject):
	# Read configuration options and init vars
	def __init__(self, config):
		self.config = config

		wallTime = config.get('jobs', 'wall time', volatile=True)
		self.wallTime = utils.parseTime(wallTime)
		self.cpuTime = utils.parseTime(config.get('jobs', 'cpu time', wallTime, volatile=True))
		self.nodeTimeout = utils.parseTime(config.get('jobs', 'node timeout', ''))

		self.memory = config.getInt('jobs', 'memory', 512, volatile=True)

		# Try to read task info file
		taskInfo = utils.PersistentDict(os.path.join(self.config.workDir, 'task.dat'), ' = ')

		# Compute / get task ID
		self.taskID = taskInfo.get('task id', 'GC' + utils.md5(str(time())).hexdigest()[:12])
		utils.vprint('Current task ID: %s' % self.taskID, -1, once = True)

		# Set random seeds (args override config)
		seedarg = config.get('jobs', 'seeds', '')
		if config.opts.seed != None:
			seedarg = config.opts.seed.rstrip('S')
		if seedarg != '':
			self.seeds = map(int, seedarg.split(','))
		else:
			# args specified => gen seeds
			if 'seeds' in taskInfo and (config.opts.seed == None):
				self.seeds = map(int, taskInfo['seeds'].split())
			else:
				self.seeds = map(lambda x: random.randint(0, 10000000), range(10))
				print "Creating random seeds...", self.seeds

		# Write task info file
		taskInfo.write({'task id': self.taskID, 'seeds': str.join(' ', map(str, self.seeds))})

		self.seSDUpperLimit = config.getInt('storage', 'scratch space used', 5000)
		self.seSDLowerLimit = config.getInt('storage', 'scratch space left', 1)
		self.seLZUpperLimit = config.getInt('storage', 'landing zone space used', 100)
		self.seLZLowerLimit = config.getInt('storage', 'landing zone space left', 1)

		# Storage setup - in case a directory is give, prepend dir specifier
		self.sePath = config.get('storage', 'se path', '').strip()
		if len(self.sePath) > 0 and self.sePath[0] == "/":
			self.sePath = "dir:///%s" % self.sePath.lstrip("/")
		self.seMinSize = config.getInt('storage', 'se min size', -1)

		self.seInputFiles = config.get('storage', 'se input files', '').split()
		self.seInputPattern = config.get('storage', 'se input pattern', '__X__')
		self.seOutputFiles = config.get('storage', 'se output files', '').split()
		self.seOutputPattern = config.get('storage', 'se output pattern', '@NICK@job_@MY_JOBID@_@X@')

		self.sbInputFiles = config.get(self.__class__.__name__, 'input files', '').split()
		self.sbOutputFiles = config.get(self.__class__.__name__, 'output files', '').split()
		self.substFiles = config.get(self.__class__.__name__, 'subst files', '').split()

		self.dependencies = config.get(self.__class__.__name__, 'depends', '').lower().split()
		if self.sePath and not self.sePath.startswith('dir'):
			self.dependencies.append('glite')

		if config.get('CMSSW', 'se output files', 'DEPRECATED') != 'DEPRECATED':
			utils.deprecated("Please specify se output files only in the [storage] section")
			self.seOutputFiles = config.get('CMSSW', 'se output files').split()
		if config.get('CMSSW', 'seeds', 'DEPRECATED') != 'DEPRECATED':
			utils.deprecated("Please specify seeds only in the [jobs] section")
			self.setSeed(str.join(',', config.get('CMSSW', 'seeds').split()))
		if config.get('CMSSW', 'se path', 'DEPRECATED') != 'DEPRECATED':
			utils.deprecated("Please specify se path only in the [storage] section")
			self.sePath = config.get('CMSSW', 'se path')


	# Get environment variables for gc_config.sh
	def getTaskConfig(self):
		return {
			# Space limits
			'SCRATCH_UL' : self.seSDUpperLimit,
			'SCRATCH_LL' : self.seSDLowerLimit,
			'LANDINGZONE_UL': self.seLZUpperLimit,
			'LANDINGZONE_LL': self.seLZLowerLimit,
			# Storage element
			'SE_PATH': self.sePath,
			'SE_MINFILESIZE': self.seMinSize,
			'SE_OUTPUT_FILES': str.join(' ', self.seOutputFiles),
			'SE_INPUT_FILES': str.join(' ', self.seInputFiles),
			'SE_OUTPUT_PATTERN': self.seOutputPattern,
			'SE_INPUT_PATTERN': self.seInputPattern,
			# Sandbox
			'SB_OUTPUT_FILES': str.join(' ', self.getOutFiles()),
			'SB_INPUT_FILES': str.join(' ', map(lambda x: utils.shellEscape(os.path.basename(x)), self.getInFiles())),
			# Runtime
			'DOBREAK': self.nodeTimeout,
			'MY_RUNTIME': self.getCommand(),
			'GC_DEPFILES': str.join(' ', self.getDependencies()),
			# Seeds and substitutions
			'SEEDS': str.join(' ', map(str, self.seeds)),
			'SUBST_FILES': str.join(' ', map(os.path.basename, self.getSubstFiles())),
			# Task infos
			'TASK_ID': self.taskID,
			'GC_CONF': self.config.confName,
			'GC_VERSION': utils.getVersion(),
			'DB_EXEC': 'shellscript'
		}


	# Get job dependent environment variables
	def getJobConfig(self, jobNum):
		tmp = [('MY_JOBID', jobNum)]
		tmp += map(lambda (x, seed): ("SEED_%d" % x, seed + jobNum), enumerate(self.seeds))
		return dict(tmp)


	def getVarMapping(self):
		# Take task variables and just the variables from the first job
		envvars = self.getTaskConfig().keys() + self.getJobConfig(0).keys()

		# Map vars: Eg. __MY_JOB__ will access $MY_JOBID
		mapping = [('DATE', 'MYDATE'), ('TIMESTAMP', 'MYTIMESTAMP'),
			('MY_JOB', 'MY_JOBID'), ('CONF', 'GC_CONF')]
		mapping += zip(envvars, envvars)
		return dict(mapping)


	# Get job requirements
	def getRequirements(self, jobNum):
		return [
			(WMS.WALLTIME, self.wallTime),
			(WMS.CPUTIME, self.cpuTime),
			(WMS.MEMORY, self.memory)
		]


	# Get files for input sandbox
	def getInFiles(self):
		def fileMap(file):
			if not os.path.isabs(file):
				path = os.path.join(self.config.baseDir, file)
			else:
				path = file
			return path
		return map(fileMap, self.sbInputFiles[:])


	# Get files for output sandbox
	def getOutFiles(self):
		return self.sbOutputFiles[:]


	# Get files whose content will be subject to variable substitution
	def getSubstFiles(self):
		return self.substFiles[:]


	def getCommand(self):
		raise AbstractError


	def getJobArguments(self, jobNum):
		return ''


	def getMaxJobs(self):
		return None


	def getDependencies(self):
		return self.dependencies[:]


	def report(self, jobNum):
		return {" ": "All jobs"}


	# Called on job submission
	def getSubmitInfo(self, jobNum):
		return {}
