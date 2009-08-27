import os, ConfigParser, utils
from grid_control import ConfigError

class Config:
	def __init__(self, configFile):
		self.protocol = {}
		try:
			# try to parse config file
			self.parser = ConfigParser.ConfigParser()
			self.parser.read(configFile)
		except ConfigParser.Error, e:
			raise ConfigError("Configuration file `%s' contains an error: %s" % (configFile, e.message))

		# use the directory of the config file as base directory
		self.baseDir = os.path.abspath(os.path.normpath(os.path.dirname(configFile)))
		self.confName = str.join("", os.path.basename(configFile).split(".")[:-1])
		self.workDirDefault = os.path.join(self.baseDir, 'work.%s' % self.confName)

		# Read default values and reread main config file
		includeFile = self.getPath("global", "include", '')
		if includeFile != '':
			self.parser.read(includeFile)
			self.parser.read(configFile)


	def get(self, section, item, default = None, volatile = False):
		if not self.protocol.has_key(section):
			self.protocol[section] = {}
		if self.protocol[section].has_key(item):
			if self.protocol[section][item][1] != default:
				raise ConfigError("Inconsistent default values: [%s] %s" % (section, item))
		try:
			lines = self.parser.get(section, item).splitlines()
			lines = map(lambda x: x.split(';')[0].strip(), lines)
			value = str.join("\n", filter(lambda x: x != '', lines))
			self.protocol[section][item] = (value, default, volatile)
			return value
		except ConfigParser.NoSectionError:
			if default != None:
				utils.vprint("Using default value [%s] %s = %s" % (section, item, str(default)), 1)
				self.protocol[section][item] = (default, default, volatile)
				return default
			raise ConfigError("No section %s in config file." % section)
		except ConfigParser.NoOptionError:
			if default != None:
				utils.vprint("Using default value [%s] %s = %s" % (section, item, str(default)), 1)
				self.protocol[section][item] = (default, default, volatile)
				return default
			raise ConfigError("No option %s in section %s of config file." % (item, section))
		except:
			raise ConfigError("Parse error in option %s of config file section %s." % (item, section))


	def getPath(self, section, item, default = None, volatile = False):
		path = self.get(section, item, default, volatile)
		if path == '':
			return ''
		path = os.path.expanduser(path)	# ~/bla -> /home/user/bla
		path = os.path.normpath(path)   # xx/../yy -> yy
		if not os.path.isabs(path):	# ./lala -> /foo/bar/lala
			basePath = os.path.join(self.baseDir, path)
			if not os.path.exists(basePath) and os.path.exists(utils.atRoot(path)):
				path = utils.atRoot(path)
			else:
				path = basePath
		return path


	def getInt(self, section, item, default = None, volatile = False):
		return int(self.get(section, item, default, volatile))


	def getBool(self, section, item, default = None, volatile = False):
		value = self.get(section, item, default, volatile)
		try:
			return bool(int(value))
		except:
			return value.lower() in ('yes', 'y', 'true', 't', 'ok')


	def needInit(self, saveConfigPath):
		flag = False
		saveConfig = ConfigParser.ConfigParser()
		saveConfig.read(saveConfigPath)
		for section in self.protocol:
			for (key, (value, default, volatile)) in self.protocol[section].iteritems():
				try:
					oldValue = saveConfig.get(section, key)
				except:
					oldValue = default
				if (str(value).strip() != str(oldValue).strip()) and not volatile:
					if not flag:
						print "\nFound some changes in the config file, which will only apply"
						print "to the current task after a reinitialization:\n"
					print "[%s] %s = %s" % (section, key, value),
					if len(oldValue) + len(value) > 60:
						print
					print "  (old value: %s)" % oldValue
					flag = True
		if flag:
			print
		return flag
