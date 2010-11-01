import sys, os, re, fnmatch, random, math, time
from grid_control import ConfigError, UserError, RuntimeError, Job, Report, utils
from python_compat import *

class JobDB:
	def __init__(self, config, module, monitor):
		(self.module, self.monitor) = (module, monitor)
		self.errorDict = module.errorDict
		self._dbPath = os.path.join(config.workDir, 'jobs')
		self.disableLog = os.path.join(config.workDir, 'disabled')
		try:
			if not os.path.exists(self._dbPath):
				if config.opts.init:
					os.mkdir(self._dbPath)
				else:
					raise ConfigError("Not a properly initialized work directory '%s'." % config.workDir)
		except IOError, e:
			raise ConfigError("Problem creating work directory '%s': %s" % (self._dbPath, e))

		self._jobs = {}
		self.jobLimit = config.getInt('jobs', 'jobs', -1, volatile=True)
		self.nJobs = self.getMaxJobs(self.module)
		(self.ready, self.running, self.queued, self.done, self.ok, self.disabled) = ([], [], [], [], [], [])

		# Read job infos from files
		(log, maxJobs) = (None, len(fnmatch.filter(os.listdir(self._dbPath), 'job_*.txt')))
		for idx, (jobNum, jobFile) in enumerate(Job.readJobs(self._dbPath)):
			if idx % 100 == 0:
				del log
				log = utils.ActivityLog('Reading job infos ... %d [%d%%]' % (idx, (100.0 * idx) / maxJobs))
			if len(self._jobs) >= self.nJobs:
				print 'Stopped reading job infos! The number of job infos in the work directory',
				print 'is larger than the maximum number of jobs (%d)' % self.nJobs
				break
			jobObj = Job.load(jobFile)
			self._jobs[jobNum] = jobObj
			self._findQueue(jobObj).append(jobNum)

		if len(self._jobs) < self.nJobs:
			self.ready.extend(filter(lambda x: x not in self._jobs, range(self.nJobs)))

		for jobList in (self.ready, self.queued, self.running, self.done, self.ok, self.disabled):
			jobList.sort()
		self.logDisabled()

		self.timeout = utils.parseTime(config.get('jobs', 'queue timeout', '', volatile=True))
		self.inFlight = config.getInt('jobs', 'in flight', -1, volatile=True)
		self.inQueue = config.getInt('jobs', 'in queue', -1, volatile=True)
		self.doShuffle = config.getBool('jobs', 'shuffle', False, volatile=True)
		self.maxRetry = config.getInt('jobs', 'max retry', -1, volatile=True)
		self.continuous = config.getBool('jobs', 'continuous', False, volatile=True)


	def getMaxJobs(self, module):
		nJobs = self.jobLimit
		if nJobs < 0:
			# No valid number of jobs given in config file - module has to provide number of jobs
			nJobs = module.getMaxJobs()
			if nJobs == None:
				raise ConfigError("Module doesn't provide max number of Jobs!")
		else:
			# Module doesn't have to provide number of jobs
			try:
				maxJobs = module.getMaxJobs()
				if maxJobs and (nJobs > maxJobs):
					print 'Maximum number of jobs given as %d was truncated to %d' % (nJobs, maxJobs)
					nJobs = maxJobs
			except:
				pass
		return nJobs


	# Return appropriate queue for given job
	def _findQueue(self, jobObj):
		if jobObj.state in (Job.SUBMITTED, Job.WAITING, Job.READY, Job.QUEUED):
			return self.queued
		elif jobObj.state == Job.RUNNING:
			return self.running
		elif jobObj.state in (Job.INIT, Job.FAILED, Job.ABORTED, Job.CANCELLED):
			return self.ready	# resubmit?
		elif jobObj.state == Job.DONE:
			return self.done
		elif jobObj.state == Job.SUCCESS:
			return self.ok
		elif jobObj.state == Job.DISABLED:
			return self.disabled
		raise Exception('Internal error: Unexpected job state %s' % Job.states[jobObj.state])


	def get(self, jobNum, create = False):
		if create:
			return self._jobs.get(jobNum, Job())
		return self._jobs[jobNum]


	def _update(self, jobObj, jobNum, state):
		if jobObj.state == state:
			return

		oldState = jobObj.state
		old = self._findQueue(jobObj)
		old.remove(jobNum)

		jobObj.update(state)
		jobObj.save(os.path.join(self._dbPath, 'job_%d.txt' % jobNum))

		new = self._findQueue(jobObj)
		new.append(jobNum)
		new.sort()

		jobNumLen = int(math.log10(max(1, self.nJobs)) + 1)
		utils.vprint('Job %s state changed from %s to %s ' % (str(jobNum).ljust(jobNumLen), Job.states[oldState], Job.states[state]), -1, True, False)
		if (state == Job.SUBMITTED) and (jobObj.attempt > 1):
			print '(retry #%s)' % (jobObj.attempt - 1)
		elif (state == Job.QUEUED) and jobObj.get('dest') != 'N/A':
			print '(%s)' % jobObj.get('dest')
		elif (state in [Job.WAITING, Job.ABORTED, Job.DISABLED]) and jobObj.get('reason'):
			print '(%s)' % jobObj.get('reason')
		elif (state == Job.SUCCESS) and jobObj.get('runtime', None) != None:
			print '(runtime %s)' % utils.strTime(jobObj.get('runtime'))
		elif (state == Job.FAILED):
			msg = []
			if jobObj.get('retcode'):
				msg.append('error code: %d' % jobObj.get('retcode'))
				try:
					if utils.verbosity() > 0:
						msg.append(self.errorDict[jobObj.get('retcode')])
				except:
					pass
			if jobObj.get('dest'):
				msg.append(jobObj.get('dest'))
			if len(msg):
				print '(%s)' % str.join(' - ', msg),
			print
		else:
			print


	def sample(self, jobList, size):
		if size >= 0:
			jobList = random.sample(jobList, min(size, len(jobList)))
		return sorted(jobList)


	def getSubmissionJobs(self, maxsample):
		# Determine number of jobs to submit
		submit = self.nJobs
		nQueued = len(self.queued)
		if self.inQueue > 0:
			submit = min(submit, self.inQueue - nQueued)
		if self.inFlight > 0:
			submit = min(submit, self.inFlight - nQueued - len(self.running))
		if self.continuous:
			submit = min(submit, maxsample)
		submit = max(submit, 0)

		# Get list of submittable jobs
		if self.maxRetry >= 0:
			jobList = filter(lambda x: self.get(x, create = True).attempt - 1 < self.maxRetry, self.ready)
		else:
			jobList = self.ready[:]
		jobList = filter(self.module.canSubmit, jobList)
		if self.doShuffle:
			return self.sample(jobList, submit)
		else:
			return sorted(jobList[:submit])


	def submit(self, wms, maxsample = 100):
		jobList = self.getSubmissionJobs(maxsample)
		if len(jobList) == 0:
			return False

		if not wms.bulkSubmissionBegin(len(jobList)):
			return False
		try:
			for jobNum, wmsId, data in wms.submitJobs(jobList):
				try:
					jobObj = self.get(jobNum)
				except:
					jobObj = Job()
					self._jobs[jobNum] = jobObj

				if wmsId == None:
					# Could not register at WMS
					self._update(jobObj, jobNum, Job.FAILED)
					continue

				jobObj.assignId(wmsId)
				for key, value in data.iteritems():
					jobObj.set(key, value)

				self._update(jobObj, jobNum, Job.SUBMITTED)
				self.monitor.onJobSubmit(wms, jobObj, jobNum)
				if utils.abort():
					return False
			return True
		finally:
			wms.bulkSubmissionEnd()


	def wmsArgs(self, jobList):
		return map(lambda jobNum: (self.get(jobNum).wmsId, jobNum), jobList)


	def check(self, wms, maxsample = 100):
		(change, timeoutList) = (False, [])
		jobList = self.sample(self.running + self.queued, (-1, maxsample)[self.continuous])

		# Update states of jobs
		for jobNum, wmsId, state, info in wms.checkJobs(self.wmsArgs(jobList)):
			jobObj = self.get(jobNum)
			if state != jobObj.state:
				change = True
				for key, value in info.items():
					jobObj.set(key, value)
				self._update(jobObj, jobNum, state)
				self.monitor.onJobUpdate(wms, jobObj, jobNum, info)
			else:
				# If a job stays too long in an inital state, cancel it
				if jobObj.state in (Job.SUBMITTED, Job.WAITING, Job.READY, Job.QUEUED):
					if self.timeout > 0 and time.time() - jobObj.submitted > self.timeout:
						timeoutList.append(jobNum)
			if utils.abort():
				return False

		# Cancel jobs who took too long
		if len(timeoutList):
			change = True
			print '\nTimeout for the following jobs:'
			self.cancel(wms, timeoutList)

		# Process module interventions
		self.processIntervention(wms, self.module.getIntervention())

		# Quit when all jobs are finished
		if len(self.ok) + len(self.disabled) == self.nJobs:
			self.logDisabled()
			if len(self.disabled) > 0:
				utils.vprint('There are %d disabled jobs in this task!' % len(self.disabled), -1, True)
				utils.vprint('Please refer to %s for a complete list.' % self.disableLog, -1, True)
			self.monitor.onTaskFinish(self.nJobs)
			if self.module.onTaskFinish():
				utils.vprint('Task successfully completed. Quitting grid-control!', -1, True)
				sys.exit(0)

		return change


	def logDisabled(self):
		try:
			open(self.disableLog, 'w').write(str.join('\n', map(str, self.disabled)))
		except:
			raise RuntimeError('Could not write disabled jobs to file %s!' % (jobNum, self.disableLog))


	def retrieve(self, wms, maxsample = 10):
		change = False
		jobList = self.sample(self.done, (-1, maxsample)[self.continuous])

		for jobNum, retCode, data in wms.retrieveJobs(self.wmsArgs(jobList)):
			try:
				jobObj = self.get(jobNum)
			except:
				continue

			if retCode == 0:
				state = Job.SUCCESS
			else:
				state = Job.FAILED

			if state != jobObj.state:
				change = True
				jobObj.set('retcode', retCode)
				jobObj.set('runtime', data.get('TIME', -1))
				self._update(jobObj, jobNum, state)
				self.monitor.onJobOutput(wms, jobObj, jobNum, retCode)

			if utils.abort():
				return False

		return change


	def cancel(self, wms, jobs, interactive = False):
		if len(jobs) == 0:
			return
		Report(jobs, self).details()
		if interactive and not utils.getUserBool('Do you really want to delete these jobs?', True):
			return

		def mark_cancelled(jobNum):
			try:
				jobObj = self.get(jobNum)
			except:
				return
			self._update(jobObj, jobNum, Job.CANCELLED)

		for (wmsId, jobNum) in wms.cancelJobs(self.wmsArgs(jobs)):
			# Remove deleted job from todo list and mark as cancelled
			jobs.remove(jobNum)
			mark_cancelled(jobNum)

		if len(jobs) > 0:
			print '\nThere was a problem with deleting the following jobs:'
			Report(jobs, self._jobs).details()
			if interactive and utils.getUserBool('Do you want to mark them as deleted?', True):
				map(mark_cancelled, jobs)


	def getCancelJobs(self, jobs):
		deleteable = [ Job.SUBMITTED, Job.WAITING, Job.READY, Job.QUEUED, Job.RUNNING ]
		return filter(lambda x: self.get(x).state in deleteable, jobs)


	def getJobs(self, selector):
		predefined = { 'TODO': 'SUBMITTED,WAITING,READY,QUEUED', 'ALL': str.join(',', Job.states)}
		jobFilter = predefined.get(selector.upper(), selector.upper())

		if len(jobFilter) and jobFilter[0].isdigit():
			try:
				jobs = map(int, jobFilter.split(','))
			except:
				raise UserError('Job identifiers must be integers.')
		else:
			def stateFilter(jobObj):
				for state in jobFilter.split(','):
					regex = re.compile('^%s.*' % state)
					for key in filter(regex.match, Job.states):
						if key == Job.states[jobObj.state]:
							return True
				return False
			def siteFilter(jobObj):
				dest = jobObj.get('dest')
				if not dest:
					return False
				dest = str.join('/', map(lambda x: x.split(':')[0], dest.upper().split('/')))
				for site in jobFilter.split(','):
					if re.compile(site).search(dest):
						return True
				return False
			# First try matching states, then try to match destinations
			jobs = filter(lambda x: stateFilter(self.get(x)), self._jobs.keys())
			if jobs == []:
				jobs = filter(lambda x: siteFilter(self.get(x)), self._jobs.keys())
		return jobs


	def delete(self, wms, selector):
		jobs = self.getCancelJobs(self.getJobs(selector))
		if jobs:
			print '\nDeleting the following jobs:'
			self.cancel(wms, jobs, True)


	# Process changes of job states requested by job module
	def processIntervention(self, wms, jobChanges):
		def resetState(jobs, newState):
			jobSet = utils.set(jobs)
			for jobNum in jobs:
				jobObj = self.get(jobNum)
				if jobObj.state in [ Job.INIT, Job.DISABLED, Job.ABORTED, Job.CANCELLED, Job.DONE, Job.FAILED, Job.SUCCESS ]:
					self._update(jobObj, jobNum, newState)
					self.monitor.onJobUpdate(wms, jobObj, jobNum, {})
					jobSet.remove(jobNum)
					jobObj.attempt = 0
			if len(jobSet) > 0:
				output = (Job.states[newState], str.join(', ', map(str, jobSet)))
				raise RuntimeError('For the following jobs it was not possible to reset the state to %s:\n%s' % output)

		if jobChanges:
			(redo, disable) = jobChanges
			newMaxJobs = self.getMaxJobs(self.module)
			if (redo == []) and (disable == []) and (self.nJobs == newMaxJobs):
				return
			utils.vprint('The job module has requested changes to the job database', -1, True)
			if self.nJobs != newMaxJobs:
				utils.vprint('Number of jobs changed from %d to %d' % (self.nJobs, newMaxJobs), -1, True)
				self.nJobs = newMaxJobs
				if len(self._jobs) < self.nJobs:
					self.ready.extend(filter(lambda x: x not in self._jobs, range(self.nJobs)))
			self.cancel(wms, self.getCancelJobs(disable))
			self.cancel(wms, self.getCancelJobs(redo))
			resetState(disable, Job.DISABLED)
			resetState(redo, Job.INIT)
			utils.vprint('All requested changes are applied', -1, True)
			self.logDisabled()
