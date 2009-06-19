#!/usr/bin/env python
import sys, os, signal, optparse

# add python subdirectory from where go.py was started to search path
_root = os.path.dirname(os.path.abspath(os.path.normpath(sys.argv[0])))
sys.path.insert(0, os.path.join(_root, 'python'))

# and include grid_control python module
from grid_control import *
import time

def print_help(*args):
	sys.stderr.write("Syntax: %s [OPTIONS] <config file>\n\n" % sys.argv[0])
	sys.stderr.write(open(utils.atRoot('share', 'help.txt'), 'r').read())
	sys.exit(0)

_verbosity = 0

def main(args):
	global opts, log

	# display the 'grid-control' logo and version
	print open(utils.atRoot('share', 'logo.txt'), 'r').read()
	try:
		ver = popen2.popen3('svnversion %s' % _root)[0].read().strip()
		if ver != '':
			print 'Revision: %s' % ver
	except:
		pass
	pyver = reduce(lambda x,y: x+y/10., sys.version_info[:2])
	if pyver < 2.3:
		utils.deprecated("This python version (%.1f) is not supported anymore!" % pyver)

	parser = optparse.OptionParser(add_help_option=False)
	parser.add_option("-h", "--help",          action="callback", callback=print_help),
	parser.add_option("-s", "--no-submission", dest="submission", default=True,  action="store_false")
	parser.add_option("-q", "--requery",       dest="resync",     default=False, action="store_true")
	parser.add_option("-i", "--init",          dest="init",       default=False, action="store_true")
	parser.add_option("-c", "--continuous",    dest="continuous", default=False, action="store_true")
	parser.add_option("-r", '--report',        dest="report",     default=False, action="store_true")
	parser.add_option("-v", "--verbose",       dest="verbosity",  default=0,     action="count")
	parser.add_option("-R", '--site-report',   dest="reportSite", default=0,     action="count")
	parser.add_option("-T", '--time-report',   dest="reportTime", default=0,     action="count")
	parser.add_option("-m", '--max-retry',     dest="maxRetry",   default=None,  type="int")
	parser.add_option("-d", '--delete',        dest="delete",     default=None)
	parser.add_option("-S", '--seed',          dest="seed",       default=None)
	(opts, args) = parser.parse_args()
	sys.modules['__main__']._verbosity = opts.verbosity

	# we need exactly one positional argument (config file)
	if len(args) != 1:
		print_help()

	# set up signal handler for interrupts
	def interrupt(sig, frame):
		global opts, log
		opts.continuous = False
		log = utils.ActivityLog('Quitting grid-control! (This can take a few seconds...)')
	signal.signal(signal.SIGINT, interrupt)

	# big try... except block to catch exceptions and print error message
	try:
		# try to open config file
		try:
			config = Config(args[0])
		except IOError, e:
			raise ConfigError("Error while reading configuration file '%s'!" % args[0])

		# Check work dir validity (default work directory is the config file name)
		workDir = config.getPath('global', 'workdir', os.path.basename(args[0]).replace(".conf",""))
		if not os.path.exists(workDir):
			if utils.boolUserInput("Do you want to create the working directory %s?" % workDir, True):
				os.mkdir(workDir)
		try:
			os.chdir(workDir)
		except:
			raise UserError("Could not access specified working directory '%s'!" % workDir)

		# Initialise application module
		module = config.get('global', 'module')
		module = Module.open(module, workDir, config, opts)
		if opts.seed:
			module.setSeed(opts.seed.lstrip('S'))

		# Initialise workload management interface
		backend = config.get('global', 'backend', 'grid')
		if backend == 'grid':
			wms = WMS.open(config.get(backend, 'wms', 'GliteWMS'), workDir, config, opts, module)
		elif backend == 'local':
			wms = WMS.open('LocalWMS', workDir, config, opts, module)
		else:
			raise UserError("Invalid backend specified!" % workDir)

		# Initialise proxy
		proxy = wms.getProxy()
		module.username = proxy.getUsername()

		# Test grid proxy lifetime
		wallTime = utils.parseTime(config.get('jobs', 'wall time'))
		if proxy.critical():
			raise UserError('Your proxy only has %d seconds left!' % proxy.timeleft())
		if not proxy.check(wallTime):
			proxy.warn(wallTime)
			opts.submission = False

		# Initialise job database
		queueTimeout = utils.parseTime(config.get('jobs', 'queue timeout', ''))
		jobs = JobDB(workDir, config.getInt('jobs', 'jobs', -1), queueTimeout, module, opts.init)

		# If invoked in report mode, just show report and exit
		if Report(opts, jobs, jobs).show():
			return 0

		# Check if jobs have to be deleted and exit
		if opts.delete != None:
			jobs.delete(wms, opts)
			return 0

		# Check if running in continuous mode
		if opts.continuous:
			print "Running in continuous mode. Press ^C to exit."

		# Job submission loop
		timeout = 0
		while True:
			for x in xrange(0, timeout, 5):
				# avoid timeout if not continuous
				if not opts.continuous:
					break
				log = utils.ActivityLog('next check in %d seconds' % (timeout - x))
				time.sleep(5)
				del log
			if not opts.continuous:
				break

			# idle timeout is one minute
			timeout = 60

			# Check free disk space
			if int(os.popen("df -P -m %s" % workDir).readlines()[-1].split()[3]) < 10:
				raise RuntimeError("Not enough space left in working directory")

			# try submission
			if opts.submission:
				inFlight = config.getInt('jobs', 'in flight')
				doShuffle = config.getBool('jobs', 'shuffle', False)
				jobList = jobs.getSubmissionJobs(inFlight, opts.maxRetry, doShuffle)
				if len(jobList):
					jobs.submit(wms, jobList)
					timeout = 10
					continue
				del jobList

			# retrieve finished jobs
			if jobs.retrieve(wms):
				timeout = 10
				continue

			# check for jobs
			if jobs.check(wms):
				timeout = 10
				continue

			# Check proxy lifetime
			if opts.submission and not proxy.check(wallTime):
				proxy.warn(wallTime)
				opts.submission = False

	except GridError, e:
		e.showMessage()
		return 1

	return 0

# if go.py is executed from the command line, call main() with the arguments
if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
