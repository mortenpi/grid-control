import os, ConfigParser as cp
from grid_control import *

class Config:
	def __init__(self, configFile = None, configDict = {}):
		(self.allowSet, self.protoValue, self.protoSet, self.parser) = (True, {}, [], cp.ConfigParser())
		if configFile:
			# use the directory of the config file as base directory
			self.baseDir = os.path.abspath(os.path.normpath(os.path.dirname(configFile)))
			self.configFile = os.path.join(self.baseDir, os.path.basename(configFile))
			self.confName = str.join('', os.path.basename(configFile).split('.')[:-1])
			self.parseFile(self.parser, configFile)
		else:
			(self.baseDir, self.configFile, self.confName) = ('.', 'gc.conf', 'gc')
		self.workDirDefault = os.path.join(self.baseDir, 'work.%s' % self.confName)

		# Override config settings via dictionary
		for section in configDict:
			for item in configDict[section]:
				self.set(section, item, configDict[section][item])


	def parseFile(self, parser, configFile):
		def parseFileInt(fn, doExpansion = True):
			try:
				parser.readfp(open(fn, 'r'))
				# Expand config option extensions with '+='
				for section in parser.sections():
					for option in filter(lambda x: x.endswith('+'), parser.options(section)):
						if doExpansion:
							value = ''
							if parser.has_option(section, option.rstrip('+').strip()):
								value = self.parseLine(parser, section, option.rstrip('+').strip()) + '\n'
							value += self.parseLine(parser, section, option)
							self.set(section, option.rstrip('+').strip(), value)
						parser.remove_option(section, option)
			except:
				raise RethrowError("Error while reading configuration file '%s'!" % fn)
		userDefaultsFile = utils.resolvePath('~/.grid-control.conf', check = False)
		if os.path.exists(userDefaultsFile):
			parseFileInt(userDefaultsFile)
		parseFileInt(configFile, False)
		# Read default values and reread main config file
		for includeFile in self.getPaths('global', 'include', ''):
			parseFileInt(includeFile)
		parseFileInt(configFile)


	def parseLine(self, parser, section, option):
		# Split into lines, remove comments and return merged result
		lines = parser.get(section, option).splitlines()
		lines = map(lambda x: x.split(';')[0].strip(), lines)
		return str.join('\n', filter(lambda x: x != '', lines))


	def set(self, section, item, value = None, override = True):
		if not self.allowSet:
			raise APIError('Invalid runtime config override: [%s] %s = %s' % (str(section), str(item), str(value)))
		utils.vprint('Config option was overridden: [%s] %s = %s' % (str(section), str(item), str(value)), 2)
		if not self.parser.has_section(str(section)):
			self.parser.add_section(str(section))
		if (not self.parser.has_option(str(section), str(item))) or override:
			self.parser.set(str(section), str(item), str(value))
			self.protoSet.append((str(section), str(item)))


	def get(self, section, item, default = None, volatile = False, noVar = True):
		# Check result, Make protocol of config queries and flag inconsistencies
		def checkResult(value):
			if item in self.protoValue.setdefault(section, {}):
				if self.protoValue[section][item][1] != default:
					raise APIError('Inconsistent default values: [%s] %s' % (section, item))
			self.protoValue[section][item] = (value, default, volatile)
			return utils.checkVar(value, '[%s] %s may not contain variables.' % (section, item), noVar)
		# Default value helper function
		def tryDefault(errorMessage):
			if default != None:
				utils.vprint('Using default value [%s] %s = %s' % (section, item, str(default)), 3)
				return checkResult(default)
			raise ConfigError(errorMessage)
		# Read from config file or return default if possible
		try:
			value = self.parseLine(self.parser, str(section), item)
		except cp.NoSectionError:
			return tryDefault('No section [%s] in config file!' % section)
		except cp.NoOptionError:
			return tryDefault('[%s] "%s" does not exist!' % (section, item))
		except:
			raise ConfigError('[%s] "%s" could not be parsed!' % (section, item))
		return checkResult(value)


	def getPaths(self, section, item, default = None, volatile = False, noVar = True, check = True):
		value = self.get(section, item, default, volatile, noVar)
		return map(lambda x: utils.resolvePath(x, [self.baseDir], check, ConfigError), value.splitlines())


	def getPath(self, section, item, default = None, volatile = False, noVar = True, check = True):
		return (self.getPaths(section, item, default, volatile, noVar, check) + [''])[0]


	def getInt(self, section, item, default = None, volatile = False, noVar = True):
		return int(self.get(section, item, default, volatile, noVar))


	def getBool(self, section, item, default = None, volatile = False, noVar = True):
		return utils.parseBool(self.get(section, item, QM(default, 'true', 'false'), volatile, noVar))


	def getList(self, section, item, default = [], volatile = False, noVar = True, delim = None):
		return utils.parseList(self.get(section, item, '', volatile, noVar), delim, onEmpty = default)


	# Compare this config object to another config file
	# Return true in case non-volatile parameters are changed
	def needInit(self, saveConfigPath):
		if not os.path.exists(saveConfigPath):
			return False
		saveConfig = cp.ConfigParser()
		self.parseFile(saveConfig, saveConfigPath)
		flag = False
		for section in self.protoValue:
			for (key, (value, default, volatile)) in self.protoValue[section].iteritems():
				try:
					oldValue = self.parseLine(saveConfig, section, key)
				except:
					oldValue = default
				if (str(value).strip() != str(oldValue).strip()) and not volatile:
					if not flag:
						utils.eprint('\nFound some changes in the config file, which will only apply')
						utils.eprint('to the current task after a reinitialization:\n')
					outputLine = '[%s] %s = %s' % (section, key, value)
					outputLine += QM(len(outputLine) > 60, '\n', '') + '  (old value: %s)' % oldValue
					utils.eprint(outputLine)
					flag = True
		return flag


	def prettyPrint(self, stream, printDefault):
		stream.write("\n; %s\n; This is the %s set of used config options:\n; %s\n\n" % \
			("="*60, utils.QM(printDefault, 'complete', 'minimal'), "="*60))
		output = {} # {'section1': [output1, output2, ...], 'section2': [...output...], ...}
		for section in self.protoValue:
			for (key, (value, default, volatile)) in sorted(self.protoValue[section].iteritems()):
				if ((section == 'global') and (key == 'include')) or ((str(section), str(key)) in self.protoSet):
					continue # included statements are already in the protocol & skip runtime settings
				if (not printDefault and (str(value) != str(default))) or printDefault:
					value = str(value).replace("\n", "\n\t") # format multi-line options
					output.setdefault(section.lower(), ["[%s]" % section]).append("%s = %s" % (key, value))
					if default != None and not printDefault:
						output[section.lower()].append("; Default setting: %s = %s" % (key, default))
		stream.write("%s\n" % str.join('\n\n', map(lambda s: str.join('\n', output[s]), sorted(output))))
