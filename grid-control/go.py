#!/usr/bin/env python
import sys, os

# add python subdirectory from where go.py was started to search path
_root = os.path.dirname(os.path.abspath(os.path.normpath(sys.argv[0])))
sys.path.append(os.path.join(_root, 'python'))

# and include grid_control python module
from grid_control import *

###
### main program
###
if __name__ == '__main__':
	try:
		proxy = Proxy()
		print 'Your proxy has %d seconds left!' % proxy.timeleft()

	except GridError, e:
		e.showMessage()
		sys.exit(1)

