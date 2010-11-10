from python_compat import *
import sys, os, StringIO, tarfile, time, fnmatch, re, popen2, threading, operator
from exceptions import *

# "question mark" function
def QM(cond, a, b):
	if cond:
		return a
	return b

################################################################
# Path helper functions

def pathGC(*args):
	# Convention: sys.path[1] == python dir of gc
	return os.path.normpath(os.path.join(sys.path[1], '..', *args))


def resolvePath(path, userpath = [], check = True, ErrorClass = RuntimeError):
	searchpaths = [ os.getcwd(), pathGC() ] + userpath
	cleanPath = lambda x: os.path.normpath(os.path.expanduser(x.strip()))
	path = cleanPath(path)
	if not os.path.isabs(path):
		for spath in searchpaths:
			if os.path.exists(os.path.join(spath, path)):
				return cleanPath(os.path.join(spath, path))
		if check:
			raise ErrorClass('Could not find file %s in \n\t%s' % (path, str.join('\n\t', searchpaths)))
	return path


def resolveInstallPath(path):
	return resolvePath(path, os.environ['PATH'].split(':'), True, InstallationError)

################################################################
# Process management functions

def gcStartThread(fun, *args, **kargs):
	thread = threading.Thread(target = fun, args = args, kwargs = kargs)
	thread.setDaemon(True)
	thread.start()
	return thread


class LoggedProcess(object):
	def __init__(self, cmd, args = ''):
		self.cmd = (cmd, args) # used in backend error messages
		vprint('External programm called: %s %s' % self.cmd, level=3)
		self.proc = popen2.Popen3('%s %s' % (cmd, args), True)
		(self.stdout, self.stderr) = ([], [])

	def getOutput(self, wait = False):
		if wait:
			self.wait()
		self.stdout.extend(self.proc.fromchild.readlines())
		return str.join('', self.stdout)

	def getError(self):
		self.stderr.extend(self.proc.childerr.readlines())
		return str.join('', self.stderr)

	def getMessage(self):
		return self.getOutput() + '\n' + self.getError()

	def iter(self):
		while True:
			try:
				line = self.proc.fromchild.readline()
			except:
				abort(True)
				break
			if not line:
				break
			self.stdout.append(line)
			yield line

	def wait(self):
		return self.proc.wait()

	def getAll(self):
		self.stdout.extend(self.proc.fromchild.readlines())
		self.stderr.extend(self.proc.childerr.readlines())
		return (self.wait(), self.stdout, self.stderr)

################################################################
# Path helper functions

def globalSetupProxy(fun, default, new = None):
	if new != None:
		fun.setting = new
	try:
		return fun.setting
	except:
		return default


def verbosity(new = None):
	return globalSetupProxy(verbosity, 0, new)


def abort(new = None):
	return globalSetupProxy(abort, False, new)

################################################################

def checkVar(value, message, check = True):
	if check and ((str(value).count('@') >= 2) or (str(value).count('__') >= 2)):
		raise ConfigError(message)
	return value


def mergeDicts(dicts):
	tmp = dict()
	for x in dicts:
		tmp.update(x)
	return tmp


def filterDict(dictType, kF = lambda k: True, vF = lambda v: True):
	return dict(filter(lambda (k, v): kF(k) and vF(v), dictType.iteritems()))


def accumulate(iterable, doEmit = lambda x, buf: x == '\n', start = '', opAdd = operator.add, addCause = True):
	buffer = start
	for item in iterable:
		if doEmit(item, buffer):
			if addCause:
				buffer = opAdd(buffer, item)
			yield buffer
			buffer = start
			if addCause:
				continue
		buffer = opAdd(buffer, item)
	yield buffer


def wrapList(value, length, delimLines = ',\n', delimEntries = ', '):
	counter = lambda item, buffer: len(item) + sum(map(len, buffer)) >= length
	wrapped = accumulate(value, counter, [], lambda x, y: x + [y], False)
	return str.join(delimLines, map(lambda x: str.join(delimEntries, x), wrapped))


