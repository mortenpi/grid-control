#!/usr/bin/env python
import gcSupport, sys, os, optparse, popen2, time, random, threading
from python_compat import *
from grid_control import *
from grid_control import job_db, storage
from grid_control.proxy import Proxy

def md5sum(filename):
	m = md5()
	# use 4M blocksize:
	blocksize = 4096 * 1024
	f = open(filename, 'r')
	while True:
		s = f.read(blocksize)
		m.update(s)
		if len(s) != blocksize:
			break
	return m.hexdigest()


def main(args):
	help = \
"""
DEFAULT: The default is to download the SE file and check them with MD5 hashes.
 * In case all files are transferred sucessfully, the job is marked
   as already downloaded, so that the files are not copied again.
 * Failed transfer attempts will mark the job as failed, so that it
   can be resubmitted."""
	parser = optparse.OptionParser(usage = "%prog [options] <config file>\n" + help)

	def addBoolOpt(optList, optPostfix, dest, default, help, optShort=("", ""), optPrefix=("no", ""), helpPrefix=("do not ", "")):
		def buildLongOpt(prefix, postfix):
			if prefix and postfix:
				return "--%s-%s" % (prefix, postfix)
			elif prefix and not postfix:
				return "--" + prefix
			else:
				return "--" + postfix
		optList.add_option(optShort[True], buildLongOpt(optPrefix[True], optPostfix), dest=dest,
			default=default, action="store_true", help=helpPrefix[True] + help + ("", " [Default]")[default])
		optList.add_option(optShort[False], buildLongOpt(optPrefix[False], optPostfix), dest=dest,
			default=default, action="store_false", help=helpPrefix[False] + help + (" [Default]", "")[default])

	addBoolOpt(parser, "verify-md5", dest="verify",       default=True,  optShort=("", "-v"),
		help="MD5 verification of SE files", helpPrefix=("disable ", "enable "))
	addBoolOpt(parser, "loop",       dest="loop",         default=False, optShort=("", "-l"),
		help="loop over jobs until all files are successfully processed")
	addBoolOpt(parser, "infinite",   dest="infinite",     default=False, optShort=("", "-L"),
		help="process jobs in an infinite loop")
	addBoolOpt(parser, "shuffle",    dest="shuffle",      default=False,
		help="shuffle download order")
	addBoolOpt(parser, "",           dest="skipExisting", default=False, optPrefix=("overwrite", "skip-existing"),
		help="files which are already on local disk", helpPrefix=("overwrite ", "skip "))

	ogFlags = optparse.OptionGroup(parser, "Job state / flag handling", "")
	addBoolOpt(ogFlags, "mark-dl",   dest="markDL",       default=True,
		help="mark sucessfully downloaded jobs as such")
	addBoolOpt(ogFlags, "mark-dl",   dest="markIgnoreDL", default=False, optPrefix=("use", "ignore"),
		help="mark about sucessfully downloaded jobs", helpPrefix=("use ", "ignore "))
	addBoolOpt(ogFlags, "mark-fail", dest="markFailed",   default=True,
		help="mark jobs failing verification as such")
	addBoolOpt(ogFlags, "mark-empty-fail", dest="markEmptyFailed", default=False,
		help="mark jobs without any files as failed")
	parser.add_option_group(ogFlags)

	ogFiles = optparse.OptionGroup(parser, "Local / SE file handling", "")
	for (optPostfix, dest, help, default) in [
			('local-ok',   'rmLocalOK',   'files of successful jobs in local directory', False),
			('local-fail', 'rmLocalFail', 'files of failed jobs in local directory', False),
			('se-ok',      'rmSEOK',      'files of successful jobs on SE', False),
			('se-fail',    'rmSEFail',    'files of failed jobs on the SE', False),
		]:
		addBoolOpt(ogFiles, optPostfix, dest=dest, default=default, optPrefix=("keep", "rm"),
			help=help, helpPrefix=("keep ", "remove "))
	parser.add_option_group(ogFiles)

	parser.add_option("-o", "--output", dest="output", default=None,
		help="specify the local output directory")
	parser.add_option("-P", "--proxy",  dest="proxy",  default="VomsProxy",
		help="specify the proxy type used to determine ability to download - VomsProxy or TrivialProxy")
	parser.add_option("-S", "--selectSE", dest="selectSE",  default=None, action="append",
		help="specify the SE paths to process")
	parser.add_option("-r", "--retry",  dest="retry",  default=0,
		help="how often should a transfer be attempted [Default: 0]")

	# Shortcut options
	def withoutDefaults(opts):
		def isDefault(opt):
			return (parser.get_option(opt).default and parser.get_option(opt).action == "store_true") or \
				(not parser.get_option(opt).default and parser.get_option(opt).action == "store_false")
		return str.join(" ", filter(lambda x: not isDefault(x), opts.split()))

	ogShort = optparse.OptionGroup(parser, "Shortcuts", "")
	optMove = "--verify-md5 --overwrite --mark-dl --use-mark-dl --mark-fail --rm-se-fail --rm-local-fail --rm-se-ok --keep-local-ok"
	ogShort.add_option("-m", "--move", dest="shMove", default=None, action="store_const", const=optMove,
		help = "Move files from SE - shorthand for:".ljust(100) + withoutDefaults(optMove))

	optCopy = "--verify-md5 --overwrite --mark-dl --use-mark-dl --mark-fail --rm-se-fail --rm-local-fail --keep-se-ok --keep-local-ok"
	ogShort.add_option("-c", "--copy", dest="shCopy", default=None, action="store_const", const=optCopy,
		help = "Copy files from SE - shorthand for:".ljust(100) + withoutDefaults(optCopy))

	optJCopy = "--verify-md5 --skip-existing --no-mark-dl --ignore-mark-dl --no-mark-fail --keep-se-fail --keep-local-fail --keep-se-ok --keep-local-ok"
	ogShort.add_option("-j", "--just-copy", dest="shJCopy", default=None, action="store_const", const=optJCopy,
		help = "Just copy files from SE - shorthand for:".ljust(100) + withoutDefaults(optJCopy))

	optSCopy = "--verify-md5 --mark-dl --mark-fail --rm-se-fail --rm-local-fail --keep-se-ok --keep-local-ok"
	ogShort.add_option("-s", "--smart-copy", dest="shSCopy", default=None, action="store_const", const=optSCopy,
		help = "Copy correct files from SE, but remember already downloaded files and delete corrupt files - shorthand for: ".ljust(100) + withoutDefaults(optSCopy))

	optJVerify = "--verify-md5 --no-mark-dl --keep-se-fail --rm-local-fail --keep-se-ok --rm-local-ok"
	ogShort.add_option("-V", "--just-verify", dest="shJVerify", default=None, action="store_const", const=optJVerify,
		help = "Just verify files on SE - shorthand for:".ljust(100) + withoutDefaults(optJVerify))

	optJDelete = "--skip-existing --rm-se-fail --rm-se-ok --rm-local-fail --keep-local-ok"
	ogShort.add_option("-D", "--just-delete", dest="shJDelete", default=None, action="store_const", const=optJDelete,
		help = "Just delete all finished files on SE - shorthand for:".ljust(100) + withoutDefaults(optJDelete))
	parser.add_option_group(ogShort)

	(opts, args) = parser.parse_args()
	def processShorthand(optSet):
		if optSet:
			parser.parse_args(args = optSet.split() + sys.argv[1:], values = opts)
	processShorthand(opts.shMove)
	processShorthand(opts.shCopy)
	processShorthand(opts.shJCopy)
	processShorthand(opts.shSCopy)
	processShorthand(opts.shJVerify)
	processShorthand(opts.shJDelete)

	# Disable loop mode if it is pointless
	if (opts.loop and not opts.skipExisting) and (opts.markIgnoreDL or not opts.markDL):
		sys.stderr.write("Loop mode was disabled to avoid continuously downloading the same files\n")
		(opts.loop, opts.infinite) = (False, False)

	# we need exactly one positional argument (config file)
	if len(args) != 1:
		sys.stderr.write("usage: %s [options] <config file>\n\n" % os.path.basename(sys.argv[0]))
		sys.stderr.write("Config file not specified!\n")
		sys.stderr.write("Use --help to get a list of options!\n")
		sys.exit(0)

	while True:
		try:
			if (realmain(opts, args) or not opts.loop) and not opts.infinite:
				break
			time.sleep(60)
		except KeyboardInterrupt:
			print "\n\nDownload aborted!\n"
			sys.exit(1)


