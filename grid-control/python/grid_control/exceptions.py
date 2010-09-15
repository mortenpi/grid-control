import sys

# our exception base class
class GCError(Exception):
	def __init__(self, msg):
		GCError.message = "%s: %s\n" % (sys.argv[0], msg)

class GridError(GCError):
	pass

class ConfigError(GCError):
	pass

# some error with the Grid installation
class InstallationError(GridError):
	pass	# just inherit everything from GridError

# some error with the user (PEBKAC)
class UserError(GridError):
	pass	# just inherit everything from GridError

# some error with the runtime
class RuntimeError(GridError):
	pass	# just inherit everything from GridError

# some error in using the API
class APIError(GridError):
	pass	# just inherit everything from GridError

# some error with the runtime
class AbstractError(APIError):
	def __init__(self):
		APIError.__init__(self, "%s is an abstract function!" % sys._getframe(1).f_code.co_name)

# some error with the dataset
class DatasetError(GridError):
	pass	# just inherit everything from GridError