def optSplit(opt, delim):
	""" Split option strings into fixed tuples
	>>> optSplit('abc:ghi#def', ['#', ':'])
	('abc', 'def', 'ghi')
	>>> optSplit('abcghi#def', ['#', ':'])
	('abcghi', 'def', '')
	"""
	rmPrefix = lambda opt: reduce(lambda x, y: x.split(y)[0], delim, opt)
	def afterPrefix(prefix):
		try:
			return opt.split(prefix, 1)[1]
		except:
			return ''
	tmp = map(lambda p: rmPrefix(afterPrefix(p)), delim)
	return tuple(map(str.strip, [rmPrefix(opt)] + tmp))


def flatten(lists):
	result = []
	for x in lists:
		try:
			if isinstance(x, str):
				raise
			result.extend(x)
		except:
			result.append(x)
	return result


def safeWrite(fp, content):
	fp.writelines(content)
	fp.truncate()
	fp.close()


def DiffLists(oldList, newList, cmpFkt, changedFkt):
	(listAdded, listMissing, listChanged) = ([], [], [])
	(newIter, oldIter) = (iter(sorted(newList, cmpFkt)), iter(sorted(oldList, cmpFkt)))
	(new, old) = (next(newIter, None), next(oldIter, None))
	while True:
		if (new == None) or (old == None):
			break
		result = cmpFkt(new, old)
		if result < 0: # new[npos] < old[opos]
			listAdded.append(new)
			new = next(newIter, None)
		elif result > 0: # new[npos] > old[opos]
			listMissing.append(old)
			old = next(oldIter, None)
		else: # new[npos] == old[opos] according to *active* comparison
			changedFkt(listAdded, listMissing, listChanged, old, new)
			(new, old) = (next(newIter, None), next(oldIter, None))
	while new != None:
		listAdded.append(new)
		new = next(newIter, None)
	while old != None:
		listMissing.append(old)
		old = next(oldIter, None)
	return (listAdded, listMissing, listChanged)


class PersistentDict(dict):
	def __init__(self, filename, delimeter = '=', lowerCaseKey = True):
		dict.__init__(self)
		(self.format, self.filename) = (delimeter, filename)
		try:
			dictObj = DictFormat(self.format)
			self.update(dictObj.parse(open(filename), lowerCaseKey = lowerCaseKey))
		except:
			pass
		self.olddict = self.items()

	def write(self, newdict = {}, update = True):
		if not update:
			self.clear()
		self.update(newdict)
		if self.olddict == self.items():
			return
		try:
			safeWrite(open(self.filename, 'w'), DictFormat(self.format).format(self))
		except:
			raise RuntimeError('Could not write to file %s' % self.filename)
		self.olddict = self.items()


class VirtualFile(StringIO.StringIO):
	def __init__(self, name, lines):
		StringIO.StringIO.__init__(self, str.join('', lines))
		self.name = name
		self.size = len(self.getvalue())


	def getTarInfo(self):
		info = tarfile.TarInfo(self.name)
		info.size = self.size
		return (info, self)


def doBlackWhiteList(value, bwfilter):
	""" Apply black-whitelisting to input list
	>>> doBlackWhiteList(['T2_US_MIT', 'T1_DE_KIT_MSS', 'T1_US_FNAL'], ['T1', '-T1_DE_KIT'])
	['T1_US_FNAL']
	"""
	blacklist = map(lambda x: x[1:], filter(lambda x: x.startswith('-'), bwfilter))
	checkMatch = lambda item, matchList: True in map(lambda x: item.startswith(x), matchList)
	value = filter(lambda x: not checkMatch(x, blacklist), value)
	whitelist = filter(lambda x: not x.startswith('-'), bwfilter)
	if len(whitelist):
		return filter(lambda x: checkMatch(x, whitelist), value)
	return value


def parseType(value):
	try:
		if '.' in value:
			return float(value)
		return int(value)
	except ValueError:
		return value