def dlfs_rm(path, msg):
	procRM = storage.se_rm(path)
	if procRM.wait() != 0:
		print "\t\tUnable to remove %s!" % msg
		utils.eprint("%s\n\n" % procRM.getMessage())


def realmain(opts, args):
	try:
		proxy = Proxy.open(opts.proxy, Config(configDict={"proxy": {"ignore warnings": True}}))
	except GCError:
		sys.stderr.write(GCError.message)
		sys.exit(1)

	(workDir, nJobs, jobList) = gcSupport.getWorkJobs(args, job_db.ClassSelector(job_db.JobClass.SUCCESS))

	# Create SE output dir
	if not opts.output:
		opts.output = os.path.join(workDir, 'se_output')
	if "://" not in opts.output:
		opts.output = "file:///%s" % os.path.abspath(opts.output)

	infos = {}
	def incInfo(x):
		infos[x] = infos.get(x, 0) + 1

	def processSingleJob(jobNum):
		print "Job %d:" % jobNum,

		# Only run over finished and not yet downloaded jobs
		try:
			jobFile = os.path.join(workDir, 'jobs', 'job_%d.txt' % jobNum)
			job = Job.load(jobFile)
		except KeyboardInterrupt:
			raise
		except:
			print "Could not load job status file %s!" % jobFile
			return
		if job.state != Job.SUCCESS:
			print "Job has not yet finished successfully!"
			return incInfo("Processing")
		if job.get('download') == 'True' and not opts.markIgnoreDL:
			print "All files already downloaded!"
			return incInfo("Downloaded")
		retry = int(job.get('download attempt', 0))

		failJob = False

		if not proxy.canSubmit(20*60, True):
			print "Please renew grid proxy!"
			sys.exit(1)

		# Read the file hash entries from job info file
		files = gcSupport.getFileInfo(workDir, jobNum, lambda retCode: retCode == 0)
		if not files:
			if opts.markEmptyFailed:
				failJob = True
			else:
				return incInfo("No files")
		print "The job wrote %d file%s to the SE" % (len(files), ('s', '')[len(files) == 1])

		for (hash, name_local, name_dest, pathSE) in files:
			print "\t", name_dest,
			sys.stdout.flush()

			# Copy files to local folder
			outFilePath = os.path.join(opts.output, name_dest)
			if opts.selectSE:
				if not (True in map(lambda s: s in pathSE, opts.selectSE)):
					print "skip file because it is not located on selected SE!"
					return
			if opts.skipExisting and (storage.se_exists(outFilePath) == 0):
				print "skip file as it already exists!"
				return
			if storage.se_exists(os.path.dirname(outFilePath)).wait() != 0:
				storage.se_mkdir(os.path.dirname(outFilePath)).wait()

			checkPath = 'file:///tmp/dlfs.%s' % name_dest
			if 'file://' in outFilePath:
				checkPath = outFilePath

			myGetSize = lambda x: "(%7s)" % gcSupport.prettySize(os.path.getsize(x.replace('file://', '')))
			def monitorFile(path, lock):
				while not lock.acquire(False):
					try:
						print "\r\t", name_dest, myGetSize(path),
						sys.stdout.flush()
					except:
						pass
					time.sleep(1)
				lock.release()
			monitorLock = threading.Lock()
			monitorLock.acquire()
			monitor = threading.Thread(target = monitorFile, args = (checkPath, monitorLock))
			monitor.start()
			try:
				procCP = storage.se_copy(os.path.join(pathSE, name_dest), outFilePath, tmp = checkPath)
				result = procCP.wait()
			finally:
				monitorLock.release()
				monitor.join()
			if result != 0:
				print "\n\t\tUnable to copy file from SE!"
				print procCP.getMessage()
				failJob = True
				break

			# Verify => compute md5hash
			if opts.verify:
				try:
					hashLocal = md5sum(checkPath.replace('file://', ''))
					if not ('file://' in outFilePath):
						dlfs_rm('file://%s' % checkPath, 'SE file')
				except KeyboardInterrupt:
					raise
				except:
					hashLocal = None
					print ""
				print "=>", ('\33[0;91mFAIL\33[0m', '\33[0;92mMATCH\33[0m')[hash == hashLocal]
				print "\t\tRemote site:", hash
				print "\t\t Local site:", hashLocal
				if hash != hashLocal:
					failJob = True
			else:
				print
				print "\t\tRemote site:", hash

		# Ignore the first opts.retry number of failed jobs
		if failJob and opts.retry and (retry < opts.retry):
			print "\t\tDownload attempt #%d failed!" % (retry + 1)
			job.set('download attempt', str(retry + 1))
			incInfo("Download attempts")
			job.save(jobFile)
			return

		for (hash, name_local, name_dest, pathSE) in files:
			# Remove downloaded files in case of failure
			if (failJob and opts.rmLocalFail) or (not failJob and opts.rmLocalOK):
				sys.stdout.write("\tDeleting file %s from local...\r" % name_dest)
				outFilePath = os.path.join(opts.output, name_dest)
				if storage.se_exists(outFilePath).wait() == 0:
					dlfs_rm(outFilePath, 'local file')
			# Remove SE files in case of failure
			if (failJob and opts.rmSEFail)    or (not failJob and opts.rmSEOK):
				sys.stdout.write("\tDeleting file %s...\r" % name_dest)
				dlfs_rm(os.path.join(pathSE, name_dest), 'SE file')
			print "%s\r" % (' ' * len("\tDeleting file %s from SE...\r" % name_dest))

		if failJob:
			incInfo("Failed downloads")
			if opts.markFailed:
				# Mark job as failed to trigger resubmission
				job.state = Job.FAILED
		else:
			incInfo("Successful download")
			if opts.markDL:
				# Mark as downloaded
				job.set('download', 'True')

		# Save new job status infos
		job.save(jobFile)
		print

	if opts.shuffle:
		random.shuffle(jobList)
	else:
		jobList.sort()
	for jobNum in jobList:
		processSingleJob(jobNum) # could be done in parallel

	# Print overview
	if infos:
		print "\nStatus overview:"
		for (state, num) in infos.items():
			if num > 0:
				print "%20s: [%d/%d]" % (state, num, len(jobList))
		print

	if ("Downloaded" in infos) and (infos["Downloaded"] == nJobs):
		return True
	return False

if __name__ == '__main__':
	sys.exit(main(sys.argv[1:]))