def parseBool(x):
	if x.lower() in ('yes', 'y', 'true', 't', 'ok', '1', 'on'):
		return True
	if x.lower() in ('no', 'n', 'false', 'f', 'fail', '0', 'off'):
		return False


def parseList(value, delimeter = ',', doFilter = lambda x: x != '', onEmpty = []):
	if value:
		return filter(doFilter, map(str.strip, value.split(delimeter)))
	return onEmpty


def parseTuples(value):
	"""Parse a string for keywords and tuples of keywords.
	>>> parseTuples('(4, 8:00), keyword, ()')
	[('4', '8:00'), 'keyword', ()]
	>>> parseTuples('(4, 8:00), keyword, ()')
	[('4', '8:00'), 'keyword', ()]
	"""
	def to_tuple_or_str((t, s)):
		if len(s) > 0:
			return s
		elif len(t.strip()) == 0:
			return tuple()
		return tuple(parseList(t))
	return map(to_tuple_or_str, re.findall('\(([^\)]*)\)|([a-zA-Z0-9_\.]+)', value))


def parseTime(usertime):
	if usertime == None or usertime == '':
		return -1
	tmp = map(int, usertime.split(':'))
	while len(tmp) < 3:
		tmp.append(0)
	if tmp[2] > 59 or tmp[1] > 59 or len(tmp) > 3:
		raise ConfigError('Invalid time format: %s' % usertime)
	return reduce(lambda x, y: x * 60 + y, tmp)


def strTime(secs, fmt = '%dh %0.2dmin %0.2dsec'):
	return QM(secs >= 0, fmt % (secs / 60 / 60, (secs / 60) % 60, secs % 60), '')


class DictFormat(object):
	# escapeString = escape '"', '$'
	# types = preserve type information
	def __init__(self, delimeter = '=', escapeString = False, types = True):
		self.delimeter = delimeter
		self.types = types
		self.escapeString = escapeString

	# Parse dictionary lists
	def parse(self, lines, lowerCaseKey = True, keyRemap = {}, valueParser = {}):
		data = {}
		currentline = ''
		doAdd = False
		try:
			lines = lines.splitlines()
		except:
			pass
		for line in lines:
			if self.escapeString:
				# Accumulate lines until closing " found
				if (line.count('"') - line.count('\\"')) % 2:
					doAdd = not doAdd
				currentline += line
				if doAdd:
					continue
			else:
				currentline = line
			try:
				# split at first occurence of delimeter and strip spaces around
				key, value = map(str.strip, currentline.split(self.delimeter, 1))
				if self.escapeString:
					value = value.strip('"').replace('\\"', '"').replace('\\$', '$')
				if lowerCaseKey:
					key = key.lower()
				if self.types:
					value = parseType(value)
					key = parseType(key)
				# do .encode('utf-8') ?
				data[keyRemap.get(key, key)] = valueParser.get(key, lambda x: x)(value)
			except:
				# in case no delimeter was found
				pass
			currentline = ''
		if doAdd:
			raise ConfigError('Invalid dict format in %s' % fp.name)
		return data

	# Format dictionary list
	def format(self, dict, printNone = False, fkt = lambda (x, y, z): (x, y, z), format = '%s%s%s\n'):
		result = []
		for key in dict.keys():
			value = dict[key]
			if value == None and not printNone:
				continue
			if self.escapeString and isinstance(value, str):
				value = '"%s"' % str(value).replace('"', '\\"').replace('$', '\\$')
				lines = value.splitlines()
				result.append(format % fkt((key, self.delimeter, lines[0])))
				result.extend(map(lambda x: x + '\n', lines[1:]))
			else:
				result.append(format % fkt((key, self.delimeter, value)))
		return result


def genTarball(outFile, dir, pattern):
	tar = tarfile.open(outFile, 'w:gz')
	def walk(tar, root, dir):
		msg = QM(len(dir) > 50, dir[:15] + '...' + dir[len(dir)-32:], dir)
		activity = ActivityLog('Generating tarball: %s' % msg)
		for name in map(lambda x: os.path.join(dir, x), os.listdir(os.path.join(root, dir))):
			match = None
			for p in pattern:
				if fnmatch.fnmatch(name, p.lstrip('-')):
					match = not p.startswith('-')
			if match != False:
				if match or os.path.islink(os.path.join(root, name)):
					tar.add(os.path.join(root, name), name)
				elif os.path.isdir(os.path.join(root, name)):
					walk(tar, root, name)
		del activity
	walk(tar, dir, '')
	tar.close()


class AbstractObject:
	def __init__(self):
		raise AbstractError

	# Modify the module search path for some class
	def dynamicLoaderPath(cls, path = []):
		if not hasattr(cls, 'moduleMap'):
			cls.moduleMap = {}
			cls.modPath = [str.join('.', cls.__module__.split('.')[:-1])]
		cls.modPath = path + [cls.__module__] + cls.modPath
	dynamicLoaderPath = classmethod(dynamicLoaderPath)

	def open(cls, name, *args, **kwargs):
		# Yield search paths
		def searchPath(cname):
			cls.moduleMap = dict(map(lambda (k, v): (k.lower(), v), cls.moduleMap.items()))
			name = cls.moduleMap.get(cname.lower(), cname)
			yield name
			yield 'grid_control.%s' % name
			for path in cls.modPath:
				if not '.' in name:
					yield '%s.%s.%s' % (path, name.lower(), name)
				yield '%s.%s' % (path, name)

		mjoin = lambda x: str.join('.', x)
		for modName in searchPath(name):
			parts = modName.split('.')
			# Try to import missing modules
			try:
				for pkg in map(lambda (i, x): mjoin(parts[:i+1]), enumerate(parts[:-1])):
					if pkg not in sys.modules:
						__import__(pkg)
				newcls = getattr(sys.modules[mjoin(parts[:-1])], parts[-1])
				assert(not isinstance(newcls, type(sys.modules['grid_control'])))
			except:
				continue
			if issubclass(newcls, cls):
				return newcls(*args, **kwargs)
			raise ConfigError('%s is not of type %s' % (newcls, cls))
		raise ConfigError('%s "%s" does not exist in\n\t%s!' % (cls.__name__, name, str.join('\n\t', searchPath(name))))
	open = classmethod(open)


def vprint(text = '', level = 0, printTime = False, newline = True, once = False):
	if verbosity() > level:
		if once:
			if text in vprint.log:
				return
			vprint.log.append(text)
		if printTime:
			sys.stdout.write('%s - ' % time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()))
		sys.stdout.write('%s%s' % (text, QM(newline, '\n', '')))
vprint.log = []


def eprint(text = '', level = -1, printTime = False, newline = True):
	if verbosity() > level:
		if printTime:
			sys.stderr.write('%s - ' % time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()))
		sys.stderr.write('%s%s' % (text, QM(newline, '\n', '')))


def getVersion():
	try:
		version = LoggedProcess('svnversion', '-c %s' % pathGC()).getOutput(True).strip()
		if version != '':
			if 'stable' in LoggedProcess('svn info', pathGC()).getOutput(True):
				return '%s - stable' % version
			return '%s - testing' % version
	except:
		pass
	return 'unknown'
getVersion = lru_cache(getVersion)


def wait(timeout):
	shortStep = map(lambda x: (x, 1), range(max(timeout - 5, 0), timeout))
	for x, w in map(lambda x: (x, 5), range(0, timeout - 5, 5)) + shortStep:
		if abort():
			return False
		log = ActivityLog('waiting for %d seconds' % (timeout - x))
		time.sleep(w)
		del log
	return True


class ActivityLog:
	class Activity:
		def __init__(self, stream, message):
			self.stream = stream
			self.message = '%s...' % message
			self.status = False

		def run(self):
			if not self.status:
				self.stream.write(self.message)
				self.stream.flush()
				self.status = True

		def clear(self):
			if self.status:
				self.stream.write('\r%s\r' % (' ' * len(self.message)))
				self.stream.flush()
				self.status = False

	class WrappedStream:
		def __init__(self, stream, activity):
			self.__stream = stream
			self.__activity = activity
			self.__activity.run()

		def __del__(self):
			self.__activity.clear()

		def write(self, data):
			self.__activity.clear()
			retVal = self.__stream.write(data)
			if data.endswith('\n'):
				self.__activity.run()
			return retVal

		def __getattr__(self, name):
			return self.__stream.__getattribute__(name)

	def __init__(self, message):
		self.saved = (sys.stdout, sys.stderr)
		self.activity = self.Activity(sys.stdout, message)

		sys.stdout = self.WrappedStream(sys.stdout, self.activity)
		sys.stderr = self.WrappedStream(sys.stderr, self.activity)

	def __del__(self):
		sys.stdout, sys.stderr = self.saved


def printTabular(head, data, fmtString = '', fmt = {}, level = -1):
	justFunDict = { 'l': str.ljust, 'r': str.rjust, 'c': str.center }
	# justFun = {id1: str.center, id2: str.rjust, ...}
	justFun = dict(map(lambda (idx, x): (idx[0], justFunDict[x]), zip(head, fmtString)))

	maxlen = dict(map(lambda (id, name): (id, len(name)), head))
	head = [ x for x in head ]

	lenMap = {}
	entries = []
	for entry in data:
		if entry:
			tmp = {}
			for id, name in head:
				tmp[id] = str(fmt.get(id, str)(entry.get(id, '')))
				value = str(fmt.get(id, str)(entry.get(id, '')))
				stripped = re.sub('\33\[\d*(;\d*)*m', '', value)
				lenMap[value] = len(value) - len(stripped)
				maxlen[id] = max(maxlen.get(id, len(name)), len(stripped))
		else:
			tmp = entry
		entries.append(tmp)

	# adjust to maxlen of column (considering escape sequence correction)
	just = lambda id, x: justFun.get(id, str.rjust)(str(x), maxlen[id] + lenMap.get(str(x), 0))

	headentry = dict(map(lambda (id, name): (id, name.center(maxlen[id])), head))
	for entry in [headentry, None] + entries:
		applyFmt = lambda fun: map(lambda (id, name): just(id, fun(id)), head)
		if entry == None:
			vprint('=%s=' % str.join('=+=', applyFmt(lambda id: '=' * maxlen[id])), level)
		elif entry == '':
			vprint('-%s-' % str.join('-+-', applyFmt(lambda id: '-' * maxlen[id])), level)
		else:
			vprint(' %s ' % str.join(' | ', applyFmt(lambda id: entry.get(id, ''))), level)


def getUserInput(text, default, choices, parser = lambda x: x):
	while True:
		try:
			userinput = user_input('%s %s: ' % (text, '[%s]' % default))
		except:
			eprint()
			sys.exit(0)
		if userinput == '':
			return parser(default)
		if parser(userinput) != None:
			return parser(userinput)
		valid = str.join(', ', map(lambda x: '"%s"' % x, choices[:-1]))
		eprint('Invalid input! Answer with %s or "%s"' % (valid, choices[-1]))


def getUserBool(text, default):
	return getUserInput(text, QM(default, 'yes', 'no'), ['yes', 'no'], parseBool)


def deprecated(text):
	eprint('%s\n[DEPRECATED] %s' % (open(pathGC('share', 'fail.txt'), 'r').read(), text))
	if not getUserBool('Do you want to continue?', False):
		sys.exit(0)


def exitWithUsage(usage, msg = None):
	sys.stderr.write(QM(msg, '%s\n' % msg, ''))
	sys.stderr.write('Syntax: %s\nUse --help to get a list of options!\n' % usage)
	sys.exit(0)


if __name__ == '__main__':
	import doctest
	doctest.testmod()
